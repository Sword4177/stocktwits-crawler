# StockTwits Sentiment API — 接入文档

**Base URL**: `https://stocktwits-crawler-production.up.railway.app`  
**数据来源**: StockTwits 实时数据，覆盖 27 个半导体/AI 板块 ticker  
**数据量**: 306,000+ 条帖子，持续更新  
**部署**: Railway（固定域名，7×24 小时在线）

---

## 认证

所有 `/api/signals/*` 端点需要在请求头中携带 API Key：

```
X-API-Key: stocktwits-2026
```

未携带或错误返回 `401 Unauthorized`。

---

## 限流

每个 IP 最多 **60 次/分钟**，超出返回 `429 Too Many Requests`。

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
  "version": "2.0.0"
}
```

---

### 2. 热度排行
```
GET /api/signals/trending
```

**参数：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `sector` | string | all | 板块过滤：`semiconductor` \| `ai` \| `all` |
| `window` | string | 24h | 时间窗口：`1h` \| `4h` \| `24h` |
| `limit` | int | 20 | 返回条数（1-100）|

**返回示例：**
```json
{
  "window": "24h",
  "sector": "all",
  "total": 10,
  "data": [
    {
      "symbol": "NVDA",
      "sector": "科技",
      "mentions": 520,
      "bullish_count": 312,
      "bearish_count": 89,
      "sentiment_score": 0.4288
    }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `sentiment_score` | (bullish - bearish) / total，范围 -1 到 1 |

---

### 3. 单 Ticker 情绪快照
```
GET /api/signals/ticker/{symbol}
```

**参数：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `window` | string | 24h | 时间窗口：`1h` \| `4h` \| `24h` |

**返回示例：**
```json
{
  "symbol": "NVDA",
  "window": "24h",
  "mentions": 520,
  "bullish_count": 312,
  "bearish_count": 89,
  "sentiment_score": 0.4288,
  "buzz_baseline_per_window": 302.1,
  "buzz_ratio": 1.72,
  "top_posts": [
    {
      "id": "656422638",
      "body": "$NVDA breaking out!",
      "sentiment": "Bullish",
      "likes": 12,
      "published_at": "2026-06-16T03:22:12+00:00"
    }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `buzz_ratio` | 当前窗口提及量 / 7日同窗口均值 |
| `top_posts` | 点赞数最高的 3 条帖子 |

---

### 4. 实时异动预警
```
GET /api/signals/alerts
```

返回两类信号：
- **buzz_spike**: 近24h提及量 ≥ 7日均值 1.5x，且股价变动 < 3%
- **sentiment_shift**: 近4h情绪分与24h均值偏差 > 0.3

**参数：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | int | 20 | 返回条数（1-100）|

**返回示例：**
```json
{
  "total": 2,
  "buzz_spikes": 1,
  "sentiment_shifts": 1,
  "data": [
    {
      "symbol": "NVDA",
      "alert_type": "buzz_spike",
      "mentions_24h": 520,
      "baseline_daily": 302.1,
      "buzz_ratio": 1.72,
      "price": 131.38,
      "pct_change": -1.2
    },
    {
      "symbol": "AMD",
      "alert_type": "sentiment_shift",
      "score_4h": 0.65,
      "score_24h": 0.21,
      "delta": 0.44,
      "mentions_4h": 38
    }
  ]
}
```

---

### 5. 板块聚合情绪
```
GET /api/signals/sector/{sector}
```

**路径参数：** `semiconductor` \| `ai` \| `all`

**参数：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `window` | string | 24h | 时间窗口：`1h` \| `4h` \| `24h` |

**返回示例：**
```json
{
  "sector": "semiconductor",
  "window": "24h",
  "total_mentions": 3200,
  "sentiment_score": 0.31,
  "bullish_count": 1820,
  "bearish_count": 640,
  "tickers": [
    {
      "symbol": "NVDA",
      "sector": "科技",
      "mentions": 520,
      "bullish_count": 312,
      "bearish_count": 89,
      "sentiment_score": 0.4288
    }
  ]
}
```

---

### 6. 原始帖子流
```
GET /api/signals/feed/{symbol}
```

**参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| `sentiment` | string | `Bullish` 或 `Bearish` |
| `cursor` | string | 分页游标（上次返回的 `next_cursor`）|
| `limit` | int | 返回条数，默认 20，最大 100 |

**返回示例：**
```json
{
  "symbol": "NVDA",
  "count": 20,
  "next_cursor": "2026-06-15T03:21:40+00:00",
  "data": [
    {
      "id": "656422638",
      "symbol": "NVDA",
      "body": "$NVDA breaking out!",
      "sentiment": "Bullish",
      "likes": 0,
      "username": "trader123",
      "published_at": "2026-06-16T03:22:12+00:00"
    }
  ]
}
```

---

## 调用示例

**Python：**
```python
import requests

BASE = "https://stocktwits-crawler-production.up.railway.app"
HEADERS = {"X-API-Key": "stocktwits-2026"}

# 热度排行（半导体板块，过去4小时）
trending = requests.get(f"{BASE}/api/signals/trending",
    params={"sector": "semiconductor", "window": "4h"},
    headers=HEADERS).json()

# NVDA 情绪快照
nvda = requests.get(f"{BASE}/api/signals/ticker/NVDA",
    params={"window": "24h"},
    headers=HEADERS).json()

# 实时预警
alerts = requests.get(f"{BASE}/api/signals/alerts",
    headers=HEADERS).json()

# NVDA 原始帖子（翻页）
feed = requests.get(f"{BASE}/api/signals/feed/NVDA",
    params={"limit": 20},
    headers=HEADERS).json()
next_page = requests.get(f"{BASE}/api/signals/feed/NVDA",
    params={"limit": 20, "cursor": feed["next_cursor"]},
    headers=HEADERS).json()
```

**curl：**
```bash
curl -H "X-API-Key: stocktwits-2026" \
  "https://stocktwits-crawler-production.up.railway.app/api/signals/trending?window=4h"

curl -H "X-API-Key: stocktwits-2026" \
  "https://stocktwits-crawler-production.up.railway.app/api/signals/alerts"
```

---

## 在线文档（Swagger UI）
```
https://stocktwits-crawler-production.up.railway.app/docs
```

---

## Ticker 覆盖范围

**半导体（18个）**: NVDA, AMD, TSM, INTC, AVGO, AMAT, LRCX, KLAC, MU, ASML, QCOM, TXN, ADI, MCHP, ON, SWKS, MPWR, ENTG

**AI（9个）**: MSFT, GOOGL, META, AMZN, PLTR, AI, SOUN, BBAI, IONQ

---

## 注意事项
- 数据每 5 分钟自动更新一次
- `sentiment_score` 范围：-1（极度看跌）到 +1（极度看多）
- `buzz_ratio` > 1.5 表示热度异常
- `window` 参数影响所有时间相关计算的基准窗口
