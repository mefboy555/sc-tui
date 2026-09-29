"""Веб-версия с авторизацией, регистрацией и SQLite."""

import logging
import time
from functools import lru_cache

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from scplay import db, soundcloud as sc, users
from scplay.config import Config
from scplay.playlists import PlaylistManager
from scplay.users import sanitize_name, ensure_default_user

# ---------- logging ----------

db.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(db.CONFIG_DIR / "server.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("scplay")

TIMEOUT = httpx.Timeout(20, connect=10)
COOKIE_NAME = "scplay_session"
COOKIE_MAX_AGE = 30 * 24 * 3600

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' https://*.sndcdn.com https://*.soundcloud.com data:; "
    "media-src 'self' https://*.soundcloud.cloud https://*.sndcdn.com; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)


app = FastAPI(title="scplay web")


@app.on_event("startup")
def _startup():
    db.init_db()
    ensure_default_user()
    log.info("Server started, DB: %s", db.DB_PATH)


# ---------- auth ----------

def current_user(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE_NAME)
    return users.get_session(token)


# ---------- middleware ----------

@app.middleware("http")
async def guard_headers_log(request: Request, call_next):
    path = request.url.path
    start = time.time()

    # API (кроме login/register) требует авторизацию
    if path.startswith("/api/") and path not in ("/api/login", "/api/register"):
        if not current_user(request):
            return JSONResponse({"detail": "Требуется вход"}, status_code=401)

    # / без сессии — на логин
    if path in ("/", "/index.html") and not current_user(request):
        return RedirectResponse("/login", status_code=303)

    response = await call_next(request)

    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"

    if path.startswith("/api/"):
        ms = (time.time() - start) * 1000
        log.info("%s %s -> %s (%.0f ms)",
                 request.method, path, response.status_code, ms)
    return response


# ---------- auth endpoints ----------

@app.post("/api/register")
async def register(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    username = sanitize_name(body.get("username", ""), 32)
    password = str(body.get("password", "") or "")

    if len(username) < 3:
        raise HTTPException(400, "Логин: минимум 3 символа")
    if len(password) < 4:
        raise HTTPException(400, "Пароль: минимум 4 символа")

    u = users.create_user(username, password)
    if not u:
        raise HTTPException(409, "Пользователь с таким логином уже существует")

    # сразу логиним
    token = users.create_session(u["id"])
    response = JSONResponse({"ok": True, "username": u["username"]})
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=COOKIE_MAX_AGE,
        httponly=True, samesite="strict", path="/",
    )
    log.info("register ok: %s", username)
    return response


@app.post("/api/login")
async def login(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    username = sanitize_name(body.get("username", ""), 32)
    password = str(body.get("password", "") or "")

    u = users.find_user(username)
    if not u or not users.verify_password(password, u["password_hash"], u["salt"]):
        log.warning("failed login for %r", username)
        raise HTTPException(401, "Неверный логин или пароль")

    token = users.create_session(u["id"])
    response = JSONResponse({"ok": True, "username": u["username"]})
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=COOKIE_MAX_AGE,
        httponly=True, samesite="strict", path="/",
    )
    log.info("login ok: %s", u["username"])
    return response


@app.post("/api/logout")
def logout(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        users.delete_session(token)
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@app.get("/api/me")
def me(request: Request):
    u = current_user(request)
    if not u:
        raise HTTPException(401)
    cfg = Config(u["user_id"])
    return {"id": u["user_id"], "username": u["username"],
            "volume": cfg.volume, "repeat": cfg.repeat}


# ---------- аудио ----------

@app.get("/api/track")
def api_track(request: Request, url: str):
    stream_url, fmt = sc.get_stream_url(url, prefer_http=True)
    log.info("track: %s -> %s", url.rsplit("/", 1)[-1], fmt or "НЕТ СТРИМА")
    return {"stream_url": stream_url, "format": fmt}


@app.get("/api/stream")
async def api_stream(request: Request, url: str):
    rng = request.headers.get("range")
    headers = {"Range": rng} if rng else {}
    client = httpx.AsyncClient(timeout=TIMEOUT)
    up_req = client.build_request("GET", url, headers=headers)
    up = await client.send(up_req, stream=True)
    keep = {"content-type", "content-range", "content-length", "accept-ranges"}
    resp_headers = {k: v for k, v in up.headers.items() if k.lower() in keep}

    async def gen():
        try:
            async for chunk in up.aiter_bytes(1 << 16):
                yield chunk
        finally:
            await up.aclose()
            await client.aclose()

    return StreamingResponse(gen(), status_code=up.status_code, headers=resp_headers)


# ---------- поиск / история / настройки ----------

@app.get("/api/search")
def api_search(request: Request, q: str, offset: int = 0, limit: int = 50):
    q = sanitize_name(q, 200)
    if not q:
        return []
    if sc.is_url(q):
        tracks = sc.resolve_url(q)
    else:
        tracks = sc.search(q, limit=min(limit, 50), offset=max(offset, 0))
    log.info("search: %r offset=%d -> %d", q, offset, len(tracks))
    return [t.to_dict() for t in tracks]


@app.get("/api/history")
def api_history(request: Request):
    u = current_user(request)
    return Config(u["user_id"]).history


@app.post("/api/history")
async def api_history_add(request: Request):
    """Добавляет трек в историю (вызывается из JS при старте воспроизведения)."""
    u = current_user(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    cfg = Config(u["user_id"])
    track = sc.Track.from_dict(body)
    cfg.add_track(track)
    log.info("history: + %s — %s", track.uploader, track.title[:40])
    return {"ok": True}


@app.post("/api/settings")
async def api_settings(request: Request):
    """
    Обновление настроек.
    - серверный throttle: 1 update в 500мс
    - сохраняем только если значение изменилось
    """
    u = current_user(request)
    uid = u["user_id"]

    # throttle по user_id
    last = getattr(api_settings, "_last", {})
    now = time.time()
    if now - last.get(uid, 0) < 0.5:
        return {"ok": True, "throttled": True}
    last[uid] = now
    api_settings._last = last

    body = await request.json()
    cfg = Config(uid)
    changed = False

    if "volume" in body:
        vol = int(body["volume"])
        if vol != cfg.volume:
            cfg.volume = vol
            changed = True

    if "repeat" in body and body["repeat"] in ("off", "all", "one"):
        if body["repeat"] != cfg.repeat:
            cfg.repeat = body["repeat"]
            changed = True

    if changed:
        cfg.save_config()
        log.info("settings: volume=%d, repeat=%s", cfg.volume, cfg.repeat)

    return {"ok": True, "changed": changed}

# ---------- плейлисты ----------

@app.get("/api/playlists")
def api_playlists(request: Request):
    u = current_user(request)
    return [{"name": n, "count": c}
            for n, c in PlaylistManager(u["user_id"]).names()]


@app.get("/api/playlists/{name}")
def api_playlist(request: Request, name: str):
    u = current_user(request)
    return [t.to_dict() for t in
            PlaylistManager(u["user_id"]).load(sanitize_name(name))]


@app.post("/api/playlists/{name}/create")
def api_playlist_create(request: Request, name: str):
    u = current_user(request)
    name = sanitize_name(name)
    if not name:
        raise HTTPException(400, "Имя не может быть пустым")
    ok = PlaylistManager(u["user_id"]).create(name)
    if not ok:
        raise HTTPException(409, "Плейлист с таким именем уже есть")
    return {"ok": True}


@app.post("/api/playlists/{name}/add")
async def api_playlist_add(request: Request, name: str):
    u = current_user(request)
    body = await request.json()
    track = sc.Track.from_dict(body)
    ok = PlaylistManager(u["user_id"]).add(sanitize_name(name), track)
    return {"ok": ok}


@app.delete("/api/playlists/{name}/remove")
def api_playlist_remove(request: Request, name: str, index: int):
    u = current_user(request)
    PlaylistManager(u["user_id"]).remove(sanitize_name(name), int(index))
    return {"ok": True}


# ---------- pages ----------

@app.get("/login")
def login_page():
    return FileResponse("static/login.html", media_type="text/html")


# статика — обязательно ПОСЛЕ явных роутов
app.mount("/", StaticFiles(directory="static", html=True), name="static")
