"""
tag_sectors.py — 用 yfinance 自动查询所有股票的板块，缓存到 symbols 表
"""
import time
import sqlite3
from datetime import datetime, timezone
import yfinance as yf
from database import get_conn, init_db

SECTOR_ZH = {
    "Technology":            "科技",
    "Financial Services":    "金融",
    "Energy":                "能源",
    "Healthcare":            "医疗",
    "Consumer Cyclical":     "消费",
    "Consumer Defensive":    "消费",
    "Communication Services":"通信",
    "Industrials":           "工业",
    "Basic Materials":       "原材料",
    "Real Estate":           "地产",
    "Utilities":             "公用事业",
    "Cryptocurrency":        "加密货币",
}


def fetch_sector(symbol: str) -> tuple[str, str]:
    try:
        info = yf.Ticker(symbol).info
        sector_en = info.get("sector", "")
        industry  = info.get("industry", "")
        sector_zh = SECTOR_ZH.get(sector_en, sector_en)
        return sector_zh, industry
    except Exception as e:
        print(f"  ✗ {symbol}: {e}")
        return "", ""


def tag_all():
    conn = get_conn()
    init_db(conn)

    # 取出所有出现过的股票
    symbols = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM posts ORDER BY symbol"
    ).fetchall()]

    # 只查还没缓存的
    cached = {r[0] for r in conn.execute("SELECT symbol FROM symbols").fetchall()}
    todo = [s for s in symbols if s not in cached]

    print(f"共 {len(symbols)} 个股票，已缓存 {len(cached)} 个，待查询 {len(todo)} 个\n")

    for i, sym in enumerate(todo, 1):
        sector, industry = fetch_sector(sym)
        conn.execute("""
            INSERT OR REPLACE INTO symbols (symbol, sector, industry, updated_at)
            VALUES (?, ?, ?, ?)
        """, (sym, sector, industry, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        print(f"  [{i}/{len(todo)}] {sym:10} → {sector} / {industry}")
        time.sleep(0.5)

    conn.close()
    print("\n✓ 完成")


if __name__ == "__main__":
    tag_all()
