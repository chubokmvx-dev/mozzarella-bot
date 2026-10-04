"""Маленький вебсервер: віддає фото й відео за підписаними посиланнями, щоб Instagram міг їх забрати."""
import hashlib
import hmac
import json
import logging
import time
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

import db
import ig
from config import ADMIN_ID, BOT_TOKEN, PORT, PUBLIC_URL

DASHBOARD_HTML = Path(__file__).parent / "dashboard.html"


def _sig(pid: int, kind: str) -> str:
    return hmac.new(BOT_TOKEN.encode(), f"{pid}:{kind}".encode(), hashlib.sha256).hexdigest()[:24]


def media_url(pid: int, kind: str) -> str:
    """kind: 'jpg' або 'mp4'."""
    return f"{PUBLIC_URL.rstrip('/')}/m/{pid}/{_sig(pid, kind)}.{kind}"


async def _serve(request: web.Request) -> web.Response:
    pid = int(request.match_info["pid"])
    sig, kind = request.match_info["sig"], request.match_info["kind"]
    if not hmac.compare_digest(sig, _sig(pid, kind)):
        raise web.HTTPNotFound()
    data = await (db.get_image(pid) if kind == "jpg" else db.get_video(pid))
    if not data:
        raise web.HTTPNotFound()
    return web.Response(
        body=data, content_type="image/jpeg" if kind == "jpg" else "video/mp4"
    )


def validate_init_data(init_data: str) -> dict | None:
    """Перевіряє підпис Telegram Mini App (initData). Повертає дані користувача або None."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    got_hash = pairs.pop("hash", None)
    if not got_hash:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, got_hash):
        return None
    try:
        if time.time() - int(pairs.get("auth_date", "0")) > 86400:
            return None
        return json.loads(pairs.get("user", "{}"))
    except (ValueError, TypeError):
        return None


async def _app(_: web.Request) -> web.Response:
    return web.Response(
        text=DASHBOARD_HTML.read_text(encoding="utf-8"),
        content_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


async def _api_dashboard(request: web.Request) -> web.Response:
    user = validate_init_data(request.headers.get("X-Init-Data", ""))
    if not user or user.get("id") != ADMIN_ID:
        raise web.HTTPForbidden()
    rows = await db.published_with_metrics(60)
    posts = []
    for r in rows:
        first_line = (r["text"] or "").strip().split("\n")[0]
        posts.append(
            {
                "id": r["id"],
                "format": r["format"],
                "title": first_line[:70],
                "published_at": r["published_at"].isoformat() if r["published_at"] else None,
                "latest": r["latest"],
                "m24": r["m24"],
                "m7": r["m7"],
            }
        )
    info = await ig.status()
    followers = None
    token = await db.get_setting("page_token")
    if info and token:
        try:
            followers = (await ig._get(info["ig_id"], fields="followers_count", access_token=token)).get(
                "followers_count"
            )
        except Exception:
            logging.info("followers unavailable")
    return web.json_response(
        {"account": info["ig_username"] if info else None, "followers": followers, "posts": posts}
    )


async def _health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


async def start() -> None:
    app = web.Application()
    app.add_routes(
        [
            web.get("/", _health),
            web.get("/app", _app),
            web.get("/api/dashboard", _api_dashboard),
            web.get(r"/m/{pid:\d+}/{sig:[0-9a-f]+}.{kind:jpg|mp4}", _serve),
        ]
    )
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
