"""Per-user настройки: громкость, repeat. Хранится в SQLite."""

import os
from pathlib import Path

from . import db


CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / "scplayer"


class Config:
    """Тонкий враппер над таблицей settings."""

    def __init__(self, user_id: int):
        self.user_id = int(user_id)
        self.volume: int = 100
        self.repeat: str = "off"
        self.history: list[dict] = []
        self._load()

    def _load(self) -> None:
        row = db.get_conn().execute(
            "SELECT volume, repeat_mode FROM settings WHERE user_id = ?",
            (self.user_id,)
        ).fetchone()
        if row:
            self.volume = row["volume"]
            self.repeat = row["repeat_mode"]
        else:
            # юзер мог быть создан без settings (миграция)
            db.get_conn().execute(
                "INSERT OR IGNORE INTO settings (user_id) VALUES (?)",
                (self.user_id,)
            )
            db.get_conn().commit()

        self.history = db.rows_to_list(db.get_conn().execute(
            "SELECT url, title, uploader, duration, played_at "
            "FROM history WHERE user_id = ? ORDER BY played_at DESC LIMIT 50",
            (self.user_id,),
        ).fetchall())

    def save_config(self) -> None:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO settings (user_id, volume, repeat_mode) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET volume=excluded.volume, repeat_mode=excluded.repeat_mode",
                (self.user_id, int(self.volume), self.repeat),
            )

    def add_track(self, track) -> None:
        """Добавляет трек в историю (INSERT OR REPLACE)."""
        entry = track.to_dict() if hasattr(track, "to_dict") else dict(track)
        title = entry.get("title") or "Неизвестный трек"
        if title in ("NA", "", "Неизвестный трек"):
            return
        uploader = entry.get("uploader") or "Неизвестный исполнитель"
        url = entry.get("url") or ""
        if not url:
            return
        duration = int(entry.get("duration") or 0)

        with db.transaction() as conn:
            # удаляем старую запись с таким url, чтобы поднять в начало
            conn.execute(
                "DELETE FROM history WHERE user_id = ? AND url = ?",
                (self.user_id, url),
            )
            conn.execute(
                "INSERT INTO history (user_id, url, title, uploader, duration, played_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (self.user_id, url, title, uploader, duration,
                 int(__import__("time").time())),
            )
            # ограничиваем историю 50 записями
            conn.execute(
                "DELETE FROM history WHERE user_id = ? AND id NOT IN ("
                "  SELECT id FROM history WHERE user_id = ? "
                "  ORDER BY played_at DESC LIMIT 50"
                ")",
                (self.user_id, self.user_id),
            )

    def get(self, key: str, default=None):
        return {"volume": self.volume, "repeat": self.repeat}.get(key, default)
