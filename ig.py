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
