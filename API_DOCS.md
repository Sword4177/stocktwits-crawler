# StockTwits Sentiment API — 接入文档

**Base URL**: `https://stocktwits-crawler-production.up.railway.app`  
**部署**: Railway（固定域名，7×24 小时在线）  
**数据**: 306,000+ 条 StockTwits 帖子，覆盖 30+ 半导体 / AI ticker，每 5 分钟更新

---

## 认证

所有 `/api/signals/*` 端点需要在请求头中携带 API Key：

```
X-API-Key: YOUR_API_KEY
```

API Key 通过私信或飞书单独发放，请勿在代码中硬编码或公开分享。

**无 key 或错误 key 返回：**
```json
{"detail": "Invalid or missing X-API-Key"}
```
HTTP 状态码：`401`

---

## 限流

- 每个 IP 最多 **60 次/分钟**
- 超出返回 HTTP `429`：
```json
{"detail": "Rate limit exceeded: 60 req/min"}
```

---

## 板块（sector）可用值

| 英文参数值 | 实际板块 | 包含 ticker（示例）|
|-----------|---------|-----------------|
| `semiconductor` | 半导体 | MU, SNDK, AVGO, ARM, TSM, AMAT, LRCX, ASML, MRVL |
| `tech` | 科技 | NVDA, AMD, MSFT, AAPL, INTC, QCOM, SMCI |
| `ai` | 科技（与 `tech` 等价） | GOOGL, META（同科技板块）|
| `consumer` | 消费 | TSLA, BABA, NIO, JD, PDD |
| `finance` | 金融 | JPM, GS, BAC |
| `energy` | 能源 | XOM, CVX |
| `crypto` | 加密货币 | — |
| `all` | 全部 | 所有 ticker |

> **注意**：`sector=ai` 与 `sector=tech` 完全等价，两者都查询科技板块（数据库中统一存储为「科技」）。推荐统一使用 `tech`。

---

## 接口列表

### 健康检查

```
GET /
```

**curl 示例：**
```bash
curl https://stocktwits-crawler-production.up.railway.app/
```

**返回：**
```json
{
  "status": "ok",
  "service": "SentinelFlow StockTwits API",
  "version": "2.0.0"
}
```

---

### 1. 热度排行 `GET /api/signals/trending`

按提及量降序返回 ticker 情绪排行。

**请求参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `sector` | string | 否 | all | 板块过滤，见上方可用值 |
| `window` | string | 否 | 24h | 时间窗口：`1h` \| `4h` \| `24h` |
| `limit` | int | 否 | 20 | 返回条数（1-100）|

**curl 示例：**
```bash
curl -H "X-API-Key: YOUR_API_KEY" \
  "https://stocktwits-crawler-production.up.railway.app/api/signals/trending?window=24h&limit=3"
```

**Python 示例：**
```python
import requests

resp = requests.get(
    "https://stocktwits-crawler-production.up.railway.app/api/signals/trending",
    headers={"X-API-Key": "YOUR_API_KEY"},
    params={"window": "24h", "limit": 3}
)
print(resp.json())
```

**真实返回：**
```json
{
  "window": "24h",
  "sector": "all",
  "total": 3,
  "data": [
    {
      "symbol": "NVDA",
      "sector": "科技",
      "mentions": 159,
      "bullish_count": 60,
      "bearish_count": 16,
      "sentiment_score": 0.2767
    },
    {
      "symbol": "MSFT",
      "sector": "科技",
      "mentions": 136,
      "bullish_count": 24,
      "bearish_count": 27,
      "sentiment_score": -0.0221
    },
    {
      "symbol": "TSLA",
      "sector": "消费",
      "mentions": 135,
      "bullish_count": 37,
      "bearish_count": 22,
      "sentiment_score": 0.1111
    }
  ]
}
```

**字段说明：**

| 字段 | 说明 |
|------|------|
| `mentions` | 时间窗口内提及次数 |
| `bullish_count` | Bullish 帖子数量 |
| `bearish_count` | Bearish 帖子数量 |
| `sentiment_score` | (bullish - bearish) / total，范围 **-1 到 +1**，> 0 偏多，< 0 偏空 |

---

