"""fetch_prices.py — 用 yfinance 抓取追踪标的近35天行情，写入 prices 表"""
import os
import psycopg2
import psycopg2.extras
import yfinance as yf
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
DAYS = 35


def fetch_and_store(symbols: list, conn) -> None:
    cur = conn.cursor()
    print(f"downloading {len(symbols)} symbols ({DAYS}d)...")

    raw = yf.download(symbols, period=f"{DAYS}d", auto_adjust=True,
                      progress=False, group_by="ticker")

    rows = []
    failed = []

    for sym in symbols:
        try:
            df = raw[sym] if len(symbols) > 1 else raw
            if df is None or df.empty:
                failed.append(sym)
                continue

            df = df.dropna(subset=["Close"])
            df["pct_change"] = df["Close"].pct_change()  # 日涨跌幅

            for date, row in df.iterrows():
                rows.append((
                    sym,
                    date.date(),
                    float(row["Open"])       if not pd.isna(row.get("Open"))       else None,
                    float(row["High"])       if not pd.isna(row.get("High"))       else None,
                    float(row["Low"])        if not pd.isna(row.get("Low"))        else None,
                    float(row["Close"]),
                    int(row["Volume"])       if not pd.isna(row.get("Volume"))     else None,
                    float(row["pct_change"]) if not pd.isna(row["pct_change"])     else None,
                ))
        except Exception as e:
            failed.append(sym)
            print(f"  skip {sym}: {e}")

    if rows:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO prices (symbol, date, open, high, low, close, volume, pct_change)
            VALUES %s
            ON CONFLICT (symbol, date) DO UPDATE SET
                open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                close=EXCLUDED.close, volume=EXCLUDED.volume,
                pct_change=EXCLUDED.pct_change
        """, rows, page_size=500)
        conn.commit()
        print(f"inserted/updated {len(rows)} rows")

    if failed:
        print(f"failed ({len(failed)}): {failed}")


def run():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SELECT symbol FROM symbols")
    symbols = [r[0] for r in cur.fetchall()]
    cur.close()
    fetch_and_store(symbols, conn)
    conn.close()


if __name__ == "__main__":
    run()
