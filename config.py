import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR        = Path(__file__).parent
DB_FILE         = str(BASE_DIR / "stocktwits.db")   # SQLite fallback (local dev)
DATABASE_URL    = os.getenv("DATABASE_URL", "")      # PostgreSQL on Railway
API_KEY         = os.getenv("API_KEY", "")           # X-API-Key auth
POLL_INTERVAL   = 300
TRENDING_LIMIT  = 30
SYMBOL_LIMIT    = 30
