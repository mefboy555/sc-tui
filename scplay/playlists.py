"""Плейлисты пользователя в SQLite."""

import time

from . import db
from .soundcloud import Track


class PlaylistManager:
    def __init__(self, user_id: int):
        self.user_id = int(user_id)

    def names(self) -> list[tuple[str, int]]:
        rows = db.get_conn().execute(
            "SELECT p.name, COUNT(pt.id) AS cnt "
            "FROM playlists p "
            "LEFT JOIN playlist_tracks pt ON pt.playlist_id = p.id "
            "WHERE p.user_id = ? "
            "GROUP BY p.id "
            "ORDER BY p.name",
            (self.user_id,),
        ).fetchall()
        return [(r["name"], r["cnt"]) for r in rows]

    def _playlist_id(self, name: str) -> int | None:
        row = db.get_conn().execute(
            "SELECT id FROM playlists WHERE user_id = ? AND name = ?",
            (self.user_id, name),
        ).fetchone()
        return row["id"] if row else None

    def exists(self, name: str) -> bool:
        return self._playlist_id(name) is not None

    def load(self, name: str) -> list[Track]:
        pid = self._playlist_id(name)
        if pid is None:
            return []
        rows = db.get_conn().execute(
            "SELECT title, uploader, url, duration "
            "FROM playlist_tracks WHERE playlist_id = ? ORDER BY position",
            (pid,),
        ).fetchall()
        return [
            Track(title=r["title"], uploader=r["uploader"],
                  url=r["url"], duration=int(r["duration"] or 0))
            for r in rows
        ]

    def create(self, name: str) -> bool:
        if not name or self.exists(name):
            return False
        try:
            with db.transaction() as conn:
                conn.execute(
                    "INSERT INTO playlists (user_id, name, created_at) VALUES (?, ?, ?)",
                    (self.user_id, name, int(time.time())),
                )
            return True
        except Exception:
            return False

    def delete(self, name: str) -> None:
        pid = self._playlist_id(name)
        if pid is None:
            return
        with db.transaction() as conn:
            conn.execute("DELETE FROM playlists WHERE id = ?", (pid,))

    def add(self, name: str, track: Track) -> bool:
        pid = self._playlist_id(name)
        if pid is None:
            return False
        # проверка дубликата
        row = db.get_conn().execute(
            "SELECT 1 FROM playlist_tracks WHERE playlist_id = ? AND url = ? LIMIT 1",
            (pid, track.url),
        ).fetchone()
        if row:
            return False
        # позиция = MAX + 1
        row = db.get_conn().execute(
            "SELECT COALESCE(MAX(position), 0) + 1 AS p FROM playlist_tracks "
            "WHERE playlist_id = ?", (pid,),
        ).fetchone()
        pos = row["p"]
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO playlist_tracks "
                "(playlist_id, position, url, title, uploader, duration, added_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pid, pos, track.url, track.title, track.uploader,
                 int(track.duration or 0), int(time.time())),
            )
        return True

    def remove(self, name: str, index: int) -> None:
        pid = self._playlist_id(name)
        if pid is None:
            return
        rows = db.get_conn().execute(
            "SELECT id FROM playlist_tracks WHERE playlist_id = ? ORDER BY position",
            (pid,),
        ).fetchall()
        if 0 <= index < len(rows):
            with db.transaction() as conn:
                conn.execute(
                    "DELETE FROM playlist_tracks WHERE id = ?", (rows[index]["id"],)
                )
