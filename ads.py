"""Реклама Instagram через Meta Marketing API: перевірка доступу до рекламного кабінету."""
import os

import ig

NEED = ("ads_management", "ads_read", "business_management", "pages_show_list", "instagram_basic")


def token() -> str:
    return os.getenv("META_ADS_TOKEN", "").strip()


async def check() -> str:
    t = token()
    if not t:
        return ("Немає змінної META_ADS_TOKEN у Railway Variables. Потрібен user-токен з правами ads_management, ads_read "
                "і business_management (Graph API Explorer → Generate Access Token). Додай його в Variables і перезапусти бота.")
    lines = []
    try:
        me = await ig._get("me", fields="id,name", access_token=t)
        lines.append(f"Токен працює: {me.get('name')}")
    except Exception as e:
        return f"Токен не підійшов: {e}"
    try:
        perms = await ig._get("me/permissions", access_token=t)
        granted = {p["permission"] for p in perms.get("data", []) if p.get("status") == "granted"}
        miss = [p for p in NEED if p not in granted]
        lines.append("Права: " + ("усі потрібні є" if not miss else "бракує " + ", ".join(miss)))
    except Exception as e:
        lines.append(f"Права перевірити не вийшло: {e}")
    try:
        acc = await ig._get("me/adaccounts", fields="id,name,account_status,currency,disable_reason,funding_source_details", limit=25, access_token=t)
        data = acc.get("data", [])
        if not data:
            lines.append("Рекламних кабінетів не знайдено. Створи кабінет у Meta Business Suite → Налаштування → Рекламні акаунти.")
        for a in data:
            st = {1: "активний", 2: "вимкнений", 3: "є заборгованість", 7: "на перевірці", 9: "пільговий період", 101: "закритий"}.get(a.get("account_status"), str(a.get("account_status")))
            pay = "картка/оплата прив'язана" if a.get("funding_source_details") else "оплата НЕ додана"
            lines.append(f"Кабінет: {a.get('name')} ({a['id']}), {st}, {a.get('currency')}, {pay}")
    except Exception as e:
        lines.append(f"Кабінети отримати не вийшло: {e}")
    return "\n".join(lines)