### 2. 单 Ticker 情绪快照 `GET /api/signals/ticker/{symbol}`

返回指定 ticker 在时间窗口内的完整情绪数据和热度信息。

**路径参数：** `symbol` — 股票代码，如 `NVDA`

**请求参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `window` | string | 否 | 24h | 时间窗口：`1h` \| `4h` \| `24h` |

**curl 示例：**
```bash
curl -H "X-API-Key: YOUR_API_KEY" \
  "https://stocktwits-crawler-production.up.railway.app/api/signals/ticker/NVDA?window=24h"
```

**真实返回：**
```json
{
  "symbol": "NVDA",
  "window": "24h",
  "mentions": 159,
  "bullish_count": 60,
  "bearish_count": 16,
  "sentiment_score": 0.2767,
  "buzz_baseline_per_window": 304.9,
  "buzz_ratio": 0.52,
  "top_posts": [
    {
      "id": "656669121",
      "body": "$NVDA call buyer at my support levels 207.5 needs to hold or it goes down to 205 202.5 and then 200",
      "sentiment": "",
      "likes": 0,
      "published_at": "2026-06-17T05:58:36+00:00"
    }
  ]
}
```

**字段说明：**

| 字段 | 说明 |
|------|------|
| `mentions` | 时间窗口内提及次数 |
| `sentiment_score` | 范围 **-1 到 +1**，> 0 偏多，< 0 偏空 |
| `buzz_baseline_per_window` | 过去 7 天同长度窗口的平均提及量（7日每日均值 × 窗口小时数 / 24）|
| `buzz_ratio` | mentions / buzz_baseline_per_window；**> 1.5** 表示当前热度明显高于基线，< 1 表示低于正常水平 |
| `top_posts` | 点赞数最高的 3 条帖子 |

---

### 3. 实时异动预警 `GET /api/signals/alerts`

返回近期触发的热度或情绪异动事件。

**请求参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `limit` | int | 否 | 20 | 返回条数（1-100）|
| `min_spike` | float | 否 | 1.5 | buzz_spike 触发阈值：近 24h 提及量需达到 7 日均值的 min_spike 倍才触发 |
| `min_delta` | float | 否 | 0.3 | sentiment_shift 触发阈值：近 4h 与近 24h 情绪分差值需超过 min_delta 才触发 |
| `sector` | string | 否 | all | 板块过滤，见上方板块可用值 |

**触发规则：**
- `buzz_spike`：近 24h 提及量 ≥ 7 日均值 × min_spike，且股价变动 < 3%
- `sentiment_shift`：近 4h 情绪分与 24h 均值偏差 > min_delta，且提及量 ≥ 5 条

**curl 示例：**
```bash
# 默认阈值（min_spike=1.5，min_delta=0.3）
curl -H "X-API-Key: YOUR_API_KEY" \
  "https://stocktwits-crawler-production.up.railway.app/api/signals/alerts"

# 放宽阈值，更容易触发（min_spike=1.0）
curl -H "X-API-Key: YOUR_API_KEY" \
  "https://stocktwits-crawler-production.up.railway.app/api/signals/alerts?min_spike=1.0&min_delta=0.2"

# 只看半导体板块
curl -H "X-API-Key: YOUR_API_KEY" \
  "https://stocktwits-crawler-production.up.railway.app/api/signals/alerts?sector=semiconductor"
```

**真实返回：**
```json
{
  "total": 1,
  "buzz_spikes": 0,
  "sentiment_shifts": 1,
  "data": [
    {
      "symbol": "AMZN",
      "alert_type": "sentiment_shift",
      "score_4h": 0.5714,
      "score_24h": 0.2603,
      "delta": 0.3111,
      "mentions_4h": 7
    }
  ]
}
```

**字段说明：**

| 字段 | 说明 |
|------|------|
| `alert_type` | `buzz_spike` 或 `sentiment_shift` |
| `score_4h` | 近 4h 情绪分（-1 到 +1）|
| `score_24h` | 近 24h 情绪分（基准）|
| `delta` | 情绪分变化量，正值代表近期更偏多头 |
| `mentions_4h` | 近 4h 提及次数 |

