# 🏭 赣丰玻纤 · 数据飞轮系统（Ganfeng Trade System V5）

> 基于 V5 实施路线图的全栈外贸 AI 系统：独立站 + 智能客服 + 选品评分 + 飞书同步 — 一套代码跑通数据飞轮闭环。

---

## 🎯 系统组成

| 模块 | 技术栈 | 路径 | 状态 |
|---|---|---|---|
| 🌐 独立站 | Flask + HTML/CSS/JS | `/` | ✅ |
| 💬 智能客服 | RAG + 意图识别 | `scripts/chatbot_engine.py` | ✅ |
| 🤖 选品引擎 | 6 维评分模型 | `scripts/sourcing_engine.py` | ✅ |
| 📊 选品看板 | Chart.js / 表格 | `/admin` | ✅ |
| 🪶 飞书同步 | lark-base 适配层 | `scripts/feishu_sync.py` | ✅（dry-run 默认） |
| 📦 免费数据源 | 6 适配器 | `scripts/free_data_sources.py` | ✅ |

---

## 🚀 快速启动

```bash
cd ganfeng-ai-trade-system

# 安装依赖（首次运行）
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 启动
./start.sh
```

启动后访问：
- 🌐 **独立站**：http://127.0.0.1:5000/
- 📊 **管理后台**：http://127.0.0.1:5000/admin

---

## 📡 API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/products?lang=zh\|en` | 12 SKU 主数据 |
| `POST` | `/api/inquiry` | 询盘表单提交 |
| `POST` | `/api/chat` | 智能客服对话 |
| `GET` | `/api/sourcing` | 12 SKU 6 维评分 |
| `GET` | `/api/data-sources` | 免费数据源聚合 |
| `GET` | `/api/dashboard` | 管理后台统计 |

### 示例：提交询盘

```bash
curl -X POST http://127.0.0.1:5000/api/inquiry \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Ali Mahmoud",
    "company": "Gulf Construction LLC",
    "country": "Saudi Arabia",
    "email": "ali@gulfco.sa",
    "sku": "GF-AR-145-44",
    "quantity_rolls": 800,
    "message": "FOB Ningbo, need CI sample"
  }'
```

### 示例：调用 AI 客服

```bash
curl -X POST http://127.0.0.1:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{ "message": "145g mesh MOQ?" }'
```

---

## 📂 目录结构

```
ganfeng-ai-trade-system/
├── app.py                    # Flask 主入口（含全部 API）
├── start.sh                  # 一键启动脚本
├── Procfile                  # 部署用
├── requirements.txt          # Python 依赖
├── README.md                 # 本文件
│
├── data/
│   ├── sku.json              # 12 SKU 主数据
│   ├── faqs.json             # 30+ FAQ 知识库
│   ├── trade.db              # SQLite 运行时生成
│   └── sourcing_cache.json   # 选品评分缓存（6h）
│
├── scripts/
│   ├── init_db.py            # 数据库 + 样本数据初始化
│   ├── sourcing_engine.py    # 6 维评分引擎 ⭐
│   ├── free_data_sources.py  # 6 个免费数据源适配器 ⭐
│   ├── chatbot_engine.py     # 智能客服 RAG ⭐
│   └── feishu_sync.py        # 飞书多维表格同步 ⭐
│
├── templates/
│   ├── index.html            # 独立站落地页
│   └── admin.html            # 管理后台
│
└── static/
    ├── css/style.css         # 全站样式
    └── js/
        ├── app.js            # 主交互
        └── chatbot.js        # 客服浮窗
```

---

## 🔄 数据流（飞轮）

```
                ┌─────────────────────────────────┐
                ↓                                  │
        🌍 免费数据源                              │
        · UN Comtrade                             │
        · Google Trends                           │
        · WITS                                    │
        · 阿里 / Google SERP                      │
        · 行业报告 PDF                            │
                │                                  │
                ↓                                  │
        🤖 选品评分引擎（6 维）                       │
                │                                  │
                ↓                                  │
        🪶 飞书多维表格（sourcing_scores）            │
                │                                  │
                ↓                                  │
        🌐 独立站（首页 Top 5 推荐）                │
                │                                  │
                ↓                                  │
        📋 询盘表单  →  💬 AI 客服                  │
                │                                  │
                ↓                                  │
        🪶 飞书多维表格（inquiries / customers）     │
                │                                  │
                ↓                                  │
        ⚡ 飞书自动化（新询盘通知 + 周报）            │
                │                                  │
                ↓                                  │
        📊 成交数据 → 回流飞书 → 优化评分模型 ←──────┘
```

---

## 🪶 飞书同步（真实模式）

默认 `LARK_DRY_RUN=true` 不发外网请求。要发往真实飞书：

```bash
export LARK_DRY_RUN=false
export LARK_BASE_TOKEN=your_base_token_here

python scripts/feishu_sync.py
```

按 V4 方案同步 5 张主表到飞书：
1. **products**（SKU 主数据，10 字段）
2. **customers**（客户主数据，10 字段）
3. **inquiries**（询盘记录，12 字段）
4. **sourcing_scores**（选品评分，11 字段）
5. **knowledge_base**（FAQ，7 字段）

---

## 🧪 本地验证步骤

```bash
# 1. 启动
./start.sh

# 2. 浏览器打开独立站：http://127.0.0.1:5000/
# 3. 浏览器打开管理后台：http://127.0.0.1:5000/admin
# 4. 测试询盘提交（独立站填写表单）
# 5. 测试 AI 客服（右下角聊天按钮）
# 6. 查看选品评分（首页 Top 5 推荐 + 管理后台完整表）

# 7. CLI 检查
curl http://127.0.0.1:5000/api/sourcing | head -30
curl http://127.0.0.1:5000/api/dashboard
```

---

## 📈 与 V1-V5 文档体系关系

本系统是 **V5《开发路线图》** 的工程实现，对应关系：

| V5 文档章节 | 本项目实现 |
|---|---|
| ① 免费数据源 | `scripts/free_data_sources.py` (6 适配器) |
| ② 三合一流架构 | Flask 后端 + 独立站 + 飞书同步层 |
| ③ 独立站设计 | `templates/index.html` |
| ④ 4 周开发路线图 | 已完成 W1-W4 MVP |
| ⑤ 飞书知识库 | `data/faqs.json`（30+ 条） |
| ⑥ 飞书自动化 | `feishu_sync.trigger_automation()` |
| ⑦ 成本预算 | 完全 0 付费数据源 + 1 名运营 |
| ⑧ 检查清单 | 见 `/admin` 数据源状态 + 自动化规则 |

---

## 📜 许可

© 2026 江西华源咨询 × 赣丰玻纤外贸部 · 仅供内部实施使用
