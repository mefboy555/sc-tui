"""Локальные плейлисты: ~/.config/scplayer/playlists/<имя>.json"""

import json
import re
from pathlib import Path

from .config import CONFIG_DIR
from .soundcloud import Track

PLAYLIST_DIR = CONFIG_DIR / "playlists"


def _safe_name(name: str) -> str:
    """Имя файла из произвольного имени плейлиста."""
    return re.sub(r"[^\w\-]+", "_", name.strip()).strip("_") or "playlist"


class PlaylistManager:
    def __init__(self):
        self.dir = PLAYLIST_DIR

    def _path(self, name: str) -> Path:
        return self.dir / (_safe_name(name) + ".json")

    def exists(self, name: str) -> bool:
        return self._path(name).exists()

    def names(self) -> list[tuple[str, int]]:
        """Список (имя, кол-во треков)."""
        if not self.dir.exists():
            return []
        result = []
        for p in sorted(self.dir.glob("*.json")):
            result.append((p.stem, len(self.load(p.stem))))
        return result

    def load(self, name: str) -> list[Track]:
        path = self._path(name)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [Track.from_dict(t) for t in data.get("tracks", [])]
        except (json.JSONDecodeError, OSError):
            return []

    def save(self, name: str, tracks: list[Track]) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._path(name).write_text(
                json.dumps(
                    {"name": name, "tracks": [t.to_dict() for t in tracks]},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as e:
            print(f"⚠️ Не удалось сохранить плейлист: {e}")

    def create(self, name: str) -> bool:
        if self.exists(name):
            print(f"⚠️ Плейлист \"{name}\" уже существует.")
            return False
        self.save(name, [])
        return True

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)

    def add(self, name: str, track: Track) -> None:
        tracks = self.load(name)
        if any(t.url == track.url for t in tracks):
            print("⚠️ Трек уже есть в плейлисте.")
            return
        tracks.append(track)
        self.save(name, tracks)

    def remove(self, name: str, index: int) -> None:
        tracks = self.load(name)
        if 0 <= index < len(tracks):
            tracks.pop(index)
            self.save(name, tracks)
