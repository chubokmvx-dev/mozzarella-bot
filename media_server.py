"""Маленький вебсервер: віддає фото й відео за підписаними посиланнями, щоб Instagram міг їх забрати."""
import hashlib
import hmac

from aiohttp import web

import db
from config import BOT_TOKEN, PORT, PUBLIC_URL


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


async def _health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


async def start() -> None:
    app = web.Application()
    app.add_routes(
        [
            web.get("/", _health),
            web.get(r"/m/{pid:\d+}/{sig:[0-9a-f]+}.{kind:jpg|mp4}", _serve),
        ]
    )
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
