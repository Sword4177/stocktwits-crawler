"""
api.py — FastAPI 对外接口
运行：uvicorn api:app --reload --port 8001
"""
import time
import json
import asyncio
import logging
from collections import defaultdict
from typing import Optional
from fastapi import FastAPI, Query, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from database import get_conn, init_db
from config import API_KEY

logger = logging.getLogger(__name__)

app = FastAPI(
    title="StockTwits Sentiment API",
    description="散户情绪监控 API — 提供 Trending 排行、热度异动信号、帖子数据",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate limiting (60 req/min per IP) ─────────────────────────────────────────
_rate_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 60
RATE_WINDOW = 60.0


def check_rate_limit(request: Request):
    ip = request.client.host
    now = time.time()
    hits = [t for t in _rate_store[ip] if now - t < RATE_WINDOW]
    if len(hits) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded: 60 req/min")
    hits.append(now)
    _rate_store[ip] = hits


# ── Auth ───────────────────────────────────────────────────────────────────────
def require_api_key(request: Request):
    if not API_KEY:
        return  # no key configured → open
    key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


DEPS = [Depends(check_rate_limit), Depends(require_api_key)]


# ── DB helpers ─────────────────────────────────────────────────────────────────
def _is_pg(conn) -> bool:
    try:
        import psycopg2
        return isinstance(conn, psycopg2.extensions.connection)
    except ImportError:
        return False


def query(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_conn()
    pg = _is_pg(conn)
    if pg:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [dict(r) for r in rows]
    else:
        import sqlite3
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def _interval(window: str, pg: bool) -> str:
    """Convert window string to SQL interval expression."""
    mapping = {"1h": ("1", "-1 hours"), "4h": ("4", "-4 hours"), "24h": ("24", "-24 hours")}
    hours, sqlite_delta = mapping.get(window, ("24", "-24 hours"))
    if pg:
        return f"NOW() - INTERVAL '{hours} hours'"
    return f"datetime('now', '{sqlite_delta}')"


def _write_snapshots() -> None:
    """每5分钟写入一次 ticker_signals 快照（仅 PostgreSQL）。"""
    conn = get_conn()
    if not _is_pg(conn):
        conn.close()
        return
    try:
        import psycopg2.extras
        cur = conn.cursor()

        # 7日基线（一次查全量）
        cur.execute("""
            SELECT symbol, COUNT(*) * 1.0 / 7 AS daily_avg
            FROM posts WHERE published_at >= NOW() - INTERVAL '7 days'
            GROUP BY symbol
        """)
        baseline = {row[0]: row[1] for row in cur.fetchall()}

        rows: list = []
        for window, hours in [("1h", 1), ("4h", 4), ("24h", 24)]:
            cur.execute(f"""
                SELECT symbol,
                       COUNT(*) AS mentions,
                       SUM(CASE WHEN sentiment='Bullish' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN sentiment='Bearish' THEN 1 ELSE 0 END),
                       ROUND(
                           (SUM(CASE WHEN sentiment='Bullish' THEN 1.0 ELSE 0 END) -
                            SUM(CASE WHEN sentiment='Bearish' THEN 1.0 ELSE 0 END))
                           / NULLIF(COUNT(*), 0), 4
                       )
                FROM posts
                WHERE published_at >= NOW() - INTERVAL '{hours} hours'
                GROUP BY symbol
                HAVING COUNT(*) > 0
            """)
            for sym, mentions, bullish, bearish, score in cur.fetchall():
                daily_avg  = baseline.get(sym, 0)
                window_base = daily_avg / 24 * hours if daily_avg else 0
                buzz_ratio  = round(mentions / window_base, 2) if window_base else 0
                rows.append((sym, window, int(mentions), int(bullish), int(bearish),
                             float(score or 0), round(window_base, 1), buzz_ratio))

        if rows:
            psycopg2.extras.execute_values(cur, """
                INSERT INTO ticker_signals
                  (symbol, time_window, mentions, bullish_count, bearish_count,
                   sentiment_score, buzz_baseline, buzz_ratio)
                VALUES %s
            """, rows)
            conn.commit()
            logger.info("ticker_signals: wrote %d rows", len(rows))
    except Exception as e:
        logger.error("snapshot write failed: %s", e)
        conn.rollback()
    finally:
        conn.close()


def _check_alert_frequency() -> None:
    """当 sentiment_shift 触发数超过 15 时打 WARNING，提示阈值可能需要上调。"""
    conn = get_conn()
    if not _is_pg(conn):
        conn.close()
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            WITH recent_4h AS (
                SELECT symbol,
                       ROUND(
                           (SUM(CASE WHEN sentiment='Bullish' THEN 1.0 ELSE 0 END) -
                            SUM(CASE WHEN sentiment='Bearish' THEN 1.0 ELSE 0 END))
                           / NULLIF(COUNT(*), 0), 4
                       ) AS score_4h,
                       COUNT(*) AS cnt_4h
                FROM posts WHERE published_at >= NOW() - INTERVAL '4 hours'
                GROUP BY symbol
            ),
            baseline_24h AS (
                SELECT symbol,
                       ROUND(
                           (SUM(CASE WHEN sentiment='Bullish' THEN 1.0 ELSE 0 END) -
                            SUM(CASE WHEN sentiment='Bearish' THEN 1.0 ELSE 0 END))
                           / NULLIF(COUNT(*), 0), 4
                       ) AS score_24h
                FROM posts WHERE published_at >= NOW() - INTERVAL '24 hours'
                GROUP BY symbol
            )
            SELECT COUNT(*) FROM recent_4h r
            JOIN baseline_24h b ON r.symbol = b.symbol
            WHERE ABS(r.score_4h - b.score_24h) > 0.15 AND r.cnt_4h >= 5
        """)
        count = cur.fetchone()[0]
        if count > 15:
            logger.warning("ALERT_FREQ_HIGH: sentiment_shift=%d (>15), consider raising min_delta", count)
        else:
            logger.info("alert_check: sentiment_shift=%d (OK)", count)
    except Exception as e:
        logger.error("alert check failed: %s", e)
    finally:
        conn.close()


async def _snapshot_loop() -> None:
    while True:
        await asyncio.sleep(300)
        try:
            _write_snapshots()
            _check_alert_frequency()
        except Exception as e:
            logger.error("snapshot loop error: %s", e)


@app.on_event("startup")
async def startup():
    conn = get_conn()
    init_db(conn)
    conn.close()
    asyncio.create_task(_snapshot_loop())


# ── Health ─────────────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "service": "SentinelFlow StockTwits API", "version": "2.0.0"}




SECTOR_MAP = {
    "semiconductor": "半导体",
    "tech": "科技",
    "ai": "科技",
    "finance": "金融",
    "energy": "能源",
    "consumer": "消费",
    "healthcare": "医疗",
    "crypto": "加密货币",
}


def _sector_cn(sector: str) -> str:
    return SECTOR_MAP.get(sector.lower(), sector)


# ══════════════════════════════════════════════════════════════════════════════
# ARTI Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/signals/trending", tags=["ARTI"], dependencies=DEPS)
def signals_trending(
    sector: Optional[str] = Query(None, description="板块过滤: semiconductor | ai | all"),
    window: str           = Query("24h", description="时间窗口: 1h | 4h | 24h"),
    limit:  int           = Query(20, ge=1, le=100),
):
    """热度排行：按提及量降序，返回 sentiment_score 和 buzz 倍数。"""
    conn = get_conn()
    pg = _is_pg(conn)
    conn.close()
    since = _interval(window, pg)
    hours = {"1h": 1, "4h": 4, "24h": 24}.get(window, 24)
    ph = "%s" if pg else "?"

    sector_filter = ""
    params: list = []
    if sector and sector != "all":
        sector_cn = _sector_cn(sector)
        sector_filter = f"AND s.sector = {ph}"
        params.append(sector_cn)

    params += [limit]

    rows = query(f"""
        SELECT p.symbol,
               COALESCE(s.sector, '') AS sector,
               COUNT(*) AS mentions,
               SUM(CASE WHEN p.sentiment='Bullish' THEN 1 ELSE 0 END) AS bullish_count,
               SUM(CASE WHEN p.sentiment='Bearish' THEN 1 ELSE 0 END) AS bearish_count,
               ROUND(
                   (SUM(CASE WHEN p.sentiment='Bullish' THEN 1.0 ELSE 0 END) -
                    SUM(CASE WHEN p.sentiment='Bearish' THEN 1.0 ELSE 0 END))
                   / NULLIF(COUNT(*), 0), 4
               ) AS sentiment_score
        FROM posts p
        LEFT JOIN symbols s ON p.symbol = s.symbol
        WHERE p.published_at >= {since}
          {sector_filter}
        GROUP BY p.symbol, s.sector
        ORDER BY mentions DESC
        LIMIT {ph}
    """, tuple(params))

    # 7-day baseline for spike_ratio
    if pg:
        since_7d = "NOW() - INTERVAL '7 days'"
    else:
        since_7d = "datetime('now', '-7 days')"

    baseline_rows = query(f"""
        SELECT symbol, COUNT(*) * 1.0 / 7 AS daily_avg
        FROM posts WHERE published_at >= {since_7d}
        GROUP BY symbol
    """)
    baseline = {r["symbol"]: r["daily_avg"] for r in baseline_rows}

    for r in rows:
        m = r["mentions"]
        daily_avg = baseline.get(r["symbol"], 0)
        window_baseline = daily_avg / 24 * hours if daily_avg else None
        r["bullish_pct"]  = round(r["bullish_count"] * 100.0 / m, 1) if m else 0
        r["bearish_pct"]  = round(r["bearish_count"] * 100.0 / m, 1) if m else 0
        r["spike_ratio"]  = round(m / window_baseline, 2) if window_baseline else None

    return {"window": window, "sector": sector or "all", "total": len(rows), "data": rows}


@app.get("/api/signals/ticker/{symbol}", tags=["ARTI"], dependencies=DEPS)
def signals_ticker(
    symbol: str,
    window: str = Query("24h", description="时间窗口: 1h | 4h | 24h"),
):
    """单 ticker 情绪快照：sentiment_score、buzz_ratio、top3 帖子。"""
    sym = symbol.upper()
    conn = get_conn()
    pg = _is_pg(conn)
    conn.close()
    since = _interval(window, pg)
    ph = "%s" if pg else "?"

    agg = query(f"""
        SELECT COUNT(*) AS mentions,
               SUM(CASE WHEN sentiment='Bullish' THEN 1 ELSE 0 END) AS bullish_count,
               SUM(CASE WHEN sentiment='Bearish' THEN 1 ELSE 0 END) AS bearish_count,
               ROUND(
                   (SUM(CASE WHEN sentiment='Bullish' THEN 1.0 ELSE 0 END) -
                    SUM(CASE WHEN sentiment='Bearish' THEN 1.0 ELSE 0 END))
                   / NULLIF(COUNT(*), 0), 4
               ) AS sentiment_score
        FROM posts
        WHERE symbol = {ph} AND published_at >= {since}
    """, (sym,))

    if not agg or agg[0]["mentions"] == 0:
        raise HTTPException(status_code=404, detail=f"No data for {sym} in window {window}")

    # 7-day baseline for buzz ratio
    if pg:
        baseline_since = "NOW() - INTERVAL '7 days'"
    else:
        baseline_since = "datetime('now', '-7 days')"

    baseline = query(f"""
        SELECT COUNT(*) * 1.0 / 7 AS daily_avg
        FROM posts
        WHERE symbol = {ph} AND published_at >= {baseline_since}
    """, (sym,))
    daily_avg = baseline[0]["daily_avg"] or 0

    # window hours for buzz_ratio denominator
    hours = {"1h": 1, "4h": 4, "24h": 24}.get(window, 24)
    window_avg = daily_avg / 24 * hours
    mentions = agg[0]["mentions"]
    buzz_ratio = round(mentions / window_avg, 2) if window_avg > 0 else None

    top3 = query(f"""
        SELECT id, body, sentiment, likes, published_at
        FROM posts
        WHERE symbol = {ph} AND published_at >= {since}
        ORDER BY likes DESC, published_at DESC
        LIMIT 3
    """, (sym,))

    # delta_1h: 1h sentiment vs current window sentiment
    delta_1h = None
    if window != "1h":
        agg_1h = query(f"""
            SELECT ROUND(
                       (SUM(CASE WHEN sentiment='Bullish' THEN 1.0 ELSE 0 END) -
                        SUM(CASE WHEN sentiment='Bearish' THEN 1.0 ELSE 0 END))
                       / NULLIF(COUNT(*), 0), 4
                   ) AS score_1h
            FROM posts
            WHERE symbol = {ph} AND published_at >= {_interval('1h', pg)}
        """, (sym,))
        score_1h = agg_1h[0]["score_1h"] if agg_1h else None
        if score_1h is not None and agg[0]["sentiment_score"] is not None:
            delta_1h = round(score_1h - agg[0]["sentiment_score"], 4)

    bullish_count = agg[0]["bullish_count"]
    bearish_count = agg[0]["bearish_count"]
    neutral_count = mentions - bullish_count - bearish_count
    bullish_pct   = round(bullish_count * 100.0 / mentions, 1) if mentions else 0
    bearish_pct   = round(bearish_count * 100.0 / mentions, 1) if mentions else 0
    neutral_pct   = round(neutral_count * 100.0 / mentions, 1) if mentions else 0
    is_spike      = buzz_ratio is not None and buzz_ratio >= 2.0

    return {
        "symbol": sym,
        "window": window,
        "mentions": mentions,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "sentiment_score": agg[0]["sentiment_score"],
        "bullish_pct": bullish_pct,
        "bearish_pct": bearish_pct,
        "neutral_pct": neutral_pct,
        "buzz_baseline_per_window": round(window_avg, 1),
        "buzz_ratio": buzz_ratio,
        "is_spike": is_spike,
        "delta_1h": delta_1h,
        "top_posts": top3,
    }


@app.get("/api/signals/alerts", tags=["ARTI"], dependencies=DEPS)
def signals_alerts(
    limit:     int            = Query(20, ge=1, le=100),
    min_spike: float          = Query(2.0, ge=0.1, description="buzz_spike 最低倍数阈值，默认 2.0"),
    min_delta: float          = Query(0.15, ge=0.0, description="sentiment_shift 最低变化量阈值，默认 0.15"),
    sector:    Optional[str]  = Query(None, description="板块过滤: semiconductor | tech | ai | all"),
):
    """
    实时异动预警：
    - buzz_spike: 近24h提及量 >= 7日均值 min_spike 倍，且股价变动 < 3%
    - sentiment_shift: 近4h情绪分 与24h均值偏差 > min_delta，且提及量 >= 5
    """
    conn = get_conn()
    pg = _is_pg(conn)
    conn.close()
    ph = "%s" if pg else "?"

    if pg:
        since_24h = "NOW() - INTERVAL '24 hours'"
        since_4h  = "NOW() - INTERVAL '4 hours'"
        since_7d  = "NOW() - INTERVAL '7 days'"
    else:
        since_24h = "datetime('now', '-24 hours')"
        since_4h  = "datetime('now', '-4 hours')"
        since_7d  = "datetime('now', '-7 days')"

    sector_join = ""
    sector_cond = ""
    sector_params_pre: list = []
    if sector and sector.lower() not in ("all", ""):
        sector_cn = _sector_cn(sector)
        sector_join = f"JOIN symbols sx ON r.symbol = sx.symbol"
        sector_cond = f"AND sx.sector = {ph}"
        sector_params_pre = [sector_cn]

    try:
        buzz_spikes = query(f"""
            WITH recent AS (
                SELECT symbol, COUNT(*) AS cnt
                FROM posts WHERE published_at >= {since_24h}
                GROUP BY symbol
            ),
            baseline AS (
                SELECT symbol, COUNT(*) * 1.0 / 7 AS daily_avg
                FROM posts WHERE published_at >= {since_7d}
                  AND published_at < {since_24h}
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
                   'buzz_spike' AS alert_type,
                   r.cnt AS mentions_24h,
                   ROUND(b.daily_avg, 1) AS baseline_daily,
                   ROUND(r.cnt * 1.0 / b.daily_avg, 2) AS buzz_ratio,
                   ROUND(lp.close, 2) AS price,
                   ROUND(lp.pct_change * 100, 2) AS pct_change
            FROM recent r
            JOIN baseline b ON r.symbol = b.symbol
            JOIN lp ON r.symbol = lp.symbol
            {sector_join}
            WHERE r.cnt >= b.daily_avg * {ph}
              AND ABS(lp.pct_change) < 0.03
              {sector_cond}
            ORDER BY buzz_ratio DESC
            LIMIT {ph}
        """, tuple([min_spike] + sector_params_pre + [limit]))
    except Exception:
        buzz_spikes = []

    sentiment_shifts = query(f"""
        WITH recent_4h AS (
            SELECT symbol,
                   ROUND(
                       (SUM(CASE WHEN sentiment='Bullish' THEN 1.0 ELSE 0 END) -
                        SUM(CASE WHEN sentiment='Bearish' THEN 1.0 ELSE 0 END))
                       / NULLIF(COUNT(*), 0), 4
                   ) AS score_4h,
                   COUNT(*) AS cnt_4h
            FROM posts WHERE published_at >= {since_4h}
            GROUP BY symbol
        ),
        baseline_24h AS (
            SELECT symbol,
                   ROUND(
                       (SUM(CASE WHEN sentiment='Bullish' THEN 1.0 ELSE 0 END) -
                        SUM(CASE WHEN sentiment='Bearish' THEN 1.0 ELSE 0 END))
                       / NULLIF(COUNT(*), 0), 4
                   ) AS score_24h
            FROM posts WHERE published_at >= {since_24h}
            GROUP BY symbol
        )
        SELECT r.symbol,
               'sentiment_shift' AS alert_type,
               r.score_4h,
               b.score_24h,
               ROUND(r.score_4h - b.score_24h, 4) AS delta,
               r.cnt_4h AS mentions_4h
        FROM recent_4h r
        JOIN baseline_24h b ON r.symbol = b.symbol
        {sector_join}
        WHERE ABS(r.score_4h - b.score_24h) > {ph}
          AND r.cnt_4h >= 5
          {sector_cond}
        ORDER BY ABS(r.score_4h - b.score_24h) DESC
        LIMIT {ph}
    """, tuple([min_delta] + sector_params_pre + [limit]))

    alerts = buzz_spikes + sentiment_shifts
    alerts.sort(key=lambda x: x.get("buzz_ratio") or abs(x.get("delta", 0)), reverse=True)

    return {
        "total": len(alerts),
        "buzz_spikes": len(buzz_spikes),
        "sentiment_shifts": len(sentiment_shifts),
        "data": alerts[:limit],
    }


@app.get("/api/signals/sector/{sector}", tags=["ARTI"], dependencies=DEPS)
def signals_sector(
    sector: str,
    window: str = Query("24h", description="时间窗口: 1h | 4h | 24h"),
):
    """板块聚合情绪：返回板块整体 sentiment_score 和各 ticker 细分。"""
    conn = get_conn()
    pg = _is_pg(conn)
    conn.close()
    since = _interval(window, pg)
    ph = "%s" if pg else "?"

    if sector.lower() == "all":
        sector_cond = ""
        params: list = []
    else:
        sector_cn = _sector_cn(sector)
        sector_cond = f"AND s.sector = {ph}"
        params = [sector_cn]

    tickers = query(f"""
        SELECT p.symbol,
               COALESCE(s.sector, '') AS sector,
               COUNT(*) AS mentions,
               SUM(CASE WHEN p.sentiment='Bullish' THEN 1 ELSE 0 END) AS bullish_count,
               SUM(CASE WHEN p.sentiment='Bearish' THEN 1 ELSE 0 END) AS bearish_count,
               ROUND(
                   (SUM(CASE WHEN p.sentiment='Bullish' THEN 1.0 ELSE 0 END) -
                    SUM(CASE WHEN p.sentiment='Bearish' THEN 1.0 ELSE 0 END))
                   / NULLIF(COUNT(*), 0), 4
               ) AS sentiment_score
        FROM posts p
        LEFT JOIN symbols s ON p.symbol = s.symbol
        WHERE p.published_at >= {since}
          {sector_cond}
        GROUP BY p.symbol, s.sector
        ORDER BY mentions DESC
    """, tuple(params))

    if not tickers:
        raise HTTPException(status_code=404, detail=f"No data for sector '{sector}'")

    total_mentions = sum(r["mentions"] for r in tickers)
    total_bullish  = sum(r["bullish_count"] for r in tickers)
    total_bearish  = sum(r["bearish_count"] for r in tickers)
    agg_score = round((total_bullish - total_bearish) / total_mentions, 4) if total_mentions else 0

    # top_movers: top 3 by sentiment_score with at least 5 mentions
    top_movers = sorted(
        [t for t in tickers if t["mentions"] >= 5],
        key=lambda x: x["sentiment_score"],
        reverse=True
    )[:3]

    return {
        "sector": sector,
        "window": window,
        "total_mentions": total_mentions,
        "sentiment_score": agg_score,
        "bullish_count": total_bullish,
        "bearish_count": total_bearish,
        "top_movers": top_movers,
        "tickers": tickers,
    }


@app.get("/api/signals/feed/{symbol}", tags=["ARTI"], dependencies=DEPS)
def signals_feed(
    symbol:    str,
    sentiment: Optional[str] = Query(None, description="Bullish | Bearish"),
    cursor:    Optional[str] = Query(None, description="分页游标 (published_at ISO string)"),
    limit:     int           = Query(20, ge=1, le=100),
):
    """原始帖子流，支持 cursor 翻页（按 published_at 倒序）。"""
    sym = symbol.upper()
    conn = get_conn()
    pg = _is_pg(conn)
    conn.close()
    ph = "%s" if pg else "?"

    conditions = [f"symbol = {ph}"]
    params: list = [sym]

    if sentiment:
        conditions.append(f"sentiment = {ph}")
        params.append(sentiment)
    if cursor:
        conditions.append(f"published_at < {ph}")
        params.append(cursor)

    where = "WHERE " + " AND ".join(conditions)
    params.append(limit)

    rows = query(f"""
        SELECT id, symbol, body, sentiment, likes, username, published_at
        FROM posts
        {where}
        ORDER BY published_at DESC
        LIMIT {ph}
    """, tuple(params))

    next_cursor = rows[-1]["published_at"] if len(rows) == limit else None

    return {
        "symbol": sym,
        "count": len(rows),
        "next_cursor": next_cursor,
        "data": rows,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Legacy endpoints (保留向后兼容)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/posts", tags=["Legacy"])
def get_posts(
    symbol:    Optional[str] = Query(None),
    source:    Optional[str] = Query(None),
    sentiment: Optional[str] = Query(None),
    limit:     int           = Query(50, ge=1, le=500),
    offset:    int           = Query(0, ge=0),
):
    conn = get_conn()
    pg = _is_pg(conn)
    conn.close()
    ph = "%s" if pg else "?"

    conditions, params = [], []
    if symbol:
        conditions.append(f"symbol = {ph}")
        params.append(symbol.upper())
    if source:
        conditions.append(f"source = {ph}")
        params.append(source)
    if sentiment:
        conditions.append(f"sentiment = {ph}")
        params.append(sentiment)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]

    rows = query(
        f"SELECT * FROM posts {where} ORDER BY published_at DESC LIMIT {ph} OFFSET {ph}",
        tuple(params),
    )
    return {"total": len(rows), "offset": offset, "data": rows}


@app.get("/api/trending", tags=["Legacy"])
def get_trending(days: int = Query(30, ge=1, le=90), limit: int = Query(25, ge=1, le=100)):
    conn = get_conn()
    pg = _is_pg(conn)
    conn.close()
    ph = "%s" if pg else "?"

    if pg:
        since = f"NOW() - INTERVAL '{days} days'"
    else:
        since = f"datetime('now', '-{days} days')"

    rows = query(f"""
        SELECT p.symbol,
               COALESCE(s.sector, '') AS sector,
               COUNT(*) AS mentions,
               SUM(CASE WHEN p.sentiment='Bullish' THEN 1 ELSE 0 END) AS bullish,
               SUM(CASE WHEN p.sentiment='Bearish' THEN 1 ELSE 0 END) AS bearish,
               ROUND(COUNT(*) * 1.0 / {ph}, 1) AS daily_avg
        FROM posts p
        LEFT JOIN symbols s ON p.symbol = s.symbol
        WHERE p.published_at >= {since}
        GROUP BY p.symbol, s.sector
        ORDER BY mentions DESC
        LIMIT {ph}
    """, (days, limit))
    return {"days": days, "total": len(rows), "data": rows}


@app.get("/api/stats", tags=["Legacy"])
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

    return {
        "overview":     stats,
        "by_symbol":    by_symbol,
        "by_sentiment": by_sentiment,
    }
