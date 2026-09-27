"""
SoundCloud: поиск, плейлисты, стримы.

- Поиск             — через yt-dlp (scsearch): надёжно и с метаданными.
- URL трека/плейлиста/профиля — напрямую через API v2 SoundCloud.
- Аудиострим        — через yt-dlp (он умеет доставать форматы).
"""

import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict

from .config import CONFIG_DIR

PRINT_FMT = "%(webpage_url)s|||%(title)s|||%(uploader)s|||%(duration)s"
NA = "NA"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}
CID_CACHE = CONFIG_DIR / "client_id.json"
CID_TTL = 6 * 3600
MAX_PAGES = 100


@dataclass
class Track:
    title: str
    uploader: str
    url: str
    duration: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Track":
        return cls(
            title=data.get("title", "???"),
            uploader=data.get("uploader", "???"),
            url=data.get("url", ""),
            duration=int(data.get("duration", 0) or 0),
        )

    @property
    def label(self) -> str:
        return f"{self.uploader} — {self.title}"

    def is_placeholder(self) -> bool:
        return (
            self.title in ("Неизвестный трек", NA, "")
            or self.uploader in ("Неизвестный исполнитель", NA, "")
        )


# ---------- HTTP (stdlib) ----------

def _http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _http_json(url: str):
    return json.loads(_http_get(url).decode("utf-8", "replace"))


# ---------- client_id ----------

def _fetch_client_id() -> str:
    html = _http_get("https://soundcloud.com").decode("utf-8", "replace")
    scripts = re.findall(r'<script[^>]+src="([^"]+\.js)"', html)
    for src in scripts:
        try:
            js = _http_get(src).decode("utf-8", "replace")
        except OSError:
            continue
        m = re.search(r'client_id\s*[:=]\s*["\']([A-Za-z0-9]{32})["\']', js)
        if m:
            return m.group(1)
    raise RuntimeError("не удалось извлечь client_id")


def get_client_id(force: bool = False) -> str:
    if not force and CID_CACHE.exists():
        try:
            data = json.loads(CID_CACHE.read_text(encoding="utf-8"))
            if time.time() - data.get("ts", 0) < CID_TTL:
                return data["client_id"]
        except (json.JSONDecodeError, OSError, KeyError):
            pass
    cid = _fetch_client_id()
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CID_CACHE.write_text(
            json.dumps({"client_id": cid, "ts": time.time()}),
            encoding="utf-8",
        )
    except OSError:
        pass
    return cid


def _api_resolve(url: str) -> dict:
    for attempt in (False, True):
        cid = get_client_id(force=attempt)
        api = ("https://api-v2.soundcloud.com/resolve?url="
               + urllib.parse.quote(url, safe="") + f"&client_id={cid}")
        try:
            return _http_json(api)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403) and not attempt:
                continue
            raise
    raise RuntimeError("API resolve не ответил")


