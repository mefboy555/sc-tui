"""Логика приложения: меню, поиск, история, плейлисты, очередь."""

from . import player, soundcloud, ui
from .config import Config
from .playlists import PlaylistManager


class App:
    def __init__(self):
        self.cfg = Config()
        self.pm = PlaylistManager()

    def run(self, initial_query: str | None = None) -> None:
        try:
            if initial_query:
                self._find_and_play(initial_query)
            while True:
                action = ui.main_menu(self._last_label())
                if action == "quit":
                    print("👋 До встречи!")
                    break
                if action == "search":
                    query = input("🔍 Запрос или URL плейлиста: ").strip()
                    if query:
                        self._find_and_play(query)
                elif action == "history":
                    self._from_history()
                elif action == "playlists":
                    self._playlists_menu()
        except KeyboardInterrupt:
            print("\n👋 Прервано.")
        except EOFError:
            print()
        finally:
            self.cfg.save_config()

    # ---------- поиск и воспроизведение ----------

    def _fetch(self, query: str) -> list:
        if soundcloud.is_url(query):
            print("⏳ Читаю плейлист/трек по URL...")
            return soundcloud.resolve_url(query)
        print(f"🔍 Ищу: {query}")
        return soundcloud.search(query, limit=int(self.cfg.get("search_limit", 20)))

    def _find_and_play(self, query: str) -> None:
        results = self._fetch(query)
        if not results:
            print("❌ Ничего не найдено.")
            self._wait()
            return
        idx = ui.choose_track(results, self.cfg)
        if idx is not None:
            self._play_queue(results, idx)

    def _from_history(self) -> None:
        if not self.cfg.history:
            print("\n📜 История пуста.")
            self._wait()
            return
        tracks = [soundcloud.Track.from_dict(h) for h in self.cfg.history]
        idx = ui.choose_track(tracks, self.cfg, header="📜 История прослушивания:")
        if idx is not None:
            self._play_queue([tracks[idx]], 0)

    def _play(self, track, pos: int | None = None, total: int | None = None) -> str:
        """
        Готовит и проигрывает один трек.
        Возвращает: 'ended' | 'quit' | 'next' | 'prev' | 'skip'
        """
        if track.is_placeholder():
            print("🔄 Подтягиваю метаданные трека...")
            track = soundcloud.enrich_track(track)

        print("⏳ Получаю ссылку на аудио...")
        stream_url, _ = soundcloud.get_stream_url(track.url)
        if not stream_url:
            print("❌ Не удалось получить стрим, пропускаю.")
            return "skip"

        self.cfg.add_track(track)
        return player.play(stream_url, track.title, self.cfg,
                           queue_pos=pos, queue_len=total)

    def _play_queue(self, tracks: list, start: int) -> None:
        """Очередь с автопереходом и клавишами next/prev."""
        pos = start
        while 0 <= pos < len(tracks):
            track = tracks[pos]
            print(f"\n🎵 Играю ({pos + 1}/{len(tracks)}): {track.label}")
            reason = self._play(track, pos + 1, len(tracks))
            if reason == "quit":
                return
            if reason == "prev":
                pos -= 1
                continue
            pos += 1
            if reason == "ended" and pos < len(tracks):
                print(f"⏭ Дальше: {tracks[pos].label}")
        print("✅ Очередь закончилась.")

    # ---------- локальные плейлисты ----------

    def _playlists_menu(self) -> None:
        while True:
            action, name = ui.playlist_picker(self.pm.names())
            if action == "back":
                return
            if action == "create":
                new_name = input("Имя нового плейлиста: ").strip()
                if new_name and self.pm.create(new_name):
                    print(f"✅ Создан плейлист \"{new_name}\".")
                continue
            if action == "open":
                self._playlist_view(name)

    def _playlist_view(self, name: str) -> None:
        while True:
            tracks = self.pm.load(name)
            action, payload = ui.playlist_view(tracks, self.cfg, name)
            if action == "back":
                return
            if action == "play":
                self._play_queue(tracks, payload)
            elif action == "remove":
                self.pm.remove(name, payload)
                print("🗑 Трек удалён из плейлиста.")
            elif action == "add":
                self._add_to_playlist(name)
            elif action == "delete_playlist":
                confirm = input(f"Удалить плейлист \"{name}\"? [y/N]: ").strip().lower()
                if confirm == "y":
                    self.pm.delete(name)
                    print("🗑 Плейлист удалён.")
                    return

    def _add_to_playlist(self, name: str) -> None:
        query = input("🔍 Поиск трека для добавления (или URL): ").strip()
        if not query:
            return
        results = self._fetch(query)
        if not results:
            print("❌ Ничего не найдено.")
            self._wait()
            return
        idx = ui.choose_track(results, self.cfg, header=f"➕ Добавляю в \"{name}\":")
        if idx is not None:
            track = results[idx]
            if track.is_placeholder():
                print("🔄 Подтягиваю метаданные...")
                track = soundcloud.enrich_track(track)
            self.pm.add(name, track)
            print(f"✅ Добавлено: {track.label}")
            self._wait()

    # ---------- служебное ----------

    def _last_label(self) -> str | None:
        if self.cfg.history:
            h = self.cfg.history[0]
            return f"{h.get('uploader')} — {h.get('title')}"
        return None

    @staticmethod
    def _wait() -> None:
        try:
            input("Нажмите Enter...")
        except EOFError:
            pass
