"""
backfill_signals.py — 回溯历史 ticker_signals 快照（每小时精度）
只处理 symbols 表中已登记的 ticker，约 138 万行
用法：python backfill_signals.py
"""
import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

WINDOWS = [("1h", 1), ("4h", 4), ("24h", 24)]
COMMIT_EVERY = 100  # 每 100 小时提交一次，保证断点续跑


def run():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    # 已登记的 ticker
    cur.execute("SELECT symbol FROM symbols")
    symbols = [r[0] for r in cur.fetchall()]
    print(f"tracked symbols: {len(symbols)}")

    # 只回溯最近 30 天
    cur.execute("SELECT MAX(published_at) FROM posts")
    latest = cur.fetchone()[0]
    from datetime import timezone
    end   = latest.replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=30)

    # 断点续跑：只看1天前以上的数据，避免把实时快照误判为回溯进度
    cur.execute("""
        SELECT MAX(ts) FROM ticker_signals
        WHERE ts < NOW() - INTERVAL '1 day'
    """)
    last_done = cur.fetchone()[0]
    if last_done:
        resume_from = last_done + timedelta(hours=1)
        if resume_from > start:
            start = resume_from
            print(f"resuming from {start}")

    total_hours = max(int((end - start).total_seconds() / 3600), 1)
    print(f"backfilling {total_hours} hours  ({start} → {end})")

    rows_inserted = 0
    hours_done = 0
    ts = start

    while ts <= end:
        batch: list = []
        for window, h in WINDOWS:
            window_start = ts - timedelta(hours=h)
            cur.execute("""
                SELECT p.symbol,
                       COUNT(*) AS mentions,
                       SUM(CASE WHEN sentiment='Bullish' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN sentiment='Bearish' THEN 1 ELSE 0 END),
                       ROUND(
                           (SUM(CASE WHEN sentiment='Bullish' THEN 1.0 ELSE 0 END) -
                            SUM(CASE WHEN sentiment='Bearish' THEN 1.0 ELSE 0 END))
                           / NULLIF(COUNT(*), 0), 4
                       )
                FROM posts p
                WHERE p.published_at >= %s AND p.published_at < %s
                  AND p.symbol = ANY(%s)
                GROUP BY p.symbol
                HAVING COUNT(*) > 0
            """, (window_start, ts, symbols))

            for sym, mentions, bullish, bearish, score in cur.fetchall():
                batch.append((sym, ts, window, int(mentions), int(bullish),
                              int(bearish), float(score or 0), 0.0, 0.0))

        if batch:
            psycopg2.extras.execute_values(cur, """
                INSERT INTO ticker_signals
                  (symbol, ts, time_window, mentions, bullish_count, bearish_count,
                   sentiment_score, buzz_baseline, buzz_ratio)
                VALUES %s
            """, batch, page_size=1000)
            rows_inserted += len(batch)

        hours_done += 1
        if hours_done % COMMIT_EVERY == 0:
            conn.commit()
            pct = hours_done / total_hours * 100
            print(f"  {hours_done}/{total_hours} ({pct:.1f}%)  rows: {rows_inserted:,}")

        ts += timedelta(hours=1)

    conn.commit()
    print(f"\ndone. total rows inserted: {rows_inserted:,}")
    conn.close()


if __name__ == "__main__":
    run()
