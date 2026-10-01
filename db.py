"""SQLite database layer с thread-local connections и WAL mode."""

import sqlite3
import threading
import time
from contextlib import contextmanager

from .config import CONFIG_DIR

DB_PATH = CONFIG_DIR / "scplay.db"
_local = threading.local()
_init_lock = threading.Lock()


def get_conn() -> sqlite3.Connection:
    """Thread-local connection для SQLite."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")      # конкурентные чтения
        conn.execute("PRAGMA synchronous=NORMAL")     # быстрее запись
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA cache_size=-8000")       # 8MB кеш
        _local.conn = conn
    return conn


@contextmanager
def transaction():
    """Контекст транзакции с авто-rollback при исключении."""
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except:
        conn.rollback()
        raise


def init_db():
    """Создаёт таблицы, если их нет. Идемпотентно."""
    with _init_lock:
        conn = get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                volume INTEGER NOT NULL DEFAULT 100,
                repeat_mode TEXT NOT NULL DEFAULT 'off'
            );

            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                uploader TEXT NOT NULL,
                duration INTEGER NOT NULL DEFAULT 0,
                played_at INTEGER NOT NULL,
                UNIQUE(user_id, url)
            );
            CREATE INDEX IF NOT EXISTS idx_history_user_played
                ON history(user_id, played_at DESC);

            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(user_id, name)
            );

            CREATE TABLE IF NOT EXISTS playlist_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                uploader TEXT NOT NULL,
                duration INTEGER NOT NULL DEFAULT 0,
                added_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_playlist_tracks_playlist
                ON playlist_tracks(playlist_id, position);

            CREATE TABLE IF NOT EXISTS client_id_cache (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                client_id TEXT NOT NULL,
                fetched_at INTEGER NOT NULL
            );
        """)


# ---------- helpers ----------

def row_to_dict(row) -> dict | None:
    return dict(row) if row else None


def rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]
