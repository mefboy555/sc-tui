"""Пользователи, сессии, хеши паролей. Всё на SQLite."""

import hashlib
import secrets
import time

from . import db


SESSION_TTL = 30 * 24 * 3600  # 30 дней


# ---------- passwords ----------

def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_bytes(16)
    h = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=2**14, r=8, p=1, dklen=32,
    )
    return h.hex(), salt.hex()


def verify_password(password: str, pw_hash: str, salt: str) -> bool:
    check, _ = hash_password(password, bytes.fromhex(salt))
    return secrets.compare_digest(check, pw_hash)


# ---------- sanitization ----------

def sanitize_username(name: str) -> str:
    import re
    name = (name or "").strip()
    name = re.sub(r"[^\w\-]+", "", name)
    return name[:32]


def sanitize_name(name: str, max_len: int = 80) -> str:
    import re
    name = (name or "").strip()
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    return name[:max_len]


# ---------- users CRUD ----------

def find_user(username: str) -> dict | None:
    row = db.get_conn().execute(
        "SELECT id, username, password_hash, salt, created_at "
        "FROM users WHERE username = ?", (username,)
    ).fetchone()
    return db.row_to_dict(row)


def get_user(user_id: int) -> dict | None:
    row = db.get_conn().execute(
        "SELECT id, username, created_at FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return db.row_to_dict(row)


def create_user(username: str, password: str) -> dict | None:
    """Создаёт пользователя + дефолтные settings. Возвращает None при конфликте."""
    username = sanitize_username(username)
    if not username or len(username) < 3:
        return None
    if len(password) < 4:
        return None
    if find_user(username):
        return None

    pw_hash, salt = hash_password(password)
    now = int(time.time())
    try:
        with db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
                (username, pw_hash, salt, now),
            )
            user_id = cur.lastrowid
            conn.execute(
                "INSERT INTO settings (user_id) VALUES (?)", (user_id,)
            )
        return {"id": user_id, "username": username}
    except Exception:
        return None


def list_users() -> list[dict]:
    return db.rows_to_list(db.get_conn().execute(
        "SELECT id, username FROM users ORDER BY id"
    ).fetchall())


def ensure_default_user() -> dict:
    """Создаёт admin/admin, если нет ни одного пользователя."""
    users = list_users()
    if users:
        return users[0]
    u = create_user("admin", "admin")
    print(f"📦 Создан дефолтный пользователь: admin / admin")
    print(f"   ⚠️  Смени пароль при первом входе!")
    return u


# ---------- sessions ----------

def create_session(user_id: int) -> str:
    """Создаёт сессию и чистит просроченные."""
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at, created_at) "
            "VALUES (?, ?, ?, ?)",
            (token, user_id, now + SESSION_TTL, now),
        )
        # чистим протухшие раз в 100 раз
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
    return token


def get_session(token: str) -> dict | None:
    if not token:
        return None
    row = db.get_conn().execute(
        "SELECT s.user_id, u.username FROM sessions s "
        "JOIN users u ON u.id = s.user_id "
        "WHERE s.token = ? AND s.expires_at > ?",
        (token, int(time.time())),
    ).fetchone()
    return db.row_to_dict(row)


def delete_session(token: str) -> None:
    with db.transaction() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