def _track_from_api(t: dict) -> Track | None:
    url = t.get("permalink_url") or ""
    if not url.startswith("https://soundcloud.com/"):
        return None
    return Track(
        title=(t.get("title") or "").strip() or "Неизвестный трек",
        uploader=((t.get("user") or {}).get("username") or "").strip() or "Неизвестный исполнитель",
        url=url,
        duration=int((t.get("duration") or 0) // 1000),
    )


# ---------- yt-dlp helpers ----------

def _run_ytdlp(args: list[str]) -> str:
    result = subprocess.run(["yt-dlp"] + args, capture_output=True, text=True)
    if result.returncode != 0 and not result.stdout.strip():
        raise RuntimeError(result.stderr.strip() or "yt-dlp exited with non-zero code")
    return result.stdout


def _clean(value, fallback: str) -> str:
    value = (value or "").strip()
    return value if value and value != NA else fallback


def _parse_lines(output: str) -> list[Track]:
    tracks = []
    for line in output.strip().splitlines():
        parts = line.split("|||")
        if len(parts) < 4:
            continue
        url, title, uploader, dur = parts[:4]
        if url == NA or not url.startswith("https://soundcloud.com/"):
            continue
        tracks.append(Track(
            title=_clean(title, "Неизвестный трек"),
            uploader=_clean(uploader, "Неизвестный исполнитель"),
            url=url,
            duration=int(dur) if dur.isdigit() else 0,
        ))
    return tracks


def is_url(text: str) -> bool:
    return text.startswith(("http://", "https://"))


# ---------- пагинация / догрузка ----------

def _collect_pages(items: list, next_url) -> list:
    """Склеивает страницы пагинации через next_href (для коллекций)."""
    guard = 0
    while next_url and guard < MAX_PAGES:
        guard += 1
        try:
            page = _http_json(next_url)
        except Exception:
            break
        batch = page.get("collection") or page.get("tracks") or []
        if not batch:
            break
        items = items + batch
        next_url = page.get("next_href")
    return items


def _fetch_user_tracks(uid) -> list[dict]:
    """Треки пользователя через /users/{id}/tracks с пагинацией."""
    cid = get_client_id()
    first = (f"https://api-v2.soundcloud.com/users/{uid}/tracks"
             f"?client_id={cid}&limit=50")
    try:
        page = _http_json(first)
    except Exception:
        return []
    return _collect_pages(page.get("collection") or [], page.get("next_href"))


def _hydrate_tracks(raw: list[dict]) -> list[dict]:
    """
    Если треки пришли огрызками (без title или permalink_url) —
    догружаем полные объекты через /tracks?ids=... (так делает сам веб-плеер).
    """
    if not raw:
        return raw
    
    # Проверяем ВСЕ элементы, а не только первые 5
    needs_hydration = any(
        not (isinstance(t, dict) and t.get("title") and t.get("permalink_url"))
        for t in raw
    )
    
    if not needs_hydration:
        return raw

    ids = [str(t["id"]) for t in raw if isinstance(t, dict) and t.get("id")]
    if not ids:
        return raw

    cid = get_client_id()
    out: list[dict] = []
    for i in range(0, len(ids), 50):
        chunk = ",".join(ids[i:i + 50])
        url = f"https://api-v2.soundcloud.com/tracks?ids={chunk}&client_id={cid}"
        try:
            page = _http_json(url)
            if isinstance(page, list):
                out.extend(page)
            elif isinstance(page, dict):
                out.extend(page.get("collection") or [])
        except Exception as e:
            print(f"⚠️ /tracks?ids= не ответил: {e}")
            break
    print(f"📊 hydrate: {len(out)} полных объектов из {len(ids)}")
    return out or raw


def _to_tracks(raw: list) -> list[Track]:
    tracks = []
    for item in raw:
        if isinstance(item, dict):
            tr = _track_from_api(item)
            if tr:
                tracks.append(tr)
    return tracks


# ---------- публичные функции ----------

def search(query: str, limit: int = 20) -> list[Track]:
    try:
        output = _run_ytdlp([
            f"scsearch{limit}:{query}",
            "--flat-playlist", "--print", PRINT_FMT,
            "--no-warnings", "--quiet",
        ])
    except RuntimeError as e:
        print(f"❌ Ошибка поиска: {e}")
        return []
    return _parse_lines(output)


def resolve_url(url: str) -> list[Track]:
    """URL трека/плейлиста/профиля → ВСЕ треки с полными метаданными."""
    try:
        data = _api_resolve(url)
    except Exception as e:
        print(f"⚠️ API не ответил ({e}), пробую yt-dlp...")
        return _resolve_via_ytdlp(url)

    kind = data.get("kind")
    print(f"📊 API вернул kind={kind!r}")

    # Одиночный трек
    if kind == "track":
        tr = _track_from_api(data)
        return [tr] if tr else []

    # Плейлист / альбом: resolve отдаёт ВСЕ треки, но иногда огрызками
    if kind in ("playlist", "album", "system-playlist", "single", "ep"):
        raw = list(data.get("tracks") or [])
        if raw:
            print(f"📊 в resolve {len(raw)} записей; ключи первой: "
                  f"{sorted(raw[0].keys())[:10]}")
        raw = _hydrate_tracks(raw)
        tracks = _to_tracks(raw)

        # Запасной вариант: полный объект плейлиста
        if not tracks and data.get("id"):
            try:
                cid = get_client_id()
                full = _http_json(
                    f"https://api-v2.soundcloud.com/playlists/{data['id']}?client_id={cid}")
                raw2 = _hydrate_tracks(full.get("tracks") or [])
                tracks = _to_tracks(raw2)
            except Exception as e:
                print(f"⚠️ /playlists/{{id}} не ответил: {e}")

        print(f"✅ Треков в плейлисте: {len(tracks)}")
        return tracks or _resolve_via_ytdlp(url)

    # Профиль пользователя
    if kind == "user":
        tracks = _to_tracks(_fetch_user_tracks(data.get("id")))
        print(f"✅ Треков у пользователя: {len(tracks)}")
        return tracks or _resolve_via_ytdlp(url)

    # Любая коллекция (ленты, лайки и т.п.)
    if isinstance(data.get("collection"), list):
        raw = _collect_pages(data["collection"], data.get("next_href"))
        tracks = _to_tracks(raw)
        print(f"✅ Треков в коллекции: {len(tracks)}")
        return tracks or _resolve_via_ytdlp(url)

    print(f"⚠️ Неизвестный kind={kind!r}, пробую yt-dlp...")
    return _resolve_via_ytdlp(url)


def _resolve_via_ytdlp(url: str) -> list[Track]:
    try:
        output = _run_ytdlp([
            url, "--flat-playlist", "--print", PRINT_FMT,
            "--no-warnings", "--quiet",
        ])
    except RuntimeError as e:
        print(f"❌ Ошибка загрузки URL: {e}")
        return []
    tracks = _parse_lines(output)
    print(f"📋 Получено треков (yt-dlp): {len(tracks)}")
    return tracks


def enrich_track(track: Track) -> Track:
    if not track.is_placeholder():
        return track
    try:
        data = _api_resolve(track.url)
        if data.get("kind") == "track":
            rich = _track_from_api(data)
            if rich:
                return rich
    except Exception:
        pass
    try:
        info = json.loads(_run_ytdlp([
            track.url, "--dump-json", "--no-warnings", "--quiet",
        ]))
        return Track(
            title=_clean(info.get("title"), track.title),
            uploader=_clean(info.get("uploader") or info.get("channel"), track.uploader),
            url=info.get("webpage_url") or track.url,
            duration=int(info.get("duration") or track.duration or 0),
        )
    except Exception:
        return track


def get_stream_url(track_url: str) -> tuple[str | None, str | None]:
    try:
        output = _run_ytdlp([
            track_url, "--dump-json", "--no-warnings", "--quiet",
        ])
        info = None
        for line in output.strip().splitlines():
            try:
                info = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        if info is None:
            print("❌ Не удалось разобрать JSON от yt-dlp")
            return None, None
    except RuntimeError as e:
        print(f"❌ Ошибка получения стрима: {e}")
        return None, None

    formats = info.get("formats", [])
    audio = [f for f in formats if f.get("acodec") != "none" and f.get("vcodec") == "none"]
    pool = audio or [f for f in reversed(formats) if f.get("acodec") != "none"]
    if not pool:
        return None, None
    best = pool[-1]
    return best.get("url"), best.get("format_note")
