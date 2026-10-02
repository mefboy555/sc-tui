#SQLite database layer: thread-local connections, WAL

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / "scplayer"
DB_PATH = CONFIG_DIR / "scplay.db"

_local = threading.local()
_init_lock = threading.Lock()

SCHEMA = """
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
        repeat_mode TEXT NOT NULL DEFAULT 'off',
        keys_json TEXT
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
"""


def _init_schema(conn: sqlite3.Connection) -> None:
    """Создаёт таблицы (идемпотентно) + миграции для старых БД."""
    with _init_lock:
        conn.executescript(SCHEMA)
        try:
            conn.execute("ALTER TABLE settings ADD COLUMN keys_json TEXT")
        except sqlite3.OperationalError:
            pass  


def get_conn() -> sqlite3.Connection:
    """Thread-local connection. Сам создаёт папку и схему при первом обращении."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA cache_size=-8000")
        _local.conn = conn
        _init_schema(conn)   # схема накатывается сама, откуда бы ни зашли
    return conn


def init_db() -> None:
#Явный вызов для совместимости (сервер/миграция)
    get_conn()


@contextmanager
def transaction():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def row_to_dict(row) -> dict | None:
    return dict(row) if row else None


def rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]
