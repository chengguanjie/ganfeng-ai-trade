# =================================================================
# 赣丰玻纤 · 数据飞轮系统 - Zeabur 部署指南
# =================================================================

## ✅ 当前部署状态（2026-09-05 已上线）

| 项目 | 值 |
|------|------|
| **访问地址** | https://ganfeng-trade.preview.aliyun-zeabur.cn |
| **管理后台** | https://ganfeng-trade.preview.aliyun-zeabur.cn/admin |
| Zeabur 项目 | ganfeng-fiberglass-ai（阿里云中国区） |
| 服务名 | ganfeng-ai-trade |
| Git commit | bb81739 (main) |
| 状态 | RUNNING · 域名 PROVISIONED |

> 注：项目部署在 Zeabur 阿里云中国区域，生成域名后缀为 `*.preview.aliyun-zeabur.cn`（预备案域名），而非国际区的 `*.zeabur.app`。
> CLI 创建域名正确语法：`zeabur domain create --id <服务ID> --env-id <环境ID> -g --domain <前缀> -y -i=false`（`--domain` 只传前缀，不带域名后缀）。

## 📦 项目简介

基于 Flask + 飞书多维表格 + AI 的外贸部数据飞轮系统：
- **独立站** `/` - 产品展示、询盘表单、AI 客服浮窗
- **管理后台** `/admin` - 选品表、询盘列表、数据源状态、飞书 Schema
- **API** `/api/*` - products / inquiry / chat / sourcing / dashboard

---

## 🚀 Zeabur 一键部署（3 步）

### 方案 A：通过 GitHub（推荐）

#### Step 1 - 推送到 GitHub

```bash
cd ganfeng-ai-trade-system

# 初始化 git 仓库
git init
git add .
git commit -m "feat: 赣丰玻纤数据飞轮系统 V1"

# 在 GitHub 创建空仓库（如 ganfeng-ai-trade），然后：
git remote add origin git@github.com:你的用户名/ganfeng-ai-trade.git
git branch -M main
git push -u origin main
```

#### Step 2 - 在 Zeabur 创建项目

1. 登录 [zeabur.com](https://zeabur.com)
2. 点击 **"New Project"** → 选区域（推荐 Hong Kong 或 Singapore，靠近外贸客户）
3. 点 **"Deploy New Service"** → 选 **"GitHub"**
4. 授权并选择 `ganfeng-ai-trade` 仓库
5. Zeabur 自动检测 Python + Procfile，开始构建

#### Step 3 - 配置环境变量

在 Zeabur 服务详情页 → **Variables** 标签，添加：

| 变量名 | 值 | 必填 |
|--------|------|------|
| `LARK_DRY_RUN` | `false` | 否（设为 false 启用真实飞书同步） |
| `LARK_APP_ID` | `cli_aa9db51beab89bc3` | 可选 |
| `LARK_APP_SECRET` | 飞书开发者后台获取 | 可选 |
| `LARK_BASE_TOKEN` | `AdMJb19DeaielmsghpocukuqnLf` | 可选 |
| `TZ` | `Asia/Shanghai` | 推荐 |

#### Step 4 - 绑定域名（可选）

- Zeabur 默认分配 `xxx.zeabur.app` 子域名
- 绑定自有域名：在 **Settings → Networking → Custom Domain** 添加 `trade.ganfeng.com.cn` 等

---

### 方案 B：Zeabur CLI（不需 GitHub）

```bash
# 安装 Zeabur CLI
npm install -g zeabur

# 登录
zeabur auth login

# 部署
cd ganfeng-ai-trade-system
zeabur deploy
```

---

## 📂 关键部署文件说明

| 文件 | 作用 |
|------|------|
| `Procfile` | Zeabur 用它启动 web 进程（gunicorn） |
| `zbpack.json` | 自定义构建命令和启动命令 |
| `runtime.txt` | 锁定 Python 3.11 |
| `requirements.txt` | Python 依赖清单 |
| `app.py` | Flask 主入口，自动监听 `$PORT` |

---

## ⚠️ SQLite 数据持久化

Zeabur 免费层容器重启后 SQLite 数据会丢失。生产建议：

**方案 1（最简单）**：升级 Zeabur 付费层（$5/月起），挂载持久化卷

**方案 2（推荐）**：改用 Zeabur Postgres / MySQL：
1. Zeabur 控制台 → "Add Service" → "Postgres"
2. 修改 `scripts/init_db.py` 用 `psycopg2` 替换 `sqlite3`
3. 设置环境变量 `DATABASE_URL`

**方案 3**：继续用 SQLite，但每次启动自动从飞书 Base 拉取最新数据恢复（已有 `scripts/feishu_sync.py` 框架）

---

## 💰 Zeabur 费用

| 计划 | 价格 | 适合 |
|------|------|------|
| Free | $0 | 演示 · 5GB 流量/月 |
| Developer | $5/月 | 小团队 · 1GB RAM · 20GB 流量 |
| Team | $20/月起 | 生产环境 |

赣丰玻纤这个系统预估：
- 内存峰值 < 512MB
- 月流量 < 2GB（独立站 + 管理后台）
- **Developer 计划（$5/月 ≈ ¥36/月）就足够**

---

## ✅ 部署后验证清单

访问 `https://你的项目.zeabur.app/` 检查：

- [ ] 独立站首页正常加载（Hero + 6 SKU + 询盘表单）
- [ ] AI 客服浮窗能弹出并回复
- [ ] 询盘表单能提交，数据库写入成功
- [ ] `/admin` 管理后台能打开
- [ ] `/api/products` 返回 12 SKU JSON
- [ ] `/api/health` 返回 `{"status":"ok"}`

---

## 🛠 故障排查

**部署失败：** 看 Zeabur Logs（实时），常见原因：
- `pip install` 失败 → 检查 `requirements.txt` 版本号
- `gunicorn` 找不到 → Procfile 用 `python -m gunicorn` 替代

**SQLite 不持久：** 见上面 SQLite 数据持久化章节

**飞书同步报错：** 检查 `LARK_DRY_RUN=false` + 4 个 LARK_* 环境变量

---

_生成时间：2026-09-05_
