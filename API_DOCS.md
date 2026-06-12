# StockTwits 散户情绪 API — 接入文档

**Base URL**: `https://unlawful-cricket-willfully.ngrok-free.dev`  
**数据来源**: StockTwits 实时数据，覆盖 30+ 半导体/AI 板块 ticker  
**数据量**: 287,000+ 条帖子，持续更新  

---

## 接口列表

### 1. 健康检查
```
GET /
```
**返回示例：**
```json
{
  "status": "ok",
  "service": "SentinelFlow StockTwits API",
  "version": "1.0.0"
}
```

---

### 2. 热度异动信号 🔥
```
GET /api/signals
```
返回近 24 小时提及量 ≥ 30 日均值 1.5 倍、且股价变动 < 3% 的 ticker（潜在价格未反应的情绪信号）。

**返回示例：**
```json
{
  "total": 3,
  "description": "mentions_24h >= 1.5x 30d avg AND abs(price_change) < 3%",
  "data": [
    {
      "symbol": "NVDA",
      "mentions_24h": 520,
      "daily_avg_30d": 302.1,
      "ratio": 1.72,
      "price": 131.38,
      "pct_change": -1.2
    }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `symbol` | 股票代码 |
| `mentions_24h` | 近24小时提及次数 |
| `daily_avg_30d` | 30日日均提及次数 |
| `ratio` | 热度倍数（mentions_24h / daily_avg_30d）|
| `price` | 最新收盘价 |
| `pct_change` | 当日涨跌幅（%）|

---

### 3. Trending 排行榜
```
GET /api/trending?days=30&limit=25
```

**参数：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `days` | int | 30 | 统计天数（1-90）|
| `limit` | int | 25 | 返回条数（1-100）|

**返回示例：**
```json
{
  "days": 30,
  "total": 25,
  "data": [
    {
      "symbol": "NVDA",
      "sector": "科技",
      "mentions": 46369,
      "bullish": 16948,
      "bearish": 4711,
      "daily_avg": 1545.6
    }
  ]
}
```

---

### 4. 整体统计
```
GET /api/stats
```
返回数据库总量、各 ticker 分布、情绪比例。

**返回示例：**
```json
{
  "overview": {
    "total": 287086,
    "symbols": 31,
    "total_likes": 45231,
    "latest_at": "2026-06-12T06:30:00+00:00"
  },
  "by_symbol": [...],
  "by_sentiment": [
    {"sentiment": "Bullish", "cnt": 89234},
    {"sentiment": "Bearish", "cnt": 31205}
  ],
  "trending_now": [...]
}
```

---

### 5. 帖子列表
```
GET /api/posts?symbol=NVDA&sentiment=Bullish&limit=50&offset=0
```

**参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| `symbol` | string | 股票代码，如 `NVDA` |
| `sentiment` | string | `Bullish` 或 `Bearish` |
| `limit` | int | 返回条数，最大 500 |
| `offset` | int | 分页偏移 |

---

## 调用示例

**Python：**
```python
import requests

BASE = "https://unlawful-cricket-willfully.ngrok-free.dev"

# 获取信号
signals = requests.get(f"{BASE}/api/signals").json()

# 获取 NVDA 近7天 trending
trending = requests.get(f"{BASE}/api/trending", params={"days": 7}).json()

# 获取 NVDA 最新 Bullish 帖子
posts = requests.get(f"{BASE}/api/posts", params={"symbol": "NVDA", "sentiment": "Bullish", "limit": 20}).json()
```

**curl：**
```bash
curl "https://unlawful-cricket-willfully.ngrok-free.dev/api/signals"
curl "https://unlawful-cricket-willfully.ngrok-free.dev/api/trending?days=7&limit=10"
```

---

## 在线文档（Swagger UI）
访问以下地址可以直接在浏览器里测试所有接口：  
`https://unlawful-cricket-willfully.ngrok-free.dev/docs`

---

## 注意事项
- 当前部署为本地 ngrok 转发，**电脑开机时 API 可用**
- 数据每 5 分钟自动更新一次
- 如需稳定的生产环境部署，可迁移至 Railway / Render
