"""
赣丰玻纤 · 智能客服引擎（基于 RAG 的轻量版）
==============================================

输入：客户消息
输出：意图 + 命中 FAQ + 推荐产品 + 自然语言回复（无 LLM 依赖，使用规则 + 模板）

设计原则：
- 完全离线运行（演示用）
- LLM 接口预留（OPENAI_API_KEY 或 WorkBuddy 调用点）
- 多语言：中英混合识别 + 自动切换回复
"""
from __future__ import annotations
import json
import os
import re
import random
from typing import Any

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
FAQ_FILE = os.path.join(ROOT_DIR, "data", "faqs.json")


def _load_faqs() -> list[dict[str, Any]]:
    with open(FAQ_FILE, "r", encoding="utf-8") as f:
        return json.load(f)["faqs"]


# 意图关键词映射（多语种 + 容错）
INTENT_PATTERNS: dict[str, list[str]] = {
    "moq_quote": ["MOQ", "最小起订", "起订量", "起订", "trial", "trial order", "试单", "起订多少", "small order", "small quantity"],
    "sample": ["sample", "样品", "samples", "免费样品", "free sample", "get sample"],
    "logistics": ["FOB", "CIF", "incoterms", "Incoterms", "物流", "运费", "shipping", "seafreight", "loading", "20GP", "40HQ", "transit", "海运"],
    "payment": ["T/T", "30/70", "L/C", "信用证", "付款", "payment", "付款方式", "OA"],
    "cert": ["证书", "认证", "ISO", "CE", "RoHS", "certification", "certifications"],
    "spec_consult": ["克重", "gram", "spec", "规格", "参数", "抗拉", "tensile", "抗碱", "alkali", "spec", "specifications", "网孔"],
    "recommend": ["推荐", "recommend", "建议", "which mesh", "suitable", "what mesh", "推荐哪款", "推荐哪一款"],
    "oem": ["OEM", "定制", "private label", "custom", "贴牌", "白牌", "专有包装", "LOGO"],
    "supply": ["产能", "lead time", "交期", "capacity", "production", "年产能", "交期多久"],
    "aftersale": ["售后", "return", "退货", "warranty", "质保", "质量申诉", "售后保障"],
    "company": ["factory", "工厂", "history", "成立", "founded", "about", "audit", "验厂"],
    "product_intro": ["what is", "什么是", "tell me about", "fiberglass mesh"],
    "channel": ["agent", "经销商", "独家", "regional", "market", "开发市场", "代理"],
}


def _detect_lang(text: str) -> str:
    """简单判定文本语言（中文/英文）"""
    cn_chars = sum(1 for c in text if "一" <= c <= "鿿")
    return "zh" if cn_chars > len(text) * 0.3 else "en"


def _detect_intent(text: str) -> tuple[str, float]:
    text_lc = text.lower()
    scores: dict[str, float] = {}
    for intent, keywords in INTENT_PATTERNS.items():
        for kw in keywords:
            if kw.lower() in text_lc:
                scores[intent] = scores.get(intent, 0) + 1
    if not scores:
        return "general", 0.0
    best = max(scores.items(), key=lambda x: x[1])
    return best[0], best[1] / 5.0


def _find_best_faq(text: str, faqs: list[dict], top_n: int = 3) -> list[dict]:
    """向量式检索的轻量替代：词袋打分 + 长度过滤"""
    text_lc = text.lower()
    tokens = re.findall(r"\w+", text_lc)
    tokens = [t for t in tokens if len(t) >= 3]
    scored = []
    for faq in faqs:
        all_text = (faq.get("q_zh", "") + " " + faq.get("q_en", "") + " " + faq.get("a_zh", "")).lower()
        score = sum(1 for t in tokens if t in all_text)
        # intent tag 命中也加分
        for tag in faq.get("tags", []):
            if tag in text_lc:
                score += 0.5
        scored.append((score, faq))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [f for s, f in scored[:top_n] if s > 0]


