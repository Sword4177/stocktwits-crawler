"""
api.py — FastAPI 对外接口
运行：uvicorn api:app --reload --port 8001
"""
import sqlite3
from typing import Optional
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from database import get_conn, init_db

app = FastAPI(
    title="SentinelFlow StockTwits API",
    description="散户情绪监控 API — 提供 Trending 排行、热度异动信号、帖子数据",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def query(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.on_event("startup")
def startup():
    conn = get_conn()
    init_db(conn)
    conn.close()


@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "service": "SentinelFlow StockTwits API", "version": "1.0.0"}


@app.get("/api/posts")
def get_posts(
    symbol:    Optional[str] = Query(None, description="股票代码，如 NVDA"),
    source:    Optional[str] = Query(None, description="来源：symbol 或 trending"),
    sentiment: Optional[str] = Query(None, description="情绪：Bullish 或 Bearish"),
    limit:     int           = Query(50, ge=1, le=500),
    offset:    int           = Query(0, ge=0),
):
    conditions, params = [], []

    if symbol:
        conditions.append("symbol = ?")
        params.append(symbol.upper())
    if source:
        conditions.append("source = ?")
        params.append(source)
    if sentiment:
        conditions.append("sentiment = ?")
        params.append(sentiment)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]

    rows = query(
        f"SELECT * FROM posts {where} ORDER BY published_at DESC LIMIT ? OFFSET ?",
        tuple(params),
    )
    return {"total": len(rows), "offset": offset, "data": rows}


@app.get("/api/posts/{post_id}")
def get_post(post_id: str):
    rows = query("SELECT * FROM posts WHERE id = ?", (post_id,))
    if not rows:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Post not found")
    return rows[0]


@app.get("/api/trending")
def get_trending(days: int = Query(30, ge=1, le=90), limit: int = Query(25, ge=1, le=100)):
    rows = query("""
        SELECT p.symbol,
               COALESCE(s.sector, '') AS sector,
               COUNT(*) AS mentions,
               SUM(CASE WHEN p.sentiment='Bullish' THEN 1 ELSE 0 END) AS bullish,
               SUM(CASE WHEN p.sentiment='Bearish' THEN 1 ELSE 0 END) AS bearish,
               ROUND(COUNT(*) * 1.0 / ?, 1) AS daily_avg
        FROM posts p
        LEFT JOIN symbols s ON p.symbol = s.symbol
        WHERE p.published_at >= datetime('now', ? || ' days')
        GROUP BY p.symbol
        ORDER BY mentions DESC
        LIMIT ?
    """, (days, f'-{days}', limit))
    return {"days": days, "total": len(rows), "data": rows}


@app.get("/api/signals")
def get_signals():
    rows = query("""
        WITH recent AS (
            SELECT symbol, COUNT(*) AS cnt
            FROM posts WHERE published_at >= datetime('now', '-1 day')
            GROUP BY symbol
        ),
        avg30 AS (
            SELECT symbol, COUNT(*) * 1.0 / 30 AS daily_avg
            FROM posts
            WHERE published_at >= datetime('now', '-31 days')
              AND published_at < datetime('now', '-1 day')
            GROUP BY symbol
        ),
        lp AS (
            SELECT p.symbol, p.close, p.pct_change
            FROM prices p
            INNER JOIN (
                SELECT symbol, MAX(date) AS mx FROM prices GROUP BY symbol
            ) m ON p.symbol = m.symbol AND p.date = m.mx
        )
        SELECT r.symbol,
               r.cnt                                    AS mentions_24h,
               ROUND(a.daily_avg, 1)                   AS daily_avg_30d,
               ROUND(r.cnt * 1.0 / a.daily_avg, 2)     AS ratio,
               ROUND(lp.close, 2)                       AS price,
               ROUND(lp.pct_change * 100, 2)            AS pct_change
        FROM recent r
        JOIN avg30 a ON r.symbol = a.symbol
        JOIN lp    ON r.symbol = lp.symbol
        WHERE r.cnt >= a.daily_avg * 1.5
          AND ABS(lp.pct_change) < 0.03
        ORDER BY ratio DESC
    """)
    return {"total": len(rows), "description": "mentions_24h >= 1.5x 30d avg AND abs(price_change) < 3%", "data": rows}


@app.get("/api/stats")
def get_stats():
    stats = query("""
        SELECT COUNT(*) AS total,
               COUNT(DISTINCT symbol) AS symbols,
               SUM(likes) AS total_likes,
               MAX(published_at) AS latest_at
        FROM posts
    """)[0]

    by_symbol = query("""
        SELECT symbol, COUNT(*) AS cnt,
               SUM(CASE WHEN sentiment='Bullish' THEN 1 ELSE 0 END) AS bullish,
               SUM(CASE WHEN sentiment='Bearish' THEN 1 ELSE 0 END) AS bearish
        FROM posts GROUP BY symbol ORDER BY cnt DESC LIMIT 30
    """)

    by_sentiment = query("""
        SELECT sentiment, COUNT(*) AS cnt FROM posts
        WHERE sentiment != '' GROUP BY sentiment ORDER BY cnt DESC
    """)

    trending_now = query("""
        SELECT symbol, COUNT(*) AS cnt FROM posts
        WHERE source='trending' AND published_at >= datetime('now', '-1 hour')
        GROUP BY symbol ORDER BY cnt DESC LIMIT 10
    """)

    return {
        "overview":      stats,
        "by_symbol":     by_symbol,
        "by_sentiment":  by_sentiment,
        "trending_now":  trending_now,
    }
