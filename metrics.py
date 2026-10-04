"""Збір метрик Instagram, тижневий звіт від Claude та нагадування про пости за планом."""
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import ai
import db
import ig
from config import ADMIN_ID, REMIND_HOUR

TZ = ZoneInfo("Europe/Kyiv")
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]

BASE_METRICS = ["reach", "views", "likes", "comments", "shares", "saved", "total_interactions"]
REEL_METRICS = ["ig_reels_avg_watch_time"]


# ---------------- збір ----------------

async def fetch_insights(media_id: str, fmt: str, token: str) -> dict:
    """Кожну метрику просимо окремо: якщо якась не підтримується для цього типу медіа, решта все одно збереться."""
    data: dict = {}
    try:
        r = await ig._get(media_id, fields="like_count,comments_count", access_token=token)
        if "like_count" in r:
            data["likes_count"] = r["like_count"]
        if "comments_count" in r:
            data["comments_count"] = r["comments_count"]
    except Exception as e:
        logging.warning("counts %s: %s", media_id, e)
    names = BASE_METRICS + (REEL_METRICS if fmt == "reel" else [])
    for name in names:
        try:
            r = await ig._get(f"{media_id}/insights", metric=name, access_token=token)
            data[name] = r["data"][0]["values"][0]["value"]
        except Exception as e:
            logging.info("metric %s for %s unavailable: %s", name, media_id, e)
    return data


async def _collect(posts: list[dict], period: str, token: str) -> int:
    saved = 0
    for p in posts:
        data = await fetch_insights(p["ig_media_id"], p["format"], token)
        if data:
            await db.save_metrics(p["id"], period, data)
            saved += 1
        await asyncio.sleep(1)
    return saved


async def collect_due() -> None:
    token = await db.get_setting("page_token")
    if not token:
        return
    await _collect(await db.posts_due_metrics("24h", 24), "24h", token)
    await _collect(await db.posts_due_metrics("7d", 24 * 7), "7d", token)
    await _collect(await db.posts_needing_latest(), "latest", token)


# ---------------- звіт ----------------

def best_metrics(row: dict) -> dict:
    return row.get("m7") or row.get("latest") or row.get("m24") or {}


async def weekly_report(bot, force: bool = False) -> bool:
    rows = [r for r in await db.published_with_metrics(30) if best_metrics(r)]
    cutoff = datetime.now(TZ) - timedelta(days=14)
    rows = [r for r in rows if r["published_at"] and r["published_at"].astimezone(TZ) >= cutoff]
    if not rows:
        if force:
            await bot.send_message(ADMIN_ID, "Поки немає опублікованих постів із метриками.")
        return False
    payload = [
        {
            "id": r["id"],
            "format": r["format"],
            "published": r["published_at"].astimezone(TZ).strftime("%d.%m %H:%M"),
            "text_start": r["text"][:140],
            "after_24h": r["m24"],
            "after_7d": r["m7"],
            "latest": r["latest"],
        }
        for r in rows
    ]
    text = await ai.analyze_week(payload)
    await bot.send_message(ADMIN_ID, "📊 Тижневий розбір\n\n" + text)
    return True


# ---------------- нагадування ----------------

async def remind(bot, day, slot: str) -> None:
    pending = await db.planned_pending_for(day)
    if pending:
        # у плані є пост на сьогодні, але фото ще немає
        for p in pending:
            kind = "Reels" if p["format"] == "reel" else "пост із фото"
            draft = "" if p["status"] == "approved" else " (текст ще не підтверджено)"
            head = "📸 Сьогодні за планом" if slot == "am" else "⏰ Нагадую: сьогодні ще немає фото для"
            await bot.send_message(
                ADMIN_ID,
                f"{head} {kind} #{p['id']}{draft}.\n\n"
                f"Що знімати: {p['photo_idea']}\n\n"
                "Сфотографуй товар і надішли сюди з описом "
                "(Назва | Ціна | Підзаголовок). Я зроблю картинку й підставлю її в цей пост.",
            )
        return
    if await db.has_post_for_day(day):
        return  # на сьогодні вже все готово або опубліковано
    # на сьогодні поста немає взагалі
    head = "📸 На сьогодні в плані немає посту." if slot == "am" else "⏰ Сьогодні ще не було публікації."
    await bot.send_message(
        ADMIN_ID,
        f"{head}\n\nСфотографуй якийсь товар і надішли мені з описом "
        "(Назва | Ціна | Підзаголовок). Я зроблю картинку, напишу підпис і сам підберу формат. "
        "Якщо хочеш наперед, запусти /plan 7.",
    )


async def tick(bot) -> None:
    now = datetime.now(TZ)
    today = now.date()
    for slot, hour in (("am", REMIND_HOUR), ("pm", 17)):
        key = f"remind_{slot}:{today}"
        if hour <= now.hour < hour + 5 and not await db.get_setting(key):
            await db.set_setting(key, "1")  # спершу позначаємо, щоб не надсилати двічі
            await remind(bot, today, slot)
    if now.weekday() == 0 and now.hour >= 10:
        iso = now.isocalendar()
        key = f"report:{iso[0]}-{iso[1]}"
        if not await db.get_setting(key):
            await db.set_setting(key, "1")
            await weekly_report(bot)


async def metrics_loop() -> None:
    while True:
        try:
            await collect_due()
        except Exception:
            logging.exception("metrics collection failed")
        await asyncio.sleep(15 * 60)


async def schedule_loop(bot) -> None:
    while True:
        try:
            await tick(bot)
        except Exception:
            logging.exception("schedule tick failed")
        await asyncio.sleep(5 * 60)
