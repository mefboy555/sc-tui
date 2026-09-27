"""Терминальные помощники: ANSI, клавиши, меню, справка."""

import os
import select
import sys

KEY_MAP = {"[A": "up", "[B": "down", "[C": "right", "[D": "left"}
DISPLAY_KEYS = {
    " ": "space", "right": "→", "left": "←",
    "up": "↑", "down": "↓", "\x03": "ctrl+c",
}


def clear_screen() -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def clear_line() -> None:
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()


def fmt_time(sec) -> str:
    if not sec:
        return "??:??"
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def display_key(key: str) -> str:
    return DISPLAY_KEYS.get(key, key)


def read_key() -> str:
    fd = sys.stdin.fileno()
    ch = os.read(fd, 1).decode("utf-8", errors="replace")
    if ch != "\x1b":
        return ch
    seq = b""
    while len(seq) < 2:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            return "esc"
        seq += os.read(fd, 2 - len(seq))
    return KEY_MAP.get(seq.decode(), "esc")


def help_line(cfg) -> str:
    def binding(action: str, label: str) -> str:
        keys = "/".join(display_key(k) for k in cfg.keys_for(action)) or "?"
        return f"{keys} — {label}"

    step = cfg.get("seek_step", 10)
    return "🎮 " + " | ".join([
        binding("pause", "пауза"),
        f"{binding('volume_down', 'тише')} / {binding('volume_up', 'громче')}",
        binding("mute", "mute"),
        f"{binding('seek_back', f'-{step}с')} / {binding('seek_forward', f'+{step}с')}",
        f"{binding('prev_track', 'пред. трек')} / {binding('next_track', 'след. трек')}",
        binding("quit", "в меню"),
    ])


def choose_track(tracks, cfg, header: str = "📋 Результаты поиска:"):
    """Меню выбора трека. Возвращает ИНДЕКС трека или None."""
    if not tracks:
        return None
    per_page = max(1, int(cfg.get("per_page", 5)))
    total_pages = (len(tracks) + per_page - 1) // per_page
    page = 0

    while True:
        clear_screen()
        print(header + "\n")
        start = page * per_page
        for i, t in enumerate(tracks[start:start + per_page], start + 1):
            print(f"  {i}. {t.uploader} — {t.title} ({fmt_time(t.duration)})")

        nav = []
        if page > 0:
            nav.append("b — назад")
        if page < total_pages - 1:
            nav.append("n — дальше")
        nav.append("q — отмена")
        print(f"\nстр. {page + 1}/{total_pages} | " + " | ".join(nav))

        choice = input("Номер трека: ").strip().lower()
        if choice == "q":
            return None
        if choice == "n" and page < total_pages - 1:
            page += 1
            continue
        if choice == "b" and page > 0:
            page -= 1
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(tracks):
            return int(choice) - 1


def playlist_picker(items: list[tuple[str, int]]):
    """Список локальных плейлистов. Возвращает ('open', name) | ('create', None) | ('back', None)."""
    while True:
        clear_screen()
        print("📚 Локальные плейлисты:\n")
        if items:
            for i, (name, count) in enumerate(items, 1):
                print(f"  {i}. {name} ({count} трек.)")
        else:
            print("  (пока пусто)")
        print("\n[c] создать | [q] назад")
        choice = input("➤ Выбор: ").strip().lower()
        if choice == "q":
            return ("back", None)
        if choice == "c":
            return ("create", None)
        if choice.isdigit() and 1 <= int(choice) <= len(items):
            return ("open", items[int(choice) - 1][0])


def playlist_view(tracks, cfg, name: str):
    """
    Просмотр плейлиста.
    Возвращает ('play', idx) | ('remove', idx) | ('add', None)
              | ('delete_playlist', None) | ('back', None)
    """
    per_page = max(1, int(cfg.get("per_page", 5)))
    total_pages = max(1, (len(tracks) + per_page - 1) // per_page)
    page = 0

    while True:
        clear_screen()
        print(f"📚 Плейлист \"{name}\" ({len(tracks)} трек.)\n")
        if tracks:
            start = page * per_page
            for i, t in enumerate(tracks[start:start + per_page], start + 1):
                print(f"  {i}. {t.uploader} — {t.title} ({fmt_time(t.duration)})")
            nav = []
            if page > 0:
                nav.append("b — назад")
            if page < total_pages - 1:
                nav.append("n — дальше")
            if nav:
                print("\n" + " | ".join(nav))
        else:
            print("  (пусто — добавь треки командой 'a')")

        print("\nномер — играть с трека | d N — удалить трек | "
              "a — добавить | x — удалить плейлист | q — назад")
        raw = input("➤ ").strip().lower()

        if raw == "q":
            return ("back", None)
        if raw == "a":
            return ("add", None)
        if raw == "x":
            return ("delete_playlist", None)
        if raw.startswith("d") and raw[1:].strip().isdigit():
            idx = int(raw[1:].strip()) - 1
            if 0 <= idx < len(tracks):
                return ("remove", idx)
            continue
        if raw == "n" and page < total_pages - 1:
            page += 1
            continue
        if raw == "b" and page > 0:
            page -= 1
            continue
        if raw.isdigit() and 1 <= int(raw) <= len(tracks):
            return ("play", int(raw) - 1)


def main_menu(last_label: str | None) -> str:
    print()
    print("=" * 50)
    print("🎵  S O U N D C L O U D   П Л Е Е Р")
    print("=" * 50)
    print("  [1] Новый поиск / URL плейлиста")
    print("  [2] История прослушивания")
    print("  [3] Локальные плейлисты")
    print("  [q] Выход")
    if last_label:
        print(f"\n📌 Последний трек: {last_label}")

    while True:
        choice = input("\n➤ Выбор: ").strip().lower()
        if choice in ("1", ""):
            return "search"
        if choice == "2":
            return "history"
        if choice == "3":
            return "playlists"
        if choice == "q":
            return "quit"
        print("❌ Нет такого варианта.")