# 各意图对应的答复模板（合并 FAQ 知识）
TEMPLATES = {
    "moq_quote": {
        "zh": "常规规格 MOQ 200 卷（≈1 个 20GP 集装箱），自粘带与定制产品 MOQ 500-1000 卷。\n\n😊 **新客户首单可享 100 卷试单 + 5 卷免费样品（DHL 运费由您承担）。**\n\n想直接进入询盘流程吗？",
        "en": "Standard SKU MOQ is 200 rolls (~one 20GP). Self-adhesive tape and custom products MOQ is 500-1000 rolls.\n\n😊 **New customers get a 100-roll trial + 5 free sample rolls (DHL paid by you).**\n\nWould you like to start a formal inquiry?",
    },
    "sample": {
        "zh": "样品政策：每个 SKU 可免费提供 5 卷样品（DHL/顺丰运费到付），3-5 天送达。\n\n需要我现在帮您安排出货吗？",
        "en": "Sample policy: 5 free rolls per SKU (DHL/SF Express freight collect), arrives in 3-5 days.\n\nShall I arrange shipment for you?",
    },
    "logistics": {
        "zh": "我们支持 FOB/CIF/CFR/EXW/DDP，最常用 FOB 宁波/上海。\n\n📦 **20GP 装载：** 145g / 160g 约 140-160 卷，40HQ 为其 2 倍。\n\n🕐 **海运时效：** 中东 18-22 天 / 欧洲 28-35 天 / 东南亚 5-10 天 / 拉美 35-45 天。\n\n需要我帮您选定最合适的贸易条款吗？",
        "en": "Incoterms: FOB/CIF/CFR/EXW/DDP, mostly FOB Ningbo/Shanghai.\n\n📦 **20GP load:** 145g/160g ≈ 140-160 rolls, 40HQ double.\n\n🕐 **Sea transit:** Middle East 18-22 days / Europe 28-35 days / SEA 5-10 days / Latam 35-45 days.\n\nShall I help with your optimal trade term?",
    },
    "payment": {
        "zh": "💳 **付款方式：**\n\n• 新客户：30% T/T 预付 + 70% 见提单\n• 老客户：可申请 30/70、40/60 或 O/A 60 天\n• L/C at sight：可接受（建议金额 ≥ USD 30,000）\n\n请问您方便哪种付款方式？",
        "en": "💳 **Payment terms:**\n\n• New customers: 30% T/T deposit + 70% against B/L copy\n• Returning: 30/70, 40/60 or O/A 60 days\n• L/C at sight: accepted (suggested ≥ USD 30,000)\n\nWhich payment term works for you?",
    },
    "cert": {
        "zh": "我们已通过：**ISO 9001:2015 + ISO 14001:2015 + CE + RoHS**。可提供第三方 SGS / BV 测试报告。\n\n需要我发您 CE 证书或 ISO 副本吗？",
        "en": "Certifications: **ISO 9001:2015 + ISO 14001:2015 + CE + RoHS**. SGS/BV test reports available on request.\n\nWant me to send you the CE or ISO copy?",
    },
    "supply": {
        "zh": "🏭 **工厂规模：** 12 条织造线 + 5 条涂层线，年产能 8000 吨（约 800 万平米）\n\n🕐 **交期：** 常规 15-25 天，加急 10 天可发（+10% 加急费）\n\n🔧 **OEM 支持：** 可定制 LOGO、品牌名、包装\n\n需要我现在报一个具体交期吗？",
        "en": "🏭 **Capacity:** 12 weaving lines + 5 coating lines, 8000 tons/year (~8 million sqm)\n\n🕐 **Lead time:** 15-25 days standard, 10 days expedited (+10%)\n\n🔧 **OEM:** Custom logo, brand name, packaging\n\nWant a specific lead time quote?",
    },
    "oem": {
        "zh": "✅ **OEM 服务：** 支持 LOGO 定制、品牌专有包装、专属标签。起订量 1000 卷起。\n\n📋 **流程：** 寄样确认 → 设计稿确认 → 合同签订 → 投产\n\n请问您需要哪种 OEM 合作模式？",
        "en": "✅ **OEM services:** Custom LOGO, brand packaging, exclusive labels. MOQ 1000 rolls.\n\n📋 **Process:** sample confirm → design confirm → contract → production\n\nWhich OEM collaboration model do you need?",
    },
    "aftersale": {
        "zh": "🛡️ **售后保障：**\n\n• 30 天内非人为质量问题 100% 包退换\n• 常规订单 2 年质量保证\n• 海外退货运费由责任方承担\n\n请问您遇到什么问题？我可以帮您立即协调处理。",
        "en": "🛡️ **After-sales:**\n\n• 30-day 100% free replacement for non-human quality issues\n• 2-year warranty on standard orders\n• Return freight by responsible party\n\nWhat issue can I help coordinate?",
    },
    "company": {
        "zh": "🏭 **赣丰玻纤**：成立于 2008 年，深耕玻纤网格布 18 年\n\n📍 **工厂：** 江西赣州（距离宁波港 600 km / 深圳港 500 km）\n\n🌍 **主要市场：** 沙特、阿联酋、越南、印度、巴西、土耳其、德国、英国（已服务 50+ 国家、300+ 海外客户）\n\n📞 **验厂：** 支持 WhatsApp/WeChat 视频验厂，可安排第三方 SGS/BV\n\n需要更多详细信息吗？",
        "en": "🏭 **Ganfeng Fiberglass:** Founded 2008, 18 years focused on fiberglass mesh\n\n📍 **Factory:** Ganzhou, Jiangxi (600 km from Ningbo port, 500 km from Shenzhen port)\n\n🌍 **Markets:** Saudi, UAE, Vietnam, India, Brazil, Turkey, Germany, UK (300+ customers in 50+ countries)\n\n📞 **Audit:** WhatsApp/WeChat video tour, or third-party SGS/BV\n\nNeed more info?",
    },
    "channel": {
        "zh": "🤝 **经销商合作：** 新区域独家代理提供\n\n• 💰 样品支持\n• 📚 技术培训\n• 🎪 展会共同参展\n• 🛡️ 国别独家市场保护\n\n欢迎预约一次线上合作沟通，请告知您专注的国家与产品方向？",
        "en": "🤝 **Distributor program:**\n\n• 💰 Sample support\n• 📚 Technical training\n• 🎪 Co-exhibition at trade shows\n• 🛡️ Country-exclusive protection\n\nLet's schedule a call. Which country and product focus?",
    },
}


