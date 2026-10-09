"""Підключення до Instagram Graph API: обмін токена, пошук сторінки та Instagram-акаунта."""
import aiohttp

import db
from config import GRAPH_VERSION, META_APP_ID, META_APP_SECRET

BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


async def _get(path: str, **params) -> dict:
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{BASE}/{path}", params=params) as r:
            data = await r.json()
            if r.status >= 400 or "error" in data:
                msg = data.get("error", {}).get("message", str(data))
                raise RuntimeError(msg)
            return data


async def connect(short_token: str) -> dict:
    """Обмінює короткий токен на довгий, знаходить Page токен і Instagram business ID, зберігає в БД."""
    if not META_APP_ID or not META_APP_SECRET:
        raise RuntimeError("Не задані META_APP_ID / META_APP_SECRET у Railway Variables")

    long_user = await _get(
        "oauth/access_token",
        grant_type="fb_exchange_token",
        client_id=META_APP_ID,
        client_secret=META_APP_SECRET,
        fb_exchange_token=short_token,
    )
    user_token = long_user["access_token"]

    pages = await _get(
        "me/accounts",
        fields="id,name,access_token,instagram_business_account{id,username}",
        access_token=user_token,
    )
    for page in pages.get("data", []):
        ig = page.get("instagram_business_account")
        if ig:
            # Page-токен, отриманий із довгого user-токена, не має терміну дії
            await db.set_setting("page_id", page["id"])
            await db.set_setting("page_name", page["name"])
            await db.set_setting("page_token", page["access_token"])
            await db.set_setting("ig_user_id", ig["id"])
            await db.set_setting("ig_username", ig.get("username", ""))
            return {"page": page["name"], "ig_username": ig.get("username", ""), "ig_id": ig["id"]}

    names = ", ".join(p["name"] for p in pages.get("data", [])) or "жодної сторінки"
    raise RuntimeError(
        f"Знайдено сторінки: {names}, але до жодної не прив'язаний Instagram business-акаунт"
    )


async def status() -> dict | None:
    ig_id = await db.get_setting("ig_user_id")
    if not ig_id:
        return None
    return {
        "page": await db.get_setting("page_name"),
        "ig_username": await db.get_setting("ig_username"),
        "ig_id": ig_id,
    }


async def _post(path: str, **data) -> dict:
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{BASE}/{path}", data={k: str(v) for k, v in data.items()}) as r:
            res = await r.json()
            if r.status >= 400 or "error" in res:
                raise RuntimeError(res.get("error", {}).get("message", str(res)))
            return res


async def _wait_ready(creation_id: str, token: str, timeout: int = 150) -> None:
    """Чекає, поки Instagram обробить фото/відео."""
    import asyncio

    waited = 0
    while waited < timeout:
        st = await _get(creation_id, fields="status_code", access_token=token)
        code = st.get("status_code")
        if code in (None, "FINISHED"):
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram не прийняв файл (статус {code})")
        await asyncio.sleep(5)
        waited += 5
    raise RuntimeError("Instagram довго обробляє файл, спробуй пізніше")


async def publish(kind: str, url: str, caption: str) -> str:
    """kind: 'photo' або 'reel'. Повертає ID опублікованого медіа."""
    ig_id = await db.get_setting("ig_user_id")
    token = await db.get_setting("page_token")
    if not ig_id or not token:
        raise RuntimeError("Instagram не підключений, спершу /ig_connect")
    caption = caption[:2200]
    if kind == "story":
        params = dict(media_type="STORIES", video_url=url)     # у Stories підпис не передається, він уже на відео
    elif kind == "reel":
        params = dict(media_type="REELS", video_url=url, caption=caption, share_to_feed="true")
    else:
        params = dict(image_url=url, caption=caption)
    container = await _post(f"{ig_id}/media", access_token=token, **params)
    await _wait_ready(container["id"], token)
    pub = await _post(f"{ig_id}/media_publish", creation_id=container["id"], access_token=token)
    return pub["id"]


async def permalink(media_id: str) -> str | None:
    token = await db.get_setting("page_token")
    try:
        return (await _get(media_id, fields="permalink", access_token=token)).get("permalink")
    except Exception:
        return None
