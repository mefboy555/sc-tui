"""Миграция со старых JSON-файлов на SQLite. Запуск: python -m scplay.migrate"""

import json
import sys
from pathlib import Path

from . import db, users
from .config import CONFIG_DIR
from .playlists import PlaylistManager as NewPM


OLD_DIR = Path.home() / ".scplayer"


def migrate():
    db.init_db()
    users.ensure_default_user()

    # читаем старый users.json
    old_users_path = OLD_DIR / "users.json"
    if not old_users_path.exists():
        print("⚠️ Старых данных не найдено, нечего мигрировать")
        return

    old_users = json.loads(old_users_path.read_text())
    print(f"📦 Найдено {len(old_users)} старых пользователей")

    for old_u in old_users:
        username = old_u["username"]
        if users.find_user(username):
            print(f"  ⏭️  {username} уже существует — пропускаю")
            continue
        # пересоздаём с тем же хешем
        with db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, salt, created_at) "
                "VALUES (?, ?, ?, ?)",
                (username, old_u["password_hash"], old_u["salt"], old_u.get("created", 0)),
            )
            user_id = cur.lastrowid
            conn.execute("INSERT INTO settings (user_id) VALUES (?)", (user_id,))
        print(f"  ✅ {username} -> id={user_id}")

        # settings
        old_cfg = CONFIG_DIR / "users" / old_u["id"] / "settings.json"
        if old_cfg.exists():
            try:
                s = json.loads(old_cfg.read_text())
                with db.transaction() as conn:
                    conn.execute(
                        "UPDATE settings SET volume=?, repeat_mode=? WHERE user_id=?",
                        (int(s.get("volume", 100)),
                         s.get("repeat", "off"),
                         user_id),
                    )
            except Exception as e:
                print(f"    ⚠️ settings: {e}")

        # history
        old_hist = CONFIG_DIR / "users" / old_u["id"] / "history.json"
        if old_hist.exists():
            try:
                items = json.loads(old_hist.read_text())
                with db.transaction() as conn:
                    for h in reversed(items):   # чтобы порядок сохранился
                        conn.execute(
                            "INSERT OR IGNORE INTO history "
                            "(user_id, url, title, uploader, duration, played_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (user_id, h.get("url"), h.get("title", "?"),
                             h.get("uploader", "?"), int(h.get("duration", 0)),
                             int(h.get("played_at") or __import__("time").time())),
                        )
                print(f"    📜 history: {len(items)} записей")
            except Exception as e:
                print(f"    ⚠️ history: {e}")

        # playlists
        old_pl_dir = CONFIG_DIR / "users" / old_u["id"] / "playlists"
        if old_pl_dir.exists():
            pm = NewPM(user_id)
            for p in old_pl_dir.glob("*.json"):
                try:
                    data = json.loads(p.read_text())
                    name = data.get("name", p.stem)
                    if pm.create(name):
                        from .soundcloud import Track
                        for t in data.get("tracks", []):
                            pm.add(name, Track.from_dict(t))
                        print(f"    🎧 playlist: {name}")
                except Exception as e:
                    print(f"    ⚠️ playlist {p.name}: {e}")

    print("✅ Миграция завершена")


if __name__ == "__main__":
    migrate()
