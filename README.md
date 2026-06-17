# StockTwits Sentiment API

实时抓取 StockTwits 散户帖子，提供半导体 / AI 板块情绪信号，供量化策略和研究系统接入。

## 目录

- [项目简介](#项目简介)
- [快速开始](#快速开始)
- [环境变量](#环境变量)
- [部署说明](#部署说明)
- [数据库结构](#数据库结构)
- [技术栈](#技术栈)

---

## 项目简介

通过 Playwright 实时抓取 StockTwits 帖子，存入 PostgreSQL，对外提供 REST API：

- **情绪信号**：每只 ticker 的 Bullish/Bearish 比例和情绪分
- **热度异动**：提及量相对 7 日基线的倍数（spike_ratio）
- **实时预警**：情绪突变或热度爆发事件
- **板块聚合**：半导体、AI 等板块整体情绪

**覆盖 ticker**：NVDA、AMD、TSM、INTC、AVGO、AMAT、LRCX、MU、ASML、QCOM 等 30+ 个半导体 / AI 标的

---

## 快速开始

### 环境要求

- Python 3.11+
- PostgreSQL（本地或 Railway）
- Playwright（仅爬虫需要）

### 安装

```bash
git clone https://github.com/Sword4177/stocktwits-crawler.git
cd stocktwits-crawler

pip install -r requirements.txt
pip install -r requirements-crawler.txt  # 爬虫依赖
playwright install chromium
```

### 配置环境变量

复制并填写 `.env`：

```bash
cp .env.example .env
```

### 启动 API

```bash
uvicorn api:app --reload --port 8001
```

访问 `http://localhost:8001/docs` 查看 Swagger UI。

### 启动爬虫

```bash
python main.py
```

### 回溯历史数据

```bash
python backfill.py --symbol NVDA --days 30
```

---

## 环境变量

| 变量名 | 必填 | 说明 |
|--------|------|------|
| `DATABASE_URL` | 是 | PostgreSQL 连接字符串，如 `postgresql://user:pass@host:5432/dbname` |
| `API_KEY` | 否 | API 认证密钥，不填则接口开放无需认证 |

---

## 部署说明

### Railway 部署步骤

1. 在 [Railway](https://railway.app) 创建新项目
2. 添加 PostgreSQL 服务
3. 连接 GitHub 仓库 `Sword4177/stocktwits-crawler`
4. 在 stocktwits-crawler 服务的 Variables 里添加：
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`（或直接填写 PostgreSQL 公网地址）
   - `API_KEY` = 你的密钥
   - `PORT` = `8001`
5. 在 Settings → Public Networking → Generate Domain，端口填 `8001`
6. 点击 Deploy

Railway 会自动读取 `Procfile` 启动：

```
web: uvicorn api:app --host 0.0.0.0 --port $PORT
```

---

## 数据库结构

### posts（帖子主表）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | StockTwits 帖子 ID |
| `symbol` | TEXT | 股票代码，如 `NVDA` |
| `source` | TEXT | 来源：`symbol` 或 `trending` |
| `body` | TEXT | 帖子正文 |
| `sentiment` | TEXT | 情绪标注：`Bullish` / `Bearish` / 空 |
| `likes` | INT | 点赞数 |
| `username` | TEXT | 发帖用户名 |
| `published_at` | TIMESTAMPTZ | 发帖时间（UTC） |
| `collected_at` | TIMESTAMPTZ | 采集时间（UTC） |

### symbols（股票元数据）

| 字段 | 类型 | 说明 |
|------|------|------|
| `symbol` | TEXT PK | 股票代码 |
| `sector` | TEXT | 板块（中文，见下方列表） |
| `industry` | TEXT | 细分行业 |
| `updated_at` | TIMESTAMPTZ | 最后更新时间 |

**板块可用值**：`半导体` / `科技` / `消费` / `金融` / `能源` / `通信` / `医疗` / `加密货币`

### ticker_signals（信号快照，每 5 分钟）

| 字段 | 类型 | 说明 |
|------|------|------|
| `symbol` | TEXT | 股票代码 |
| `ts` | TIMESTAMPTZ | 快照时间 |
| `time_window` | TEXT | 窗口：`1h` / `4h` / `24h` |
| `mentions` | INT | 窗口内提及量 |
| `bullish_count` | INT | Bullish 数量 |
| `bearish_count` | INT | Bearish 数量 |
| `sentiment_score` | REAL | 情绪分 |
| `buzz_ratio` | REAL | 热度倍数 |

### signal_alerts（预警事件）

| 字段 | 类型 | 说明 |
|------|------|------|
| `symbol` | TEXT | 触发预警的股票代码 |
| `alert_type` | TEXT | `buzz_spike` 或 `sentiment_shift` |
| `triggered_at` | TIMESTAMPTZ | 触发时间 |
| `detail` | JSONB | 详细数据 |

---

## 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.11 |
| API 框架 | FastAPI + uvicorn |
| 数据库 | PostgreSQL（生产）/ SQLite（本地开发） |
| 爬虫 | Playwright（无头浏览器） |
| 部署 | Railway |
| 文档 | Swagger UI（自动生成） |
