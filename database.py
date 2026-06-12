import sqlite3
from datetime import datetime, timezone
from config import DB_FILE


def get_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_FILE)


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id           TEXT PRIMARY KEY,
            symbol       TEXT NOT NULL,
            source       TEXT NOT NULL,
            body         TEXT NOT NULL,
            sentiment    TEXT DEFAULT '',
            likes        INTEGER DEFAULT 0,
            username     TEXT DEFAULT '',
            published_at TEXT NOT NULL,
            collected_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS symbols (
            symbol   TEXT PRIMARY KEY,
            sector   TEXT DEFAULT '',
            industry TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol ON posts(symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_published ON posts(published_at)")
    conn.commit()


def save_post(conn: sqlite3.Connection, post_id: str, symbol: str, source: str,
              body: str, sentiment: str, likes: int, username: str,
              published_at: str) -> bool:
    conn.execute("""
        INSERT OR IGNORE INTO posts
          (id, symbol, source, body, sentiment, likes, username, published_at, collected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        post_id, symbol, source, body, sentiment, likes, username,
        published_at,
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    return conn.execute("SELECT changes()").fetchone()[0] > 0


def total_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
