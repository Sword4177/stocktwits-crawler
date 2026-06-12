from pathlib import Path

BASE_DIR        = Path(__file__).parent
DB_FILE         = str(BASE_DIR / "stocktwits.db")
POLL_INTERVAL   = 300        # 每5分钟抓一次
TRENDING_LIMIT  = 30         # 抓trending前30条
SYMBOL_LIMIT    = 30         # 每个symbol抓最新30条
