"""fetch_prices.py — 用 yfinance 抓取追踪标的近35天行情，写入 prices 表"""
import sqlite3
import yaml
import os
import yfinance as yf
from config import DB_FILE


def init_prices_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            symbol     TEXT NOT NULL,
            date       TEXT NOT NULL,
            open       REAL,
            close      REAL,
            pct_change REAL,
            volume     INTEGER,
            PRIMARY KEY (symbol, date)
        )
    """)
    conn.commit()


def load_symbols():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "symbols.yaml")
    with open(path) as f:
        return yaml.safe_load(f)["symbols"]


def fetch_prices(symbols=None, period="35d"):
    conn = sqlite3.connect(DB_FILE)
    init_prices_table(conn)

    if symbols is None:
        symbols = load_symbols()

    ok, fail = 0, 0
    for sym in symbols:
        try:
            hist = yf.Ticker(sym).history(period=period)
            if hist.empty:
                print(f"  – {sym}: 无数据")
                continue
            for dt, row in hist.iterrows():
                o = float(row.get("Open") or 0)
                c = float(row.get("Close") or 0)
                pct = (c - o) / o if o else 0.0
                conn.execute("""
                    INSERT OR REPLACE INTO prices (symbol, date, open, close, pct_change, volume)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (sym, dt.strftime("%Y-%m-%d"),
                      round(o, 4), round(c, 4), round(pct, 6),
                      int(row.get("Volume") or 0)))
            ok += 1
            print(f"  ✓ {sym}")
        except Exception as e:
            fail += 1
            print(f"  ✗ {sym}: {e}")

    conn.commit()
    conn.close()
    print(f"\n完成：{ok} 成功，{fail} 失败")


if __name__ == "__main__":
    print("正在抓取行情数据（最近35天）…")
    fetch_prices()