class ChatbotEngine:
    def __init__(self) -> None:
        self.faqs = _load_faqs()

    def reply(self, user_msg: str, session_id: str | None = None) -> dict[str, Any]:
        lang = _detect_lang(user_msg)
        intent, conf = _detect_intent(user_msg)

        # 优先用模板回答（更可控）
        if intent in TEMPLATES:
            text = TEMPLATES[intent][lang]
        else:
            # 否则从 FAQ 命中
            hits = _find_best_faq(user_msg, self.faqs)
            if hits:
                best = hits[0]
                text = best["a_zh"] if lang == "zh" else best.get("a_zh", "")
                # 英文版没有的话给中文
            else:
                text = (
                    "您好，我已记录您的问题，会转给外贸专员 24h 内回复。\n\n请问方便留下您的邮箱或 WhatsApp 吗？"
                    if lang == "zh" else
                    "Got it. I'll pass your question to our export specialist, reply within 24h.\n\nCould you share your email or WhatsApp?"
                )

        # 兜底引导
        if intent == "general" or conf < 0.2:
            cta = (
                "\n\n💡 **您可能想了解：** [产品介绍] [报价] [样品] [交期] [认证]\n\n可直接回复关键词，或点击右下角『询盘表单』留下您的需求。"
                if lang == "zh" else
                "\n\n💡 **You may want to know:** [Products] [Quote] [Sample] [Lead time] [Certs]\n\nReply with a keyword, or click the inquiry form to share your needs."
            )
            text += cta

        # 询盘 CTA：所有回复尾部都附
        cta2 = (
            "\n\n---\n\n📋 **要即时询盘？** 请点击页面右侧『Quote Now』按钮，1 分钟内提交。\n\n📞 **直接呼客服：** WhatsApp +86-1380-xxxx-xxx"
            if lang == "zh" else
            "\n\n---\n\n📋 **To RFQ now:** Click 『Quote Now』 button, 1 min to submit.\n\n📞 **WhatsApp:** +86-1380-xxx-xxx"
        )
        text += cta2

        return {
            "intent": intent,
            "confidence": round(conf, 2),
            "language": lang,
            "matched_faq": [f.get("q_zh", "") for f in _find_best_faq(user_msg, self.faqs, 2)],
            "text": text,
        }


if __name__ == "__main__":
    eng = ChatbotEngine()
    test_msgs = [
        "你好，145g 的网格布 MOQ 是多少？",
        "What's your MOQ for 145g mesh?",
        "Can I get free samples?",
        "你们工厂通过 ISO 认证了吗？",
        "delivery time to Saudi?",
        "hello",
    ]
    for m in test_msgs:
        print(f"\nUSER: {m}")
        out = eng.reply(m)
        print(f"BOT : {out['intent']} ({out['language']})")
        print(f"     {out['text'][:120]}...")
