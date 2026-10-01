"""Per-user настройки: громкость, repeat, хоткеи. Дефолты из кода + SQLite."""

import json
import os
import time
from copy import deepcopy
from pathlib import Path

from . import db

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / "scplayer"

REPEAT_MODES = ("off", "all", "one")

DEFAULT_SETTINGS = {
    "volume": 100,
    "volume_step": 5,
    "max_volume": 150,
    "seek_step": 10,
    "search_limit": 20,
    "per_page": 5,
    "max_history": 50,
    "repeat": "off",
    "keys": {
        "volume_up":    ["+", "=", "up"],
        "volume_down":  ["-", "_", "down"],
        "pause":        [" ", "p"],
        "mute":         ["m"],
        "seek_forward": ["right"],
        "seek_back":    ["left"],
        "next_track":   [">", "n"],
        "prev_track":   ["<", "b"],
        "repeat":       ["r"],
        "quit":         ["q"],
    },
}


class Config:
    def __init__(self, user_id: int):
        self.user_id = int(user_id)
        self.data: dict = deepcopy(DEFAULT_SETTINGS)
        self.history: list[dict] = []
        self._load()

    def _load(self) -> None:
        row = db.get_conn().execute(
            "SELECT volume, repeat_mode, keys_json FROM settings WHERE user_id = ?",
            (self.user_id,),
        ).fetchone()
        if row:
            self.data["volume"] = row["volume"]
            self.data["repeat"] = row["repeat_mode"]
            if row["keys_json"]:
                try:
                    user_keys = json.loads(row["keys_json"])
                    if isinstance(user_keys, dict):
                        self.data["keys"].update(user_keys)
                except json.JSONDecodeError:
                    pass
        else:
            db.get_conn().execute(
                "INSERT OR IGNORE INTO settings (user_id) VALUES (?)",
                (self.user_id,),
            )
            db.get_conn().commit()

        self.history = db.rows_to_list(db.get_conn().execute(
            "SELECT url, title, uploader, duration, played_at "
            "FROM history WHERE user_id = ? ORDER BY played_at DESC LIMIT 50",
            (self.user_id,),
        ).fetchall())

    def save_config(self) -> None:
        """Сохраняет volume/repeat всегда; хоткеи — только отличающиеся от дефолта."""
        diff_keys = {
            k: v for k, v in self.data["keys"].items()
            if DEFAULT_SETTINGS["keys"].get(k) != v
        }
        keys_json = json.dumps(diff_keys, ensure_ascii=False) if diff_keys else None
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO settings (user_id, volume, repeat_mode, keys_json) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET volume=excluded.volume, "
                "repeat_mode=excluded.repeat_mode, keys_json=excluded.keys_json",
                (self.user_id, int(self.data["volume"]),
                 self.data["repeat"], keys_json),
            )

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def keys_for(self, action: str) -> list[str]:
        """Список клавиш действия (для строки подсказки)."""
        return self.data.get("keys", {}).get(action, [])

    def action_for(self, key: str) -> str | None:
        """Какому действию соответствует нажатая клавиша."""
        for action, keys in self.data.get("keys", {}).items():
            if key in keys:
                return action
        return None

    def cycle_repeat(self) -> str:
        """Переключает off → all → one → off и сохраняет."""
        cur = self.data.get("repeat", "off")
        idx = REPEAT_MODES.index(cur) if cur in REPEAT_MODES else 0
        self.data["repeat"] = REPEAT_MODES[(idx + 1) % len(REPEAT_MODES)]
        self.save_config()
        return self.data["repeat"]

    def add_track(self, track) -> None:
        entry = track.to_dict() if hasattr(track, "to_dict") else dict(track)
        title = entry.get("title") or "Неизвестный трек"
        if title in ("NA", "", "Неизвестный трек"):
            return
        uploader = entry.get("uploader") or "Неизвестный исполнитель"
        url = entry.get("url") or ""
        if not url:
            return
        with db.transaction() as conn:
            conn.execute(
                "DELETE FROM history WHERE user_id = ? AND url = ?",
                (self.user_id, url),
            )
            conn.execute(
                "INSERT INTO history (user_id, url, title, uploader, duration, played_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (self.user_id, url, title, uploader,
                 int(entry.get("duration") or 0), int(time.time())),
            )
            conn.execute(
                "DELETE FROM history WHERE user_id = ? AND id NOT IN ("
                "  SELECT id FROM history WHERE user_id = ? "
                "  ORDER BY played_at DESC LIMIT 50)",
                (self.user_id, self.user_id),
            )
