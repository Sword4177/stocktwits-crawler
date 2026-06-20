import sqlite3
from datetime import datetime, timezone
from config import DB_FILE, DATABASE_URL


def get_conn():
    if DATABASE_URL:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    return sqlite3.connect(DB_FILE)


def _is_pg(conn) -> bool:
    try:
        import psycopg2
        return isinstance(conn, psycopg2.extensions.connection)
    except ImportError:
        return False


def init_db(conn) -> None:
    pg = _is_pg(conn)
    cur = conn.cursor()

    if pg:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id                   TEXT PRIMARY KEY,
                symbol               TEXT NOT NULL,
                source               TEXT NOT NULL,
                body                 TEXT NOT NULL,
                sentiment            TEXT DEFAULT '',
                sentiment_confidence REAL DEFAULT 0.0,
                likes                INTEGER DEFAULT 0,
                username             TEXT DEFAULT '',
                published_at         TIMESTAMPTZ NOT NULL,
                collected_at         TIMESTAMPTZ NOT NULL
            )
        """)
        cur.execute("""
            ALTER TABLE posts ADD COLUMN IF NOT EXISTS
              sentiment_confidence REAL DEFAULT 0.0
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS symbols (
                symbol     TEXT PRIMARY KEY,
                sector     TEXT DEFAULT '',
                industry   TEXT DEFAULT '',
                updated_at TIMESTAMPTZ NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                symbol     TEXT NOT NULL,
                date       DATE NOT NULL,
                open       REAL,
                high       REAL,
                low        REAL,
                close      REAL,
                volume     BIGINT,
                pct_change REAL,
                PRIMARY KEY (symbol, date)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticker_signals (
                id              SERIAL PRIMARY KEY,
                symbol          TEXT NOT NULL,
                ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                time_window     TEXT NOT NULL,
                mentions        INTEGER DEFAULT 0,
                bullish_count   INTEGER DEFAULT 0,
                bearish_count   INTEGER DEFAULT 0,
                sentiment_score REAL DEFAULT 0,
                buzz_baseline   REAL DEFAULT 0,
                buzz_ratio      REAL DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS signal_alerts (
                id          SERIAL PRIMARY KEY,
                symbol      TEXT NOT NULL,
                alert_type  TEXT NOT NULL,
                triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                detail      JSONB
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_symbol ON posts(symbol)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_posts_published ON posts(published_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ticker_signals_ts ON ticker_signals(ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_alerts_triggered ON signal_alerts(triggered_at)")
    else:
        cur.execute("""
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS symbols (
                symbol   TEXT PRIMARY KEY,
                sector   TEXT DEFAULT '',
                industry TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_symbol ON posts(symbol)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_published ON posts(published_at)")

    conn.commit()
    cur.close()


def save_post(conn, post_id: str, symbol: str, source: str,
              body: str, sentiment: str, likes: int, username: str,
              published_at: str) -> bool:
    pg = _is_pg(conn)
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    confidence = 1.0 if sentiment in ("Bullish", "Bearish") else 0.0
    if pg:
        cur.execute("""
            INSERT INTO posts (id, symbol, source, body, sentiment, sentiment_confidence,
                               likes, username, published_at, collected_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        """, (post_id, symbol, source, body, sentiment, confidence, likes, username, published_at, now))
    else:
        cur.execute("""
            INSERT OR IGNORE INTO posts
              (id, symbol, source, body, sentiment, sentiment_confidence,
               likes, username, published_at, collected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (post_id, symbol, source, body, sentiment, confidence, likes, username, published_at, now))
    conn.commit()
    changed = cur.rowcount > 0
    cur.close()
    return changed


def total_count(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM posts")
    result = cur.fetchone()[0]
    cur.close()
    return result
