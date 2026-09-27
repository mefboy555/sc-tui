"""
Настройки и история плеера.

~/.config/scplayer/config.json  — настройки (громкость, хоткеи, лимиты)
~/.config/scplayer/history.json — история проигранных треков
"""

import json
import os
import shutil
from copy import deepcopy
from pathlib import Path

# XDG: уважаем XDG_CONFIG_HOME, если задан
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / "scplayer"
CONFIG_PATH = CONFIG_DIR / "config.json"
HISTORY_PATH = CONFIG_DIR / "history.json"

# Старое расположение (для миграции)
OLD_DIR = Path.home() / ".scplayer"

DEFAULT_CONFIG = {
    "volume": 100,        # текущая громкость (перезаписывается плеером)
    "volume_step": 5,     # шаг изменения громкости
    "max_volume": 150,    # потолок громкости (mpv умеет до 150)
    "seek_step": 10,      # шаг перемотки в секундах
    "search_limit": 20,   # сколько результатов тянуть из поиска
    "per_page": 5,        # треков на страницу в меню
    "max_history": 50,    # максимум записей в истории
    "keys": {
        "volume_up":    ["+", "=", "up"],
        "volume_down":  ["-", "_", "down"],
        "pause":        [" ", "p"],
        "mute":         ["m"],
        "seek_forward": ["right"],
        "seek_back":    ["left"],
        "next_track":   [">", "n"],
        "prev_track":   ["<", "b"],
        "quit":         ["q"],
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Рекурсивно накладывает пользовательский конфиг на дефолты."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


class Config:
    def __init__(self) -> None:
        self.data: dict = deepcopy(DEFAULT_CONFIG)
        self.history: list[dict] = []
        self._migrate_old()
        self.load()

    # ---------- загрузка ----------

    def load(self) -> None:
        if CONFIG_PATH.exists():
            try:
                user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                _deep_merge(self.data, user)
            except (json.JSONDecodeError, OSError) as e:
                print(f"⚠️ Конфиг повреждён, использую дефолты: {e}")
        if HISTORY_PATH.exists():
            try:
                data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
                raw = [h for h in data if isinstance(h, dict)]
                # Чистим "NA — NA" из истории
                self.history = [
                    h for h in raw
                    if (h.get("title", "") not in ("NA", ""))
                    and (h.get("uploader", "") not in ("NA", ""))
                ]
            except (json.JSONDecodeError, OSError):
                self.history = []
                
    def _migrate_old(self) -> None:
        """Переносит данные со старого ~/.scplayer, если он есть."""
        old_cfg = OLD_DIR / "config.json"
        if not old_cfg.exists():
            return
        try:
            old = json.loads(old_cfg.read_text(encoding="utf-8"))
            self.data["volume"] = int(old.get("volume", self.data["volume"]))
            if not self.history:
                self.history = [h for h in old.get("history", []) if isinstance(h, dict)]
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            self.save_config()
            self.save_history()
            shutil.move(str(old_cfg), str(OLD_DIR / "config.json.migrated"))
            print(f"📦 Данные перенесены: {OLD_DIR} → {CONFIG_DIR}")
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    # ---------- сохранение ----------

    def _write(self, path: Path, payload) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            print(f"⚠️ Не удалось сохранить {path.name}: {e}")

    def save_config(self) -> None:
        self._write(CONFIG_PATH, self.data)

    def save_history(self) -> None:
        self._write(HISTORY_PATH, self.history[: self.get("max_history", 50)])

    # ---------- доступ к настройкам ----------

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

    # ---------- история ----------

    def add_track(self, track) -> None:
        """Добавляет трек в начало истории, убирая дубликаты по url."""
        entry = track.to_dict() if hasattr(track, "to_dict") else dict(track)
        # Не сохраняем placeholder-треки
        if entry.get("title") in ("NA", "", "Неизвестный трек"):
            return
        self.history = [h for h in self.history if h.get("url") != entry.get("url")]
        self.history.insert(0, entry)
        self.history = self.history[: self.get("max_history", 50)]
        self.save_history()