> **提示**：`total=0` 时说明当前没有达到阈值的异动。可降低 `min_spike` 或 `min_delta` 来查看更多候选信号。

---

### 4. 板块聚合情绪 `GET /api/signals/sector/{sector}`

返回指定板块所有 ticker 的聚合情绪和各 ticker 细分。

**路径参数：** `sector` — 见上方板块可用值，如 `semiconductor`

**请求参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `window` | string | 否 | 24h | 时间窗口：`1h` \| `4h` \| `24h` |

**curl 示例：**
```bash
curl -H "X-API-Key: YOUR_API_KEY" \
  "https://stocktwits-crawler-production.up.railway.app/api/signals/sector/semiconductor?window=24h"
```

**真实返回：**
```json
{
  "sector": "semiconductor",
  "window": "24h",
  "total_mentions": 417,
  "sentiment_score": 0.0767,
  "bullish_count": 101,
  "bearish_count": 69,
  "tickers": [
    {
      "symbol": "MU",
      "sector": "半导体",
      "mentions": 118,
      "bullish_count": 35,
      "bearish_count": 8,
      "sentiment_score": 0.2288
    },
    {
      "symbol": "SNDK",
      "sector": "半导体",
      "mentions": 115,
      "bullish_count": 16,
      "bearish_count": 42,
      "sentiment_score": -0.2261
    }
  ]
}
```

**字段说明：**

| 字段 | 说明 |
|------|------|
| `sentiment_score` | 板块整体情绪分，范围 **-1 到 +1** |
| `tickers` | 板块内各 ticker 明细，按提及量降序 |

---

### 5. 原始帖子流 `GET /api/signals/feed/{symbol}`

返回指定 ticker 的原始帖子，支持 cursor 翻页。

**路径参数：** `symbol` — 股票代码，如 `NVDA`

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sentiment` | string | 否 | 过滤情绪：`Bullish` 或 `Bearish` |
| `cursor` | string | 否 | 翻页游标，填上次返回的 `next_cursor` |
| `limit` | int | 否 | 返回条数，默认 20，最大 100 |

**curl 示例：**
```bash
# 第一页
curl -H "X-API-Key: YOUR_API_KEY" \
  "https://stocktwits-crawler-production.up.railway.app/api/signals/feed/NVDA?limit=2"

# 翻页（填入上次返回的 next_cursor）
curl -H "X-API-Key: YOUR_API_KEY" \
  "https://stocktwits-crawler-production.up.railway.app/api/signals/feed/NVDA?limit=2&cursor=2026-06-17T05:50:48+00:00"
```

**真实返回：**
```json
{
  "symbol": "NVDA",
  "count": 2,
  "next_cursor": "2026-06-17T05:50:48+00:00",
  "data": [
    {
      "id": "656669121",
      "symbol": "NVDA",
      "body": "$NVDA call buyer at my support levels 207.5 needs to hold or it goes down to 205 202.5 and then 200",
      "sentiment": "",
      "likes": 0,
      "username": "Rema1",
      "published_at": "2026-06-17T05:58:36+00:00"
    },
    {
      "id": "656669005",
      "symbol": "NVDA",
      "body": "$NVDA and $META are also goofy cheap… get ready for liftoff",
      "sentiment": "",
      "likes": 0,
      "username": "emeraldbayrider",
      "published_at": "2026-06-17T05:50:48+00:00"
    }
  ]
}
```

**字段说明：**

| 字段 | 说明 |
|------|------|
| `next_cursor` | 下一页的游标，`null` 表示已到最后一页 |
| `sentiment` | `Bullish` / `Bearish` / 空（未标注）|

---

## Swagger UI

在浏览器直接测试所有接口：

```
https://stocktwits-crawler-production.up.railway.app/docs
```

---

## 旧版端点（已废弃）

以下端点为早期版本保留，**不推荐新接入方使用**，未来可能移除：

| 端点 | 替代接口 |
|------|---------|
| `GET /api/trending` | `GET /api/signals/trending` |
| `GET /api/posts` | `GET /api/signals/feed/{symbol}` |
| `GET /api/stats` | — |

旧版 `/api/trending` 参数为 `days`（天数），返回字段与新版不同，不含 `sentiment_score`。
