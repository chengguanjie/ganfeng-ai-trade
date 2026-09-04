"""
赣丰玻纤 · 免费数据源接入层
========================

支持的免费/低成本数据源：
1. UN Comtrade (联合国海关数据)
2. Google Trends (搜索热度)
3. World Bank WITS (关税/贸易流量)
4. EU Eurostat / US ITC DataWeb 等各国海关
5. Google Search (关键词搜索)
6. 阿里国际站 / 中国制造网 (B2B 平台)

每个数据源都是一个适配器，统一返回结构：
{
    "source": 数据源名称,
    "sku_keywords": [...],
    "metrics": {
        "market_size_usd": 市场规模（USD）,
        "growth_pct_cagr": 年复合增长率（%),
        "demand_index": 需求指数 0-100,
        "trend_score": 趋势分 0-100,
        "top_buying_countries": 进口大国列表,
    },
    "fetched_at": ISO 时间戳
}

真实生产环境中，把各适配器内部的 demo 数据替换为真实 API 调用即可。
"""
from __future__ import annotations
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
SKU_FILE = os.path.join(DATA_DIR, "sku.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_sku_keywords() -> list[str]:
    with open(SKU_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    keywords = set()
    for p in data["products"]:
        name_en = p.get("name_en", "").lower()
        for token in name_en.replace(",", " ").replace("(", " ").replace(")", " ").split():
            if len(token) > 3 and token not in {"for", "with", "the", "and"}:
                keywords.add(token)
    return sorted(keywords)[:15]


# ============================================================
# 1. UN Comtrade (联合国海关数据) - 免费开放接口
# ============================================================
class ComtradeAdapter:
    """UN Comtrade 真实 API:
       https://comtradeapi.un.org/data/v1/get/C/A/HS?reporter=ALL&period=2024&cmdCode=7019&flow=imp
    """
    BASE = "https://comtradeapi.un.org/data/v1/get"

    # HS code 7019 = Glass fibres, glass wool etc. + woven fabrics
    # HS code 701940 = Glass fibre woven fabrics (最贴近玻璃纤维网格布)
    HS_CODES = ["701940", "701951", "701952", "701959"]

    def fetch(self) -> dict[str, Any]:
        # 真实接入示例（如可联网且有授权):
        # import urllib.request, urllib.parse
        # params = urllib.parse.urlencode({
        #     "reporterCode": "0", "period": "2024",
        #     "cmdCode": self.HS_CODES[0], "flowCode": "M",  # Imports
        #     "partnerCode": "all", "subscription-key": os.getenv("COMTRADE_KEY","")
        # })
        # url = f"{self.BASE}/C/A/HS?{params}"
        # with urllib.request.urlopen(url, timeout=20) as r:
        #     return json.loads(r.read().decode("utf-8"))
        # 这里以离线模式返回带物理意义的示意数据。
        return {
            "source": "UN Comtrade",
            "status": "demo-mode (real api ready, requires subscription-key)",
            "metrics": {
                "global_import_usd_billion": 3.2,
                "yoy_growth_pct": 4.2,
                "top_importers_2024": [
                    {"country": "USA", "import_usd_million": 612},
                    {"country": "Germany", "import_usd_million": 487},
                    {"country": "France", "import_usd_million": 312},
                    {"country": "Saudi Arabia", "import_usd_million": 268},
                    {"country": "UAE", "import_usd_million": 192},
                    {"country": "Vietnam", "import_usd_million": 178},
                    {"country": "India", "import_usd_million": 165},
                    {"country": "Brazil", "import_usd_million": 142},
                ],
                "demand_index_2024_vs_2020": 1.27,
            },
            "fetched_at": _now_iso(),
        }


# ============================================================
# 2. Google Trends (搜索热度)
# ============================================================
class GoogleTrendsAdapter:
    """使用 pytrends 或直接 HTTP 调用.
       pip install pytrends  ;  Or use agent-browser when needed.
    """
    KEYWORDS = ["fiberglass mesh", "alkali resistant mesh", "EIFS mesh", "drywall joint tape", "waterproofing mesh"]

    def fetch(self) -> dict[str, Any]:
        # from pytrends.request import TrendReq
        # pytrends = TrendReq(hl='en-US', tz=0)
        # pytrends.build_payload(self.KEYWORDS, timeframe='today 12-m', geo='')
        # df = pytrends.interest_over_time()
        # return df.mean().to_dict()
        # 这里给示意数据（不同关键词近 12 月 vs 上 12 月变化）:
        return {
            "source": "Google Trends",
            "status": "demo-mode (real api requires pytrends / rate-limit)",
            "metrics": {
                "keyword_interest_2024": {
                    "fiberglass mesh": {"score": 72, "yoy_change_pct": +6.5},
                    "alkali resistant mesh": {"score": 58, "yoy_change_pct": +11.2},
                    "EIFS mesh": {"score": 49, "yoy_change_pct": +3.0},
                    "drywall joint tape": {"score": 86, "yoy_change_pct": +1.8},
                    "waterproofing mesh": {"score": 65, "yoy_change_pct": +8.7},
                    "solar PV reinforcement mesh": {"score": 34, "yoy_change_pct": +18.4},
                    "marine fiberglass mesh": {"score": 28, "yoy_change_pct": +14.0},
                    "GRC reinforcement mesh": {"score": 41, "yoy_change_pct": +5.5},
                },
                "top_growing_query": "solar PV reinforcement mesh",
            },
            "fetched_at": _now_iso(),
        }


# ============================================================
# 3. World Bank WITS (关税/贸易壁垒)
# ============================================================
class WITSAdapter:
    """World Bank WITS - 全球贸易数据 + 关税
       https://wits.worldbank.org/API/SDMX/V21/datasource/tradestats-trade/data
    """
    def fetch(self) -> dict[str, Any]:
        return {
            "source": "World Bank WITS",
            "status": "demo-mode (real api needs WITS_URL=http://wits.worldbank.org/API/V1/SDMX/V21)",
            "metrics": {
                "tariff_overview": [
                    {"country": "USA", "avg_mfn_tariff_pct": 5.8, "tariff_code": "7019.40"},
                    {"country": "EU", "avg_mfn_tariff_pct": 4.5, "tariff_code": "7019.40"},
                    {"country": "Saudi Arabia", "avg_mfn_tariff_pct": 5.0, "tariff_code": "7019.40"},
                    {"country": "UAE", "avg_mfn_tariff_pct": 5.0, "tariff_code": "7019.40"},
                    {"country": "Vietnam", "avg_mfn_tariff_pct": 8.0, "tariff_code": "7019.40"},
                    {"country": "India", "avg_mfn_tariff_pct": 10.0, "tariff_code": "7019.40"},
                    {"country": "Brazil", "avg_mfn_tariff_pct": 12.0, "tariff_code": "7019.40"},
                    {"country": "Turkey", "avg_mfn_tariff_pct": 6.5, "tariff_code": "7019.40"},
                    {"country": "Iraq", "avg_mfn_tariff_pct": 5.0, "tariff_code": "7019.40"},
                    {"country": "Mexico", "avg_mfn_tariff_pct": 7.5, "tariff_code": "7019.40"},
                ],
                "nontariff_barriers_index": {
                    "USA": "low", "EU": "medium-CE-marking", "Saudi Arabia": "low-SASO",
                    "Vietnam": "low", "India": "medium-BIS", "Brazil": "medium-INMETRO",
                    "Turkey": "medium-CE", "Iraq": "high", "Mexico": "medium-NOM",
                },
            },
            "fetched_at": _now_iso(),
        }


# ============================================================
# 4. Google Search 关键词热度 (模拟)
# ============================================================
class GoogleSearchAdapter:
    """使用 agent-browser 或 scrapling 获取 SERP 数据。"""
    def fetch(self) -> dict[str, Any]:
        return {
            "source": "Google Search SERPs",
            "status": "demo-mode (real api via scrapling or google-custom-search)",
            "metrics": {
                "competitor_count_for_keyword": {
                    "fiberglass mesh": "12.4M results",
                    "alkali resistant mesh": "1.8M results",
                    "EIFS mesh": "0.42M results",
                    "waterproofing mesh": "3.1M results",
                    "drywall joint tape": "8.7M results",
                },
                "auction_ad_density": {
                    "fiberglass mesh": "high (4-7 ads)",
                    "alkali resistant mesh": "low (0-2 ads)",
                    "EIFS mesh": "low (0-1 ads)",
                    "waterproofing mesh": "medium (2-4 ads)",
                },
            },
            "fetched_at": _now_iso(),
        }


# ============================================================
# 5. 阿里国际站 (店铺内免费数据) - 仅示意
# ============================================================
class AlibabaAdapter:
    """阿里国际站数据管家 - 仅注册店铺才能获取，本类示意。
       真实接入请用 lark-im / browser-automation-toolbox 爬取后台。"""
    def fetch(self) -> dict[str, Any]:
        return {
            "source": "Alibaba Data Bank (店铺内免费)",
            "status": "demo-mode (requires store login)",
            "metrics": {
                "category_top_keywords": [
                    {"keyword": "fiberglass mesh", "index": 9421, "change_pct": +12},
                    {"keyword": "alkali resistant fiberglass mesh", "index": 7320, "change_pct": +18},
                    {"keyword": "self adhesive fiberglass mesh tape", "index": 5102, "change_pct": +9},
                    {"keyword": "drywall joint tape", "index": 4960, "change_pct": +4},
                    {"keyword": "waterproofing mesh", "index": 4801, "change_pct": +13},
                ],
                "buyer_distribution_top": [
                    {"country": "USA", "share_pct": 14.2},
                    {"country": "Saudi Arabia", "share_pct": 9.8},
                    {"country": "UAE", "share_pct": 8.7},
                    {"country": "India", "share_pct": 7.3},
                    {"country": "Vietnam", "share_pct": 6.1},
                ],
                "rfq_growth_yoy": "+24.6%",
            },
            "fetched_at": _now_iso(),
        }


# ============================================================
# 顶层：根据关键词聚合所有数据源 → 标准化输出
# ============================================================
class DataAggregator:
    def __init__(self) -> None:
        self.comtrade = ComtradeAdapter()
        self.trends = GoogleTrendsAdapter()
        self.wits = WITSAdapter()
        self.search = GoogleSearchAdapter()
        self.alibaba = AlibabaAdapter()

    def fetch_all(self) -> dict[str, Any]:
        return {
            "comtrade": self.comtrade.fetch(),
            "trends": self.trends.fetch(),
            "wits": self.wits.fetch(),
            "search": self.search.fetch(),
            "alibaba": self.alibaba.fetch(),
        }

    # 对单个 SKU 关键词，提取相应评分维度
    def score_one_sku(self, sku: dict) -> dict[str, Any]:
        name = sku.get("name_en", "")
        kw = name.lower()
        trends = self.trends.fetch()["metrics"]["keyword_interest_2024"]
        keywords_map = {
            "alkali-resistant fiberglass mesh": trends["alkali resistant mesh"],
            "waterproof reinforcement fiberglass mesh": trends["waterproofing mesh"],
            "self-adhesive fiberglass joint tape": trends["drywall joint tape"],
            "marine engineering anti-corrosion mesh": trends["marine fiberglass mesh"],
            "solar pv reinforcement fiberglass mesh": trends["solar PV reinforcement mesh"],
            "grc permanent reinforcement mesh": trends["GRC reinforcement mesh"],
            "fire-resistant high-temp coated fiberglass mesh": trends["fiberglass mesh"],
            "interior drywall joint tape": trends["drywall joint tape"],
            "eifs decorative panel reinforcement mesh": trends["EIFS mesh"],
            "mosaic backing fiberglass mesh": trends["fiberglass mesh"],
            "roof waterproofing reinforcement mesh": trends["waterproofing mesh"],
            "custom fiberglass mesh": trends["fiberglass mesh"],
        }
        trend_hit = None
        for k, v in keywords_map.items():
            if all(word in k for word in kw.split()[:3] if len(word) > 4):
                trend_hit = v
                break
        if not trend_hit:
            trend_hit = trends["fiberglass mesh"]

        # 简单确定性打分（归一到 0-10）
        return {
            "trend_score": min(10.0, trend_hit["score"] / 10.0),
            "yoy_change_pct": trend_hit["yoy_change_pct"],
            "global_import_usd_billion": self.comtrade.fetch()["metrics"]["global_import_usd_billion"],
            "yoy_growth_pct": self.comtrade.fetch()["metrics"]["yoy_growth_pct"],
        }


if __name__ == "__main__":
    agg = DataAggregator()
    res = agg.fetch_all()
    print(json.dumps(res, indent=2, ensure_ascii=False))
