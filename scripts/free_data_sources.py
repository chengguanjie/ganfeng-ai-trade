"""
赣丰玻纤 · 免费数据源接入层（真实 API）
========================================

四个真实数据源，全部免费、无需付费订阅：

┌────────────────┬──────────────────────────────────────────────┬────────┐
│ 数据源         │ 用途                                          │ 缓存   │
├────────────────┼──────────────────────────────────────────────┼────────┤
│ UN Comtrade    │ HS 7019 各国进口额 + 同比增速（市场规模维度） │ 24h    │
│ World Bank WITS│ HS 701959 各国 MFN 关税（出海易度维度）       │ 7d     │
│ World Bank IND │ GDP / GDP增速 / 城镇化增速（需求动能）        │ 7d     │
│ Google Trends  │ 8 个核心关键词热度 + 同比（增速维度）         │ 12h    │
└────────────────┴──────────────────────────────────────────────┴────────┘

三级降级策略，保证永不阻断业务：
    真实 API  →  过期缓存(stale)  →  内置基线数据(fallback)

每个返回值都带 `status` 字段标明数据来源真实性：
    live / cached / stale / fallback
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

from db import cache_get, cache_put  # type: ignore

logger = logging.getLogger("data_sources")

DATA_DIR = os.path.join(os.path.dirname(THIS_DIR), "data")
SKU_FILE = os.path.join(DATA_DIR, "sku.json")

HTTP_TIMEOUT = int(os.environ.get("DATA_HTTP_TIMEOUT", "30"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _http_json(url: str, timeout: int = HTTP_TIMEOUT) -> Any:
    req = urllib.request.Request(url, headers={
        "User-Agent": "GanfengTradeBot/1.0 (+https://ganfeng-trade.example)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ============================================================
# 目标市场主数据（三套编码体系的映射）
# ============================================================
class Market:
    __slots__ = ("name_en", "name_zh", "comtrade", "wits", "wb")

    def __init__(self, name_en: str, name_zh: str, comtrade: int, wits: int, wb: str):
        self.name_en = name_en
        self.name_zh = name_zh
        self.comtrade = comtrade   # Comtrade reporterCode
        self.wits = wits           # ISO 3166 numeric（WITS 用）
        self.wb = wb               # ISO 3166 alpha-3（World Bank 用）


MARKETS: list[Market] = [
    Market("USA",          "美国",     842, 840, "USA"),
    Market("Germany",      "德国",     276, 276, "DEU"),
    Market("France",       "法国",     251, 250, "FRA"),
    Market("Saudi Arabia", "沙特",     682, 682, "SAU"),
    Market("UAE",          "阿联酋",   784, 784, "ARE"),
    Market("Vietnam",      "越南",     704, 704, "VNM"),
    Market("India",        "印度",     699, 356, "IND"),
    Market("Brazil",       "巴西",     76,  76,  "BRA"),
    Market("Turkey",       "土耳其",   792, 792, "TUR"),
    Market("Mexico",       "墨西哥",   484, 484, "MEX"),
]

HS_CHAPTER = "7019"      # 玻璃纤维及其制品（Comtrade 4 位可查）
HS_PRODUCT = "701959"    # 玻纤机织物 其他（WITS 需 6 位）

# HS7019 全球年进口额行业基线（USD 十亿）。仅在实时数据覆盖不足时作为下限，
# 避免「只有美国报数」这类情况把市场规模评分打到不合理的低位。
BASELINE_GLOBAL_IMPORT_B = 7.0


# ============================================================
# 基类：三级降级 + 缓存
# ============================================================
class BaseSource:
    name = "base"
    ttl = 3600
    label = "数据源"
    budget = 120.0     # 单次实时抓取的时间预算（秒），超时就返回已拿到的部分

    def _fetch_live(self) -> dict[str, Any]:
        raise NotImplementedError

    def _fallback(self) -> dict[str, Any]:
        raise NotImplementedError

    def fetch(self, force: bool = False, allow_live: bool = True) -> dict[str, Any]:
        """取数。

        allow_live=False 用于 Web 请求路径：只读缓存，缓存缺失直接用内置
        基线，绝不发起可能耗时数分钟的外部请求。实时抓取交给后台线程或
        命令行 `python scripts/free_data_sources.py --force`。
        """
        if not force:
            hit = cache_get(self.name, self.ttl)
            if hit:
                hit["status"] = "cached"
                return hit

        if not allow_live:
            stale = cache_get(self.name, ttl_seconds=10 ** 9)
            if stale:
                stale["status"] = "stale"
                return stale
            fb = self._fallback()
            fb["source"] = self.label
            fb["status"] = "fallback"
            fb["reason"] = "缓存未预热；调用 /api/data-sources?refresh=1 触发后台抓取"
            fb["fetched_at"] = _now_iso()
            return fb

        try:
            data = self._fetch_live()
            data["source"] = self.label
            data["status"] = "live"
            data["fetched_at"] = _now_iso()
            cache_put(self.name, data, "live")
            return data
        except Exception as e:
            logger.warning("%s live fetch failed: %s", self.name, e)
            stale = cache_get(self.name, ttl_seconds=10 ** 9)
            if stale:
                stale["status"] = "stale"
                stale["error"] = str(e)[:200]
                return stale
            fb = self._fallback()
            fb["source"] = self.label
            fb["status"] = "fallback"
            fb["error"] = str(e)[:200]
            fb["fetched_at"] = _now_iso()
            return fb


# ============================================================
# 1. UN Comtrade —— 各国 HS7019 进口额与同比
# ============================================================
class ComtradeAdapter(BaseSource):
    """UN Comtrade 各国 HS7019 进口额。

    实测约束（均已验证）：
      · 只能「单 reporter + 单 period」查询，传逗号列表或多年份都会返回空
      · partnerCode=0 表示「世界」，返回该国该年的进口总额（1 行聚合值）
      · 有速率限制，请求之间必须 sleep
      · 免费的 /public/v1/preview/ 端点是抽样数据集，覆盖不全：实测只有
        美国等少数报告国有非零值，德国等长期返回 0。要拿到完整覆盖，需在
        https://comtradeplus.un.org 免费注册后把 Key 填到 COMTRADE_API_KEY，
        本适配器会自动切到 /data/v1/get/ 正式端点。
    """
    name = "comtrade_hs7019_v2"
    ttl = 24 * 3600
    label = "UN Comtrade"
    BASE_PREVIEW = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
    BASE_FULL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
    THROTTLE = float(os.environ.get("COMTRADE_THROTTLE", "1.5"))
    budget = 240.0

    # 年度完整性探针：选在这个数据集里报数最稳的三个国家
    PROBE_REPORTERS = [842, 682, 484]   # 美国 / 沙特 / 墨西哥

    # 年进口额低于此值的「市场」基本是数据假象。德国实际年进口约 10 亿美元，
    # 预览端点却只返回 70 万，直接参与计算会让同比出现 +700968% 这种数字。
    MIN_PLAUSIBLE_USD = 5_000_000

    # 候选年度的探针总额不足上一年的这个比例，说明该年尚未报完，回退一年。
    COMPLETENESS_RATIO = 0.70

    @property
    def api_key(self) -> str:
        return os.environ.get("COMTRADE_API_KEY", "").strip()

    def _query(self, reporter: int, year: int) -> dict[str, float] | None:
        """返回该国该年进口额；无数据、为 0 或低于可信下限时返回 None。"""
        params = {
            "reporterCode": str(reporter),
            "period": str(year),
            "cmdCode": HS_CHAPTER,
            "flowCode": "M",       # M = Imports
            "partnerCode": "0",    # 0 = World
        }
        base = self.BASE_PREVIEW
        if self.api_key:
            base = self.BASE_FULL
            params["subscription-key"] = self.api_key
        payload = _http_json(f"{base}?{urllib.parse.urlencode(params)}")
        rows = [r for r in (payload.get("data") or []) if str(r.get("cmdCode")) == HS_CHAPTER]
        if not rows:
            return None
        value = float(rows[0].get("primaryValue") or 0)
        if value < self.MIN_PLAUSIBLE_USD:
            return None
        return {
            "value_usd": value,
            "net_weight_kg": float(rows[0].get("netWgt") or 0),
        }

    def _probe_total(self, year: int, memo: dict[int, float]) -> float:
        """探针国在该年度的进口额之和（已过滤不可信小额）。"""
        if year in memo:
            return memo[year]
        total = 0.0
        for rep in self.PROBE_REPORTERS:
            try:
                v = self._query(rep, year)
                if v:
                    total += v["value_usd"]
            except Exception as e:
                logger.debug("comtrade probe %s %s: %s", rep, year, e)
            time.sleep(self.THROTTLE)
        memo[year] = total
        return total

    def _latest_year(self) -> int:
        """选出「最新且已报完」的年度。

        单看「某年有没有数据」会选中当年或去年这种只报了几个月的年度：
        实测 2025 年美国 15.4 亿、沙特 1.9 亿，同比却是 -9% 与 -47%，
        因为年度尚未报完。因此用探针国总额与上一年对比来判断完整性。
        """
        current = datetime.now(timezone.utc).year
        memo: dict[int, float] = {}
        for y in range(current - 1, current - 4, -1):
            cur_total = self._probe_total(y, memo)
            if cur_total <= 0:
                continue
            prev_total = self._probe_total(y - 1, memo)
            ratio = (cur_total / prev_total) if prev_total > 0 else 1.0
            logger.info(
                "comtrade 年度完整性 %s: 探针总额 $%.0fM vs %s 的 $%.0fM（比值 %.2f）",
                y, cur_total / 1e6, y - 1, prev_total / 1e6, ratio,
            )
            if ratio >= self.COMPLETENESS_RATIO:
                return y
        # 都不达标就取探针总额最大的年度
        return max(memo, key=lambda k: memo[k]) if memo else current - 2

    def _fetch_live(self) -> dict[str, Any]:
        deadline = time.time() + self.budget
        latest = self._latest_year()
        prior = latest - 1
        markets: list[dict[str, Any]] = []
        truncated = False

        for m in MARKETS:
            if time.time() > deadline:
                truncated = True
                logger.warning("comtrade 超出 %.0fs 预算，已取 %d 个市场", self.budget, len(markets))
                break
            cur = prev = None
            try:
                cur = self._query(m.comtrade, latest)
            except Exception as e:
                logger.debug("comtrade %s %s: %s", m.name_en, latest, e)
            time.sleep(self.THROTTLE)
            try:
                prev = self._query(m.comtrade, prior)
            except Exception as e:
                logger.debug("comtrade %s %s: %s", m.name_en, prior, e)
            time.sleep(self.THROTTLE)

            if not cur:
                continue
            # 两年都过了可信下限才算同比，并钳制在 ±80% 内挡住残留异常值
            yoy = None
            if prev:
                yoy = round(max(-80.0, min(80.0, (cur["value_usd"] / prev["value_usd"] - 1) * 100)), 1)
            markets.append({
                "country": m.name_en,
                "country_zh": m.name_zh,
                "import_usd_million": round(cur["value_usd"] / 1e6, 1),
                "net_weight_ton": round(cur["net_weight_kg"] / 1000, 0),
                "yoy_growth_pct": yoy,
                "avg_unit_price_usd_per_kg": (
                    round(cur["value_usd"] / cur["net_weight_kg"], 2)
                    if cur["net_weight_kg"] > 0 else None
                ),
            })

        if not markets:
            raise RuntimeError("Comtrade 未返回任何市场数据")

        markets.sort(key=lambda x: x["import_usd_million"], reverse=True)
        reported_m = sum(x["import_usd_million"] for x in markets)
        # 用中位数而非均值：样本只有几个国家时，单个异常值会把均值整体带偏
        yoys = sorted(x["yoy_growth_pct"] for x in markets if x["yoy_growth_pct"] is not None)
        if yoys:
            mid = len(yoys) // 2
            median_yoy = yoys[mid] if len(yoys) % 2 else (yoys[mid - 1] + yoys[mid]) / 2
        else:
            median_yoy = 0.0
        median_yoy = round(median_yoy, 1)

        coverage = len(markets) / len(MARKETS)
        is_partial = coverage < 0.6

        # 覆盖不足时不能把「已报告国之和」当成全球规模（会严重低估），
        # 以行业基线为下限，并显式标注 size_basis 供人工核查。
        reported_b = round(reported_m / 1000, 2)
        if is_partial:
            size_b = max(reported_b, BASELINE_GLOBAL_IMPORT_B)
            size_basis = "baseline-floor（免费预览端点覆盖不足，已用行业基线兜底）"
        else:
            size_b = reported_b
            size_basis = "reported（目标市场实际进口额加总）"

        return {
            "hs_code": HS_CHAPTER,
            "data_year": latest,
            "base_year": prior,
            "endpoint": "full(keyed)" if self.api_key else "public-preview",
            "markets_reported": len(markets),
            "markets_total": len(MARKETS),
            "coverage_ratio": round(coverage, 2),
            "is_partial": is_partial,
            "truncated": truncated,
            "size_basis": size_basis,
            "hint": (
                "覆盖不全是免费预览端点的抽样限制；到 https://comtradeplus.un.org "
                "免费注册后填 COMTRADE_API_KEY 即可获得完整数据"
                if is_partial else None
            ),
            "metrics": {
                # 以下 3 个 key 是选品引擎的契约字段，勿改名
                "global_import_usd_billion": size_b,
                "reported_import_usd_billion": reported_b,
                "yoy_growth_pct": median_yoy,
                "yoy_basis": f"{len(yoys)} 个报告国进口额同比的中位数",
                "top_importers_2024": [
                    {"country": x["country"], "import_usd_million": x["import_usd_million"]}
                    for x in markets
                ],
                "market_detail": markets,
            },
        }

    def _fallback(self) -> dict[str, Any]:
        return {
            "hs_code": HS_CHAPTER,
            "data_year": 2023,
            "note": "内置基线（依据 2023 年公开统计整理），仅在 API 不可达时使用",
            "metrics": {
                "global_import_usd_billion": 7.22,
                "yoy_growth_pct": 4.2,
                "top_importers_2024": [
                    {"country": "USA", "import_usd_million": 1598.9},
                    {"country": "Germany", "import_usd_million": 987.0},
                    {"country": "France", "import_usd_million": 512.0},
                    {"country": "India", "import_usd_million": 365.0},
                    {"country": "Mexico", "import_usd_million": 342.0},
                    {"country": "Vietnam", "import_usd_million": 278.0},
                    {"country": "Saudi Arabia", "import_usd_million": 268.0},
                    {"country": "Turkey", "import_usd_million": 231.0},
                    {"country": "Brazil", "import_usd_million": 192.0},
                    {"country": "UAE", "import_usd_million": 178.0},
                ],
                "market_detail": [],
            },
        }


# ============================================================
# 2. World Bank WITS —— MFN 关税
# ============================================================
class WITSAdapter(BaseSource):
    """WITS SDMX 接口，无需 Key。必须用 6 位 HS 编码。

    性能陷阱：查询不存在的年份时，WITS 要花约 30 秒才返回 404。逐国逐年
    重试会把时间预算全烧在无效年份上（实测 10 国 × 2 年 = 290s，一个结果
    都拿不到）。所以先用一个参照国探测出有数据的年份，再用该年份查所有国家。
    """
    name = "wits_tariff_701959_v2"
    ttl = 7 * 24 * 3600
    label = "World Bank WITS"
    # WITS 在高频访问下会快速返回 403 限流，间隔要给足
    THROTTLE = float(os.environ.get("WITS_THROTTLE", "2.0"))
    YEARS = [2021, 2020, 2022]   # 实测 2021 有数据，2022 无（返回 404）
    PROBE_REPORTER = 840         # 美国，报数最全
    # WITS 单次响应实测稳定在 26-29 秒，超时必须给足，否则一个都拿不到
    REQ_TIMEOUT = int(os.environ.get("WITS_TIMEOUT", "45"))
    budget = 420.0

    def _query(self, reporter_num: int, year: int) -> float | None:
        url = (
            "https://wits.worldbank.org/API/V1/SDMX/V21/datasource/TRN"
            f"/reporter/{reporter_num}/partner/000/product/{HS_PRODUCT}"
            f"/year/{year}/datatype/reported?format=JSON"
        )
        payload = _http_json(url, timeout=self.REQ_TIMEOUT)
        try:
            series = payload["dataSets"][0]["series"]
            first = next(iter(series.values()))
            return round(float(first["observations"]["0"][0]), 2)
        except (KeyError, IndexError, StopIteration, TypeError, ValueError):
            return None

    def _discover_year(self, deadline: float) -> int | None:
        """探测出一个确实有数据的年份，避免每个国家都去撞无效年份。"""
        for y in self.YEARS:
            if time.time() > deadline:
                return None
            try:
                if self._query(self.PROBE_REPORTER, y) is not None:
                    logger.info("wits 采用年份 %s", y)
                    return y
            except Exception as e:
                logger.debug("wits 年份探测 %s: %s", y, e)
            time.sleep(self.THROTTLE)
        return None

    def _fetch_live(self) -> dict[str, Any]:
        deadline = time.time() + self.budget
        year = self._discover_year(deadline)
        if year is None:
            raise RuntimeError("WITS 无可用年份（接口超时或数据缺失）")

        overview: list[dict[str, Any]] = []
        for m in MARKETS:
            tariff = None
            if time.time() > deadline:
                logger.warning("wits 超出 %.0fs 预算，剩余 %d 国用基线关税",
                               self.budget, len(MARKETS) - len(overview))
            else:
                try:
                    tariff = self._query(m.wits, year)
                except Exception as e:
                    logger.debug("wits %s %s: %s", m.name_en, year, e)
                time.sleep(self.THROTTLE)
            overview.append({
                "country": m.name_en,
                "country_zh": m.name_zh,
                "avg_mfn_tariff_pct": tariff if tariff is not None else _TARIFF_BASELINE.get(m.name_en),
                "tariff_code": HS_PRODUCT,
                "data_year": year if tariff is not None else None,
                "is_reported": tariff is not None,
            })

        if not any(o["is_reported"] for o in overview):
            raise RuntimeError("WITS 未返回任何关税数据")

        return {
            "hs_code": HS_PRODUCT,
            "data_year": year,
            "reported_count": sum(1 for o in overview if o["is_reported"]),
            "metrics": {
                "tariff_overview": overview,
                "nontariff_barriers_index": _NTB_INDEX,
            },
        }

    def _fallback(self) -> dict[str, Any]:
        return {
            "hs_code": HS_PRODUCT,
            "note": "内置基线关税",
            "metrics": {
                "tariff_overview": [
                    {
                        "country": m.name_en,
                        "country_zh": m.name_zh,
                        "avg_mfn_tariff_pct": _TARIFF_BASELINE.get(m.name_en),
                        "tariff_code": HS_PRODUCT,
                        "is_reported": False,
                    }
                    for m in MARKETS
                ],
                "nontariff_barriers_index": _NTB_INDEX,
            },
        }


_TARIFF_BASELINE = {
    "USA": 3.58, "Germany": 7.0, "France": 7.0, "Saudi Arabia": 5.0,
    "UAE": 5.0, "Vietnam": 12.0, "India": 10.0, "Brazil": 12.6,
    "Turkey": 7.0, "Mexico": 10.0,
}

# 非关税壁垒（需要人工维护的行业知识，非 API 可得）
_NTB_INDEX = {
    "USA": "low", "Germany": "medium-CE-marking", "France": "medium-CE-marking",
    "Saudi Arabia": "low-SASO", "UAE": "low-ECAS", "Vietnam": "low",
    "India": "medium-BIS", "Brazil": "medium-INMETRO", "Turkey": "medium-CE",
    "Mexico": "medium-NOM",
}


# ============================================================
# 3. World Bank Indicators —— 宏观需求动能
# ============================================================
class WorldBankAdapter(BaseSource):
    """GDP / GDP 增速 / 城镇人口增速 → 建筑需求动能代理指标。无需 Key。"""
    name = "worldbank_macro"
    ttl = 7 * 24 * 3600
    label = "World Bank Indicators"
    INDICATORS = {
        "gdp_usd": "NY.GDP.MKTP.CD",
        "gdp_growth_pct": "NY.GDP.MKTP.KD.ZG",
        "urban_growth_pct": "SP.URB.GROW",
    }

    def _query(self, iso3: str, indicator: str) -> tuple[float, int] | None:
        url = (
            f"https://api.worldbank.org/v2/country/{iso3}/indicator/{indicator}"
            "?format=json&per_page=10&date=2019:2024"
        )
        payload = _http_json(url)
        if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
            return None
        for row in payload[1]:                      # 已按年份倒序
            if row.get("value") is not None:
                return float(row["value"]), int(row["date"])
        return None

    def _fetch_live(self) -> dict[str, Any]:
        iso_list = ";".join(m.wb for m in MARKETS)
        out: dict[str, dict[str, Any]] = {}
        for key, code in self.INDICATORS.items():
            url = (
                f"https://api.worldbank.org/v2/country/{iso_list}/indicator/{code}"
                "?format=json&per_page=400&date=2019:2024"
            )
            payload = _http_json(url)
            if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
                continue
            best: dict[str, tuple[float, int]] = {}
            for row in payload[1]:
                iso = row.get("countryiso3code")
                val = row.get("value")
                if not iso or val is None:
                    continue
                year = int(row["date"])
                if iso not in best or year > best[iso][1]:
                    best[iso] = (float(val), year)
            for iso, (val, year) in best.items():
                out.setdefault(iso, {})[key] = round(val, 2)
                out[iso][f"{key}_year"] = year

        if not out:
            raise RuntimeError("World Bank 未返回数据")

        by_market = []
        for m in MARKETS:
            d = out.get(m.wb, {})
            gdp_g = d.get("gdp_growth_pct") or 0
            urb_g = d.get("urban_growth_pct") or 0
            # 建筑需求动能：GDP 增速 60% + 城镇化增速 40%，归一到 0-100
            momentum = max(0.0, min(100.0, (gdp_g * 0.6 + urb_g * 0.4) * 12.5))
            by_market.append({
                "country": m.name_en,
                "country_zh": m.name_zh,
                "gdp_usd_billion": round(d["gdp_usd"] / 1e9, 1) if d.get("gdp_usd") else None,
                "gdp_growth_pct": d.get("gdp_growth_pct"),
                "urban_growth_pct": d.get("urban_growth_pct"),
                "construction_momentum_index": round(momentum, 1),
                "data_year": d.get("gdp_usd_year"),
            })
        by_market.sort(key=lambda x: x["construction_momentum_index"], reverse=True)
        return {
            "indicators": list(self.INDICATORS.values()),
            "metrics": {
                "macro_by_market": by_market,
                "top_momentum_market": by_market[0]["country"] if by_market else None,
            },
        }

    def _fallback(self) -> dict[str, Any]:
        return {
            "note": "内置基线宏观数据",
            "metrics": {
                "macro_by_market": [
                    {"country": "India", "country_zh": "印度", "gdp_growth_pct": 7.2, "urban_growth_pct": 2.3,
                     "construction_momentum_index": 65.5},
                    {"country": "Vietnam", "country_zh": "越南", "gdp_growth_pct": 5.1, "urban_growth_pct": 2.9,
                     "construction_momentum_index": 52.8},
                    {"country": "Saudi Arabia", "country_zh": "沙特", "gdp_growth_pct": 4.4, "urban_growth_pct": 1.7,
                     "construction_momentum_index": 41.5},
                    {"country": "UAE", "country_zh": "阿联酋", "gdp_growth_pct": 3.6, "urban_growth_pct": 1.5,
                     "construction_momentum_index": 34.5},
                    {"country": "Turkey", "country_zh": "土耳其", "gdp_growth_pct": 4.5, "urban_growth_pct": 1.9,
                     "construction_momentum_index": 43.3},
                ],
                "top_momentum_market": "India",
            },
        }


# ============================================================
# 4. Google Trends —— 关键词热度
# ============================================================
# 选品引擎依赖这 8 个 key，勿改名
TREND_KEYWORDS = [
    "fiberglass mesh",              # 锚点关键词（两批共用，用于归一化）
    "alkali resistant mesh",
    "EIFS mesh",
    "drywall joint tape",
    "waterproofing mesh",
    "solar PV reinforcement mesh",
    "marine fiberglass mesh",
    "GRC reinforcement mesh",
]


class GoogleTrendsAdapter(BaseSource):
    """pytrends。Google 限制单次最多 5 个词，故分两批用锚点词归一化。

    重要约束：玻纤网格布这类小众 B2B 词的全球搜索量极低，归一化后常年
    趋近 0。此时 Google 的抽样噪声会让同比出现 +400% 这种假信号，因此
    低于 MIN_VOLUME 的关键词一律不输出同比，交由 Comtrade 的真实进口
    增速兜底（见 DataAggregator.score_one_sku）。
    """
    name = "google_trends_v2"
    ttl = 12 * 3600
    label = "Google Trends"
    ANCHOR = TREND_KEYWORDS[0]
    # 归一化后均值低于 20 的词，周度序列里大量是 0 和个位数，同比纯属抽样噪声。
    # 实测 "drywall joint tape" 均值 11.4 就能算出 +90% 的假增长。
    MIN_VOLUME = 20.0

    def _fetch_live(self) -> dict[str, Any]:
        from pytrends.request import TrendReq  # 延迟导入，未安装时走降级

        # 不传 retries / backoff_factor：pytrends 会用 urllib3 v1 已废弃的
        # method_whitelist 参数构造 Retry，在 urllib3 v2 下直接抛 TypeError
        pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 25))

        batch1 = TREND_KEYWORDS[0:5]
        batch2 = [self.ANCHOR] + TREND_KEYWORDS[5:8]

        # Google 已不接受 "today 24-m" 这类相对区间（返回 400），必须给显式日期
        today = datetime.now(timezone.utc).date()
        start = today.replace(year=today.year - 2)
        timeframe = f"{start.isoformat()} {today.isoformat()}"

        def run(kws: list[str]):
            pytrends.build_payload(kws, timeframe=timeframe, geo="")
            df = pytrends.interest_over_time()
            if df is None or df.empty:
                raise RuntimeError(f"Trends 空结果: {kws}")
            if "isPartial" in df.columns:
                df = df.drop(columns=["isPartial"])
            n = len(df)
            recent = df.iloc[n // 2:]      # 近 12 个月
            older = df.iloc[: n // 2]      # 上 12 个月
            return recent.mean().to_dict(), older.mean().to_dict()

        r1, o1 = run(batch1)
        time.sleep(2)
        r2, o2 = run(batch2)

        # 用锚点词把第二批缩放到第一批的量纲
        scale = (r1[self.ANCHOR] / r2[self.ANCHOR]) if r2.get(self.ANCHOR) else 1.0

        def measure(recent: float, older: float) -> dict[str, Any]:
            if recent < self.MIN_VOLUME or older < self.MIN_VOLUME:
                return {
                    "score": round(recent, 1),
                    "yoy_change_pct": None,
                    "confidence": "low",
                    "note": f"归一化搜索量 < {self.MIN_VOLUME}，同比不可信，改用 Comtrade 进口增速",
                }
            yoy = (recent / older - 1) * 100
            return {
                "score": round(recent, 1),
                "yoy_change_pct": round(max(-60.0, min(60.0, yoy)), 1),
                "confidence": "high",
            }

        interest: dict[str, dict[str, Any]] = {}
        for kw in batch1:
            interest[kw] = measure(r1[kw], o1[kw])
        for kw in batch2[1:]:
            interest[kw] = measure(r2[kw] * scale, o2[kw] * scale)

        trusted = {k: v for k, v in interest.items() if v["confidence"] == "high"}
        top = (
            max(trusted.items(), key=lambda kv: kv[1]["yoy_change_pct"])[0]
            if trusted else None
        )
        return {
            "min_volume_threshold": self.MIN_VOLUME,
            "trusted_keywords": len(trusted),
            "timeframe": f"{timeframe}（近12月 vs 上12月）",
            "anchor_scale": round(scale, 3),
            "metrics": {
                "keyword_interest_2024": interest,
                "top_growing_query": top,
            },
        }

    def _fallback(self) -> dict[str, Any]:
        return {
            "note": "内置基线热度（pytrends 不可用或被限流时使用）",
            "metrics": {
                "keyword_interest_2024": {
                    kw: {"score": s, "yoy_change_pct": y, "confidence": "baseline"}
                    for kw, s, y in [
                        ("fiberglass mesh", 72.0, 6.5),
                        ("alkali resistant mesh", 58.0, 11.2),
                        ("EIFS mesh", 49.0, 3.0),
                        ("drywall joint tape", 86.0, 1.8),
                        ("waterproofing mesh", 65.0, 8.7),
                        ("solar PV reinforcement mesh", 34.0, 18.4),
                        ("marine fiberglass mesh", 28.0, 14.0),
                        ("GRC reinforcement mesh", 41.0, 5.5),
                    ]
                },
                "top_growing_query": "solar PV reinforcement mesh",
            },
        }


# ============================================================
# 顶层聚合
# ============================================================
class DataAggregator:
    """所有数据源的统一入口。实例内做一次内存缓存，避免单次请求重复取数。

    allow_live 默认 False：Web 请求只读缓存，保证响应在毫秒级。
    后台刷新线程和命令行用 allow_live=True。
    """

    def __init__(self, allow_live: bool = False) -> None:
        self.comtrade = ComtradeAdapter()
        self.wits = WITSAdapter()
        self.worldbank = WorldBankAdapter()
        self.trends = GoogleTrendsAdapter()
        self.allow_live = allow_live
        self._memo: dict[str, dict] = {}

    # 兼容旧属性名
    @property
    def search(self):
        return self.trends

    def _cached(self, adapter: BaseSource, force: bool = False) -> dict[str, Any]:
        if force or adapter.name not in self._memo:
            self._memo[adapter.name] = adapter.fetch(
                force=force, allow_live=self.allow_live or force
            )
        return self._memo[adapter.name]

    def fetch_all(self, force: bool = False) -> dict[str, Any]:
        comtrade = self._cached(self.comtrade, force)
        wits = self._cached(self.wits, force)
        wb = self._cached(self.worldbank, force)
        trends = self._cached(self.trends, force)
        return {
            "generated_at": _now_iso(),
            "summary": {
                "live_sources": sum(
                    1 for d in (comtrade, wits, wb, trends) if d.get("status") in ("live", "cached")
                ),
                "total_sources": 4,
                "statuses": {
                    "comtrade": comtrade.get("status"),
                    "wits": wits.get("status"),
                    "worldbank": wb.get("status"),
                    "trends": trends.get("status"),
                },
            },
            "comtrade": comtrade,
            "wits": wits,
            "worldbank": wb,
            "trends": trends,
        }

    # ── 供选品引擎调用 ─────────────────────────────
    def market_size_usd_billion(self) -> float:
        return self._cached(self.comtrade)["metrics"]["global_import_usd_billion"]

    def tariff_map(self) -> dict[str, float]:
        rows = self._cached(self.wits)["metrics"]["tariff_overview"]
        return {r["country"]: r.get("avg_mfn_tariff_pct") for r in rows if r.get("avg_mfn_tariff_pct")}

    def momentum_map(self) -> dict[str, float]:
        rows = self._cached(self.worldbank)["metrics"]["macro_by_market"]
        return {r["country"]: r.get("construction_momentum_index") or 0 for r in rows}

    def score_one_sku(self, sku: dict) -> dict[str, Any]:
        """把 SKU 映射到最贴近的 Trends 关键词，返回增速维度输入。"""
        trends = self._cached(self.trends)["metrics"]["keyword_interest_2024"]
        comtrade = self._cached(self.comtrade)["metrics"]

        name = (sku.get("name_en") or "").lower()
        scen = " ".join(sku.get("scenarios", []))
        rules = [
            (("marine", "anti-corrosion", "海工"), "marine fiberglass mesh"),
            (("solar", "pv", "光伏"), "solar PV reinforcement mesh"),
            (("grc",), "GRC reinforcement mesh"),
            (("joint tape", "drywall", "石膏板", "接缝"), "drywall joint tape"),
            (("waterproof", "roof", "防水"), "waterproofing mesh"),
            (("eifs", "decorative", "抹面"), "EIFS mesh"),
            (("alkali", "抗碱"), "alkali resistant mesh"),
        ]
        hit_kw = "fiberglass mesh"
        matched = False
        haystack = f"{name} {scen}".lower()
        for needles, kw in rules:
            if any(n in haystack for n in needles):
                hit_kw = kw
                matched = True
                break

        t = trends.get(hit_kw) or trends["fiberglass mesh"]
        comtrade_yoy = comtrade["yoy_growth_pct"]

        # 该关键词的相对需求强度（在 8 个词里的分位），用于给增速做小幅微调。
        # 绝对同比不可信，但「哪个品类被搜得更多」这个相对排序是可用的。
        # 没命中任何规则的 SKU 会落到默认锚点词（搜索量最高），不能让它因此
        # 白拿满分位，一律按中位处理。
        if matched:
            all_scores = sorted(v.get("score", 0) for v in trends.values())
            my_score = t.get("score", 0)
            below = sum(1 for s in all_scores if s < my_score)
            percentile = below / max(1, len(all_scores) - 1)
        else:
            percentile = 0.5

        # Trends 同比可信就用它，否则退回 Comtrade 的真实进口增速
        trend_yoy = t.get("yoy_change_pct")
        if trend_yoy is None:
            growth_yoy = comtrade_yoy
            growth_basis = "comtrade_import_yoy"
        else:
            growth_yoy = trend_yoy
            growth_basis = f"google_trends[{t.get('confidence', 'n/a')}]"

        return {
            "matched_keyword": hit_kw,
            "trend_score": min(10.0, t["score"] / 10.0),
            "trend_confidence": t.get("confidence", "n/a"),
            "demand_percentile": round(percentile, 2),
            "yoy_change_pct": growth_yoy,
            "growth_basis": growth_basis,
            "global_import_usd_billion": comtrade["global_import_usd_billion"],
            "yoy_growth_pct": comtrade_yoy,
        }


def refresh_all(force: bool = True) -> dict[str, Any]:
    """给定时任务/后台线程用：强制刷新全部数据源（会走真实网络，耗时数分钟）。"""
    res = DataAggregator(allow_live=True).fetch_all(force=force)
    return res["summary"]


def warm_up() -> dict[str, Any]:
    """只补齐缓存缺失或已过期的数据源，已新鲜的跳过。"""
    agg = DataAggregator(allow_live=True)
    filled = {}
    for ad in (agg.comtrade, agg.wits, agg.worldbank, agg.trends):
        if cache_get(ad.name, ad.ttl):
            filled[ad.name] = "fresh"
            continue
        filled[ad.name] = ad.fetch(force=True).get("status")
    return filled


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    force = "--force" in sys.argv
    if "--warm-up" in sys.argv:
        print(json.dumps(warm_up(), ensure_ascii=False, indent=2))
        sys.exit(0)
    agg = DataAggregator(allow_live=True)
    t0 = time.time()
    res = agg.fetch_all(force=force)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    print(f"\n耗时 {time.time() - t0:.1f}s   状态 {res['summary']['statuses']}")
