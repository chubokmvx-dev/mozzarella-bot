import asyncio
import logging
import re
from html import escape as html_escape
from datetime import datetime, timedelta
from io import BytesIO

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

import ads
import ai
import db
import ig
import media_server
import metrics
import photo
import video
from config import ADMIN_ID, AUTO_PUBLISH, BOT_TOKEN, DATABASE_URL, META_USER_TOKEN, PUBLIC_URL

logging.basicConfig(level=logging.INFO)

router = Router()
# бот відповідає лише власнику
router.message.filter(F.from_user.id == ADMIN_ID)
router.callback_query.filter(F.from_user.id == ADMIN_ID)


class Edit(StatesGroup):
    waiting = State()


class PhotoFlow(StatesGroup):
    waiting_caption = State()


class StoryEdit(StatesGroup):
    waiting = State()


def kb(post_id: int, swap_targets: list[dict] | None = None, media: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if media:
        # у посту є фото: його можна одразу публікувати або змінити формат
        rows.append(
            [
                InlineKeyboardButton(text="🚀 Опублікувати", callback_data=f"pub:{post_id}"),
                InlineKeyboardButton(text="🔄 Інший формат", callback_data=f"fmt:{post_id}"),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"ok:{post_id}"),
            InlineKeyboardButton(text="✏️ Змінити", callback_data=f"edit:{post_id}"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data=f"no:{post_id}"),
        ]
    )
    # фото можна підставити замість поста з плану: його текст перепишеться під це фото
    for d in swap_targets or []:
        label = f"↪️ Підставити в пост #{d['id']}" + (f" · {d['slot']}" if d["slot"] else "")
        rows.append([InlineKeyboardButton(text=label, callback_data=f"swap:{post_id}:{d['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def render(p: dict) -> str:
    head = f"📝 Пост #{p['id']} · {p['format']}" + (f" · {p['slot']}" if p["slot"] else "")
    out = f"{head}\n\n{p['text']}"
    if p["photo_idea"] and p["photo_idea"] != "фото додано":
        out += f"\n\n📷 Фото: {p['photo_idea']}"
    return out


BTN_CAL = "📅 Контент-план"
MAIN_KB = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CAL)]], resize_keyboard=True)
STATUS_ICON = {"draft": "📝", "approved": "✅", "published": "🚀"}
FMT_ICON = {"reel": "🎬", "carousel": "🖼", "photo": "📷"}


def _short(text: str, n: int = 45) -> str:
    one = " ".join(text.split())
    return one if len(one) <= n else one[: n - 1] + "…"


def render_calendar(posts: list[dict], today) -> list[tuple[str, list[dict]]]:
    """Календар, розбитий на повідомлення до ~3500 символів: [(текст, пости цього повідомлення)]."""
    if not posts:
        return [("📅 У плані поки нічого немає. Команда /plan 7 складе план на тиждень.", [])]
    chunks, ids, cur, last_key = [], [], "", object()
    cur = "📅 <b>Контент-план</b>\n📝 чернетка · ✅ підтверджено · 🚀 опубліковано · 🖼 є медіа\n"
    for p in posts:
        d = p["planned_date"]
        key = d
        if key != last_key:
            if d is None:
                title = "Без дати"
            else:
                tag = " (сьогодні)" if d == today else " (завтра)" if (d - today).days == 1 else ""
                title = f"{metrics.WEEKDAYS[d.weekday()]} {d:%d.%m}{tag}"
            cur += f"\n<b>{title}</b>\n"
            last_key = key
        tm = re.search(r"\d{1,2}:\d{2}", p["slot"] or "")
        media = " 🖼" if (p["has_img"] or p["has_vid"]) else ""
        line = (f"{STATUS_ICON.get(p['status'], '•')} {tm.group() + ' ' if tm else ''}"
                f"{FMT_ICON.get(p['format'], '📷')} #{p['id']} {html_escape(_short(p['text']))}{media}\n")
        if len(cur) + len(line) > 3500:
            chunks.append((cur, ids))
            cur, ids, last_key = "", [], object()
        cur += line
        ids.append(p)
    chunks.append((cur, ids))
    return chunks


@router.message(Command("calendar"))
@router.message(F.text == BTN_CAL)
async def calendar(m: Message):
    today = datetime.now(metrics.TZ).date()
    for text, items in render_calendar(await db.upcoming_posts(), today):
        await m.answer(text, parse_mode="HTML", reply_markup=cal_kb(items))


def cal_kb(items: list[dict]) -> InlineKeyboardMarkup | None:
    """Кнопка зміни дати/часу під кожним ще не опублікованим постом (без дати — з позначкою 🗓)."""
    rows = []
    for p in items:
        if p["status"] == "published":
            continue
        mark = "🗓 Поставити дату" if p["planned_date"] is None else "✏️ Змінити"
        rows.append([InlineKeyboardButton(text=f"{mark} · #{p['id']} {_short(p['text'], 18)}", callback_data=f"cd:{p['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows[:40]) if rows else None


@router.callback_query(F.data.startswith("cd:"))
async def cal_pick_date(c: CallbackQuery):
    pid = int(c.data.split(":")[1])
    post = await db.get_post(pid)
    if not post or post["status"] == "published":
        await c.answer("Пост недоступний", show_alert=True)
        return
    today = datetime.now(metrics.TZ).date()
    days = [today + timedelta(days=i) for i in range(0, 8)]
    btns = [InlineKeyboardButton(
        text=("Сьогодні" if i == 0 else "Завтра" if i == 1 else metrics.WEEKDAYS[d.weekday()]) + f" {d:%d.%m}",
        callback_data=f"cs:{pid}:{d:%Y%m%d}") for i, d in enumerate(days)]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([InlineKeyboardButton(text="🚫 Без дати", callback_data=f"cs:{pid}:none"),
                 InlineKeyboardButton(text="✖️ Закрити", callback_data="cx")])
    await c.message.answer(f"📅 Пост #{pid} · {html_escape(_short(post['text'], 60))}\nНа який день запланувати?",
                           reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    await c.answer()


@router.callback_query(F.data == "cx")
async def cal_close(c: CallbackQuery):
    await c.message.delete()
    await c.answer()


@router.callback_query(F.data.startswith("cs:"))
async def cal_pick_time(c: CallbackQuery):
    _, pid, day = c.data.split(":")
    if day == "none":
        await db.set_schedule(int(pid), None, "")
        await c.message.edit_text(f"🚫 Пост #{pid}: дату знято.")
        await c.answer()
        return
    times = ["09:00", "12:00", "15:00", "18:00", "20:00", "21:00"]
    rows = [[InlineKeyboardButton(text=t, callback_data=f"ct:{pid}:{day}:{t.replace(':', '')}") for t in times[i:i + 3]]
            for i in range(0, 6, 3)]
    rows.append([InlineKeyboardButton(text="Без часу", callback_data=f"ct:{pid}:{day}:0")])
    d = datetime.strptime(day, "%Y%m%d").date()
    await c.message.edit_text(f"📅 Пост #{pid} · {metrics.WEEKDAYS[d.weekday()]} {d:%d.%m}\nО котрій?",
                              reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await c.answer()


@router.callback_query(F.data.startswith("ct:"))
async def cal_save(c: CallbackQuery):
    _, pid, day, hhmm = c.data.split(":")
    d = datetime.strptime(day, "%Y%m%d").date()
    t = f"{hhmm[:2]}:{hhmm[2:]}" if hhmm != "0" else ""
    slot = f"{metrics.WEEKDAYS[d.weekday()]} {d:%d.%m}" + (f" {t}" if t else "")
    await db.set_schedule(int(pid), d, slot)
    await c.message.edit_text(f"✅ Пост #{pid} заплановано: {slot}. Побачиш його в «{BTN_CAL}».")
    await c.answer()


async def reel_clip(image: bytes) -> bytes:
    """Reels з музикою: твій трек із /music (випадковий), інакше власна ambient-музика. Вимкнути: /music off."""
    music = None
    if (await db.get_setting("music_on")) != "0":
        music = await db.random_music()
        try:
            return await asyncio.to_thread(video.make_reel, image, music)
        except Exception:
            if music is None:
                raise
            logging.exception("custom music failed, falling back to built-in")
            return await asyncio.to_thread(video.make_reel, image, None)
    return await asyncio.to_thread(video.make_reel, image, None, False)


@router.message(Command("music"))
async def music_cmd(m: Message):
    arg = (m.text or "").split(maxsplit=1)[1].strip().lower() if len((m.text or "").split()) > 1 else ""
    if arg in ("off", "on"):
        await db.set_setting("music_on", "0" if arg == "off" else "1")
    elif arg == "clear":
        await db.clear_music()
    tracks = await db.list_music()
    on = (await db.get_setting("music_on")) != "0"
    lst = "\n".join(f"• {t['name']}" for t in tracks) or "— своїх треків немає, використовую вбудовану ambient-музику"
    await m.answer(
        f"🎵 Музика в Reels: {'увімкнена' if on else 'вимкнена'}\n{lst}\n\n"
        "Щоб додати трек, надішли мені аудіофайл (mp3/m4a) — бот буде брати випадковий.\n"
        "/music off · /music on · /music clear (видалити мої треки)\n\n"
        "⚠️ Бери музику без авторських прав (YouTube Audio Library, Pixabay Music), інакше Instagram може вимкнути звук."
    )


@router.message(F.audio | F.document.mime_type.startswith("audio/"))
async def music_upload(m: Message, bot: Bot):
    f = m.audio or m.document
    if f.file_size and f.file_size > 15 * 1024 * 1024:
        await m.answer("Файл завеликий (макс. 15 МБ).")
        return
    buf = await bot.download(f)
    name = getattr(f, "title", None) or getattr(f, "file_name", None) or "трек"
    await db.add_music(name, buf.read())
    await m.answer(f"🎵 Трек «{name}» додано. Нові Reels будуть із музикою (/music — список).")


@router.message(Command("start"))
async def start(m: Message):
    await m.answer(
        "Привіт! Команди:\n"
        "/calendar — що вже заплановано\n"
        "/plan 7 — контент-план на 7 днів\n"
        "/plan 7 більше новинок — з побажанням\n"
        "/dashboard — дашборд з метриками\n"
        "/report — розбір результатів від Claude\n"
        "/ig_status — стан підключення Instagram\n\n"
        "Обробка фото: надішли фото продукту (краще як файл), потім опис:\n"
        "Назва | Ціна | Підзаголовок\n"
        "Наприклад: Моцарела буфала | 389 | Свіжа поставка\n\n"
        "Акційне фото (з плашкою АКЦІЯ, знижкою і закресленою ціною):\n"
        "акція | Назва | Нова ціна | Стара ціна | Підзаголовок\n"
        "Наприклад: акція | Моцарела буфала | 289 | 389 | Діє до 15.10\n\n"
        "Опис можна додати і одразу в підпис до фото.",
        reply_markup=MAIN_KB,
    )


@router.message(Command("ig_connect"))
async def ig_connect(m: Message):
    if not META_USER_TOKEN:
        await m.answer("Немає META_USER_TOKEN у Railway Variables. Додай токен і перезапусти бота.")
        return
    await m.answer("Підключаю Instagram…")
    try:
        info = await ig.connect(META_USER_TOKEN)
    except Exception as e:
        logging.exception("ig connect failed")
        await m.answer(f"Не вдалося підключити: {e}")
        return
    await m.answer(
        f"✅ Підключено: Instagram @{info['ig_username']} (сторінка «{info['page']}»).\n"
        "Тепер можна видалити META_USER_TOKEN з Railway Variables, він більше не потрібен."
    )


@router.message(Command("ads_check"))
async def ads_check(m: Message):
    await m.answer("Перевіряю доступ до рекламного кабінету…")
    await m.answer(await ads.check())


@router.message(Command("ig_status"))
async def ig_status(m: Message):
    info = await ig.status()
    if not info:
        await m.answer("Instagram ще не підключений. Команда: /ig_connect")
        return
    await m.answer(f"Instagram: @{info['ig_username']}, сторінка «{info['page']}» ✅")


@router.message(Command("dashboard"))
async def dashboard(m: Message):
    if not PUBLIC_URL:
        await m.answer("Не задано PUBLIC_URL у Railway Variables.")
        return
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Відкрити дашборд",
                    web_app=WebAppInfo(url=f"{PUBLIC_URL.rstrip('/')}/app"),
                )
            ]
        ]
    )
    await m.answer("Дашборд з метриками постів:", reply_markup=markup)


@router.message(Command("report"))
async def report(m: Message, bot: Bot):
    await m.answer("Збираю актуальні метрики й аналізую…")
    try:
        await metrics.collect_due()
        await metrics.weekly_report(bot, force=True)
    except Exception as e:
        logging.exception("report failed")
        await m.answer(f"Не вдалося зробити розбір: {e}")


@router.message(Command("plan"))
async def plan(m: Message, command: CommandObject):
    args = (command.args or "").split(maxsplit=1)
    days = min(int(args[0]), 14) if args and args[0].isdigit() else 7
    note = args[1] if len(args) > 1 else ""
    await m.answer("Складаю план, хвилинку…")
    try:
        items = await ai.generate_plan(days, note)
    except Exception:
        logging.exception("plan failed")
        await m.answer("Не вдалося скласти план, спробуй ще раз.")
        return
    # перший день плану: сьогодні, якщо ще немає 12:00 за Києвом, інакше завтра
    now = datetime.now(metrics.TZ)
    start = now.date() if now.hour < 12 else now.date() + timedelta(days=1)
    for idx, it in enumerate(items, start=1):
        try:
            day = max(1, min(int(it.get("day", idx)), days))
        except (TypeError, ValueError):
            day = idx
        planned = start + timedelta(days=day - 1)
        t = re.search(r"\d{1,2}:\d{2}", str(it.get("time", "")))
        slot = f"{metrics.WEEKDAYS[planned.weekday()]} {planned:%d.%m}" + (f" {t.group()}" if t else "")
        fmt = it.get("format") if it.get("format") in ("photo", "reel") else "photo"
        pid = await db.add_post(fmt, slot, it["text"], it.get("photo_idea", ""), planned)
        await m.answer(render(await db.get_post(pid)), reply_markup=kb(pid))


@router.callback_query(F.data.startswith("ok:"))
async def approve(c: CallbackQuery):
    pid = int(c.data.split(":")[1])
    await db.set_status(pid, "approved")  # далі їх підхопить планувальник публікацій
    await c.message.edit_reply_markup(reply_markup=None)
    await c.message.reply(f"✅ Пост #{pid} підтверджено")
    await c.answer()


async def _publish(m: Message, pid: int):
    post = await db.get_post(pid)
    if not post:
        await m.answer("Не знайшов пост.")
        return
    if post["status"] == "published":
        await m.answer(f"Пост #{pid} уже опублікований.")
        return
    if not PUBLIC_URL:
        await m.answer("Не задано PUBLIC_URL у Railway Variables, Instagram не зможе забрати файл.")
        return
    is_reel = post["format"] == "reel" and bool(await db.get_video(pid))
    url = media_server.media_url(pid, "mp4" if is_reel else "jpg")
    await m.answer("Публікую в Instagram… Reels може зайняти до пари хвилин." if is_reel else "Публікую в Instagram…")
    try:
        media_id = await ig.publish("reel" if is_reel else "photo", url, post["text"])
    except Exception as e:
        logging.exception("publish failed")
        await m.answer(f"Не вдалося опублікувати: {e}")
        return
    await db.set_published(pid, media_id)
    link = await ig.permalink(media_id)
    await m.answer(f"✅ Опубліковано! {link or ''}".strip())


@router.callback_query(F.data.startswith("pub:"))
async def publish_cb(c: CallbackQuery):
    pid = int(c.data.split(":")[1])
    await c.message.edit_reply_markup(reply_markup=None)
    await c.answer()
    await _publish(c.message, pid)


@router.callback_query(F.data.startswith("fmt:"))
async def switch_format(c: CallbackQuery):
    pid = int(c.data.split(":")[1])
    post, image = await db.get_post(pid), await db.get_image(pid)
    if not post or not image:
        await c.answer("Немає фото", show_alert=True)
        return
    await c.answer()
    if post["format"] == "reel":
        await db.set_format(pid, "photo")
        await c.message.answer("Переключив на звичайний пост.")
    else:
        await c.message.answer("Роблю Reels…")
        try:
            clip = await db.get_video(pid) or await reel_clip(image)
        except Exception:
            logging.exception("reel failed")
            await c.message.answer("Reels зробити не вдалося.")
            return
        await db.set_video(pid, clip)
        await db.set_format(pid, "reel")
        await c.message.answer_video(BufferedInputFile(clip, filename="reel.mp4"), width=1080, height=1920, supports_streaming=True, caption="🎞 Reels")
    await c.message.edit_reply_markup(reply_markup=None)
    await c.message.answer(render(await db.get_post(pid)), reply_markup=kb(pid, media=True))


@router.callback_query(F.data.startswith("swap:"))
async def swap(c: CallbackQuery):
    _, new_id, old_id = c.data.split(":")
    new_id, old_id = int(new_id), int(old_id)
    new, old = await db.get_post(new_id), await db.get_post(old_id)
    image = await db.get_image(new_id)
    if not new or not old or not image:
        await c.answer("Не знайшов пост або фото", show_alert=True)
        return
    await c.message.edit_reply_markup(reply_markup=None)
    await c.message.answer(f"Підлаштовую пост #{old_id} під фото…")
    try:
        text = await ai.post_from_photo(image, hint=new["text"], existing=old["text"])
    except Exception:
        logging.exception("swap failed")
        await c.message.answer("Не вийшло, спробуй ще раз.")
        await c.answer()
        return
    await db.set_text(old_id, text)
    await db.set_image(old_id, image)
    await db.set_status(new_id, "rejected")  # тимчасовий пост під фото більше не потрібен
    if old["format"] == "reel":
        # пост із плану заплановано як Reels: збираємо відео з підставленого фото
        try:
            clip = await reel_clip(image)
            await db.set_video(old_id, clip)
            await c.message.answer_video(BufferedInputFile(clip, filename="reel.mp4"), width=1080, height=1920, supports_streaming=True, caption="🎞 Reels")
        except Exception:
            logging.exception("reel failed")
            await db.set_format(old_id, "photo")
            await c.message.answer("Reels зробити не вдалося, пост піде звичайним фото.")
    await c.message.answer(render(await db.get_post(old_id)), reply_markup=kb(old_id, media=True))
    await c.answer()


@router.callback_query(F.data.startswith("no:"))
async def reject(c: CallbackQuery):
    pid = int(c.data.split(":")[1])
    await db.set_status(pid, "rejected")
    await c.message.edit_reply_markup(reply_markup=None)
    await c.message.reply(f"❌ Пост #{pid} скасовано")
    await c.answer()


@router.callback_query(F.data.startswith("edit:"))
async def edit(c: CallbackQuery, state: FSMContext):
    pid = int(c.data.split(":")[1])
    await state.set_state(Edit.waiting)
    await state.update_data(pid=pid)
    await c.message.edit_reply_markup(reply_markup=None)
    await c.message.answer(f"Напиши правку для поста #{pid}, наприклад: «зроби коротше, додай про свіжість»")
    await c.answer()


@router.message(Edit.waiting, F.text)
async def apply_edit(m: Message, state: FSMContext):
    pid = (await state.get_data())["pid"]
    post = await db.get_post(pid)
    await m.answer("Правлю…")
    try:
        new_text = await ai.revise_post(post["text"], m.text)
    except Exception:
        logging.exception("revise failed")
        await m.answer("Не вийшло, напиши правку ще раз.")
        return
    await db.set_text(pid, new_text)
    await state.clear()
    await m.answer(
        render(await db.get_post(pid)),
        reply_markup=kb(pid, media=bool(await db.get_image(pid))),
    )


STORY_WORDS = ("сторіс", "сторис", "сторі", "story", "stories")


def story_kb(sid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Опублікувати в Stories", callback_data=f"sp:{sid}")],
        [InlineKeyboardButton(text="🔁 Інший підпис", callback_data=f"sc:{sid}"),
         InlineKeyboardButton(text="✏️ Свій підпис", callback_data=f"se:{sid}")],
        [InlineKeyboardButton(text="❌ Прибрати", callback_data=f"sd:{sid}")],
    ])


async def reel_music() -> bytes | None:
    """Музика для сторіс і Reels: твій трек із /music, інакше вбудована (вимкнути: /music off)."""
    return await db.random_music() if (await db.get_setting("music_on")) != "0" else None


async def _make_story(m: Message, bot: Bot, file_id: str, caption: str):
    """Фото з підписом «сторіс | Назва | свій підпис(необов'язково)» → вертикальне відео зі стрічки без цін."""
    parts = [p.strip() for p in caption.split("|")]
    title = parts[1] if len(parts) > 1 else ""
    own = parts[2] if len(parts) > 2 else ""
    await m.answer("Роблю сторіс…")
    try:
        buf = BytesIO()
        await bot.download(file_id, destination=buf)
        src = buf.getvalue()
        text = "" if own in ("-", "без", "—") else own
        if not text and own not in ("-", "без", "—"):
            try:
                text = await ai.story_caption(src, title)
            except Exception:
                logging.exception("story caption failed")
                text = title
        music = await reel_music()
        clip = await asyncio.to_thread(video.make_story, src, text, music, (await db.get_setting("music_on")) != "0")
        sid = await db.add_story(title, text, src, clip)
    except Exception:
        logging.exception("story failed")
        await m.answer("Не вдалося зробити сторіс, спробуй надіслати фото ще раз.")
        return
    await m.answer_video(BufferedInputFile(clip, filename="story.mp4"), width=1080, height=1920, supports_streaming=True, caption=f"📲 Сторіс #{sid}\nПідпис: {text or '—'}",
                         reply_markup=story_kb(sid))


async def _redo_story(sid: int, caption: str) -> bytes:
    st_ = await db.get_story(sid)
    music = await reel_music()
    if st_["kind"] == "video":
        clip = await asyncio.to_thread(video.story_from_video, st_["src"], caption, music)
    else:
        clip = await asyncio.to_thread(video.make_story, st_["src"], caption, music, (await db.get_setting("music_on")) != "0")
    await db.set_story(sid, caption, clip)
    return clip


@router.callback_query(F.data.startswith("sc:"))
async def story_recaption(c: CallbackQuery):
    sid = int(c.data.split(":")[1])
    st_ = await db.get_story(sid)
    if not st_:
        await c.answer("Сторіс не знайдено", show_alert=True)
        return
    await c.answer("Придумую інший підпис…")
    try:
        text = await ai.story_caption(st_["thumb"] if st_["kind"] == "video" else st_["src"],
                                      (st_["title"] + f". Не повторюй: {st_['caption']}").strip(". "))
        clip = await _redo_story(sid, text)
    except Exception:
        logging.exception("story recaption failed")
        await c.message.answer("Не вийшло, спробуй ще раз.")
        return
    await c.message.answer_video(BufferedInputFile(clip, filename="story.mp4"), width=1080, height=1920, supports_streaming=True, caption=f"📲 Сторіс #{sid}\nПідпис: {text}",
                                reply_markup=story_kb(sid))


@router.callback_query(F.data.startswith("se:"))
async def story_own_caption(c: CallbackQuery, state: FSMContext):
    sid = int(c.data.split(":")[1])
    await state.set_state(StoryEdit.waiting)
    await state.update_data(sid=sid)
    await c.message.answer("Напиши свій короткий підпис для сторіс (до 3 рядків). «-» щоб без підпису.")
    await c.answer()


@router.message(StoryEdit.waiting, F.text, ~F.text.startswith("/"))
async def story_own_apply(m: Message, state: FSMContext):
    sid = (await state.get_data())["sid"]
    await state.clear()
    text = "" if m.text.strip() == "-" else m.text.strip()[:120]
    await m.answer("Оновлюю…")
    try:
        clip = await _redo_story(sid, text)
    except Exception:
        logging.exception("story edit failed")
        await m.answer("Не вийшло, спробуй ще раз.")
        return
    await m.answer_video(BufferedInputFile(clip, filename="story.mp4"), width=1080, height=1920, supports_streaming=True, caption=f"📲 Сторіс #{sid}\nПідпис: {text or '—'}",
                         reply_markup=story_kb(sid))


@router.callback_query(F.data.startswith("sd:"))
async def story_drop(c: CallbackQuery):
    await c.message.edit_reply_markup(reply_markup=None)
    await c.message.reply("❌ Сторіс прибрано (в Instagram нічого не йшло).")
    await c.answer()


@router.callback_query(F.data.startswith("sp:"))
async def story_publish(c: CallbackQuery):
    sid = int(c.data.split(":")[1])
    st_ = await db.get_story(sid)
    if not st_ or st_["status"] == "published":
        await c.answer("Вже опубліковано або не знайдено", show_alert=True)
        return
    if not PUBLIC_URL:
        await c.answer("Не задано PUBLIC_URL у Railway Variables", show_alert=True)
        return
    await c.message.edit_reply_markup(reply_markup=None)
    await c.answer()
    await c.message.answer("Публікую сторіс…")
    try:
        media_id = await ig.publish("story", media_server.story_url(sid), "")
    except Exception as e:
        logging.exception("story publish failed")
        await c.message.answer(f"Не вдалося опублікувати сторіс: {e}", reply_markup=story_kb(sid))
        return
    await db.set_story_published(sid, media_id)
    await c.message.answer("✅ Сторіс опубліковано! Вона буде в Instagram 24 години.")


class VideoFlow(StatesGroup):
    choose = State()


async def _download_video(bot: Bot, file_id: str) -> bytes:
    buf = BytesIO()
    await bot.download(file_id, destination=buf)
    return buf.getvalue()


async def _story_from_video(m: Message, bot: Bot, file_id: str, caption: str):
    parts = [p.strip() for p in caption.split("|")]
    title = parts[1] if len(parts) > 1 else ""
    own = parts[2] if len(parts) > 2 else ""
    await m.answer("Роблю сторіс із відео…")
    try:
        src = await _download_video(bot, file_id)
        thumb = await asyncio.to_thread(video.first_frame, src)
        text = "" if own in ("-", "без", "—") else own
        if not text and own not in ("-", "без", "—"):
            try:
                text = await ai.story_caption(thumb, title)
            except Exception:
                logging.exception("story caption failed")
                text = title
        clip = await asyncio.to_thread(video.story_from_video, src, text, await reel_music())
        sid = await db.add_story(title, text, src, clip, "video", thumb)
    except Exception:
        logging.exception("video story failed")
        await m.answer("Не вдалося обробити відео. Перевір, що воно до 20 МБ (ліміт Telegram для ботів), і надішли ще раз.")
        return
    await m.answer_video(BufferedInputFile(clip, filename="story.mp4"), width=1080, height=1920, supports_streaming=True, caption=f"📲 Сторіс #{sid}\nПідпис: {text or '—'}",
                         reply_markup=story_kb(sid))


async def _reel_from_video(m: Message, bot: Bot, file_id: str, caption: str):
    parts = [p.strip() for p in caption.split("|")]
    hint = parts[1] if len(parts) > 1 else ""
    await m.answer("Роблю Reels із відео…")
    try:
        src = await _download_video(bot, file_id)
        thumb = await asyncio.to_thread(video.first_frame, src)
        clip = await asyncio.to_thread(video.reel_from_video, src, await reel_music())
        try:
            text = await ai.post_from_photo(thumb, hint)
        except Exception:
            logging.exception("reel caption failed")
            text = hint or "Новий ролик"
        pid = await db.add_post_with_image("reel", text, thumb)
        await db.set_video(pid, clip)
    except Exception:
        logging.exception("video reel failed")
        await m.answer("Не вдалося обробити відео. Перевір, що воно до 20 МБ (ліміт Telegram для ботів), і надішли ще раз.")
        return
    await m.answer_video(BufferedInputFile(clip, filename="reel.mp4"), width=1080, height=1920, supports_streaming=True, caption="🎞 Reels зі свого відео")
    await m.answer(render(await db.get_post(pid)), reply_markup=kb(pid, media=True))


async def _video_entry(m: Message, bot: Bot, state: FSMContext, file_id: str):
    cap = (m.caption or "").strip()
    low = cap.lower()
    if low.startswith(STORY_WORDS):
        await state.clear()
        await _story_from_video(m, bot, file_id, cap)
    elif low.startswith(("рілс", "рілз", "рилс", "reel", "reels")):
        await state.clear()
        await _reel_from_video(m, bot, file_id, cap)
    else:
        await state.set_state(VideoFlow.choose)
        await state.update_data(file_id=file_id, cap=cap)
        await m.answer("Що зробити з відео?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📲 Сторіс", callback_data="vd:s"),
            InlineKeyboardButton(text="🎞 Reels", callback_data="vd:r")],
            [InlineKeyboardButton(text="📲 Сторіс без підпису", callback_data="vd:n")]]))


@router.message(F.video | F.video_note)
async def on_video(m: Message, bot: Bot, state: FSMContext):
    await _video_entry(m, bot, state, (m.video or m.video_note).file_id)


@router.message(F.document.mime_type.startswith("video/"))
async def on_video_file(m: Message, bot: Bot, state: FSMContext):
    await _video_entry(m, bot, state, m.document.file_id)


@router.callback_query(F.data.startswith("vd:"))
async def video_choice(c: CallbackQuery, bot: Bot, state: FSMContext):
    data = await state.get_data()
    if not data.get("file_id"):
        await c.answer("Надішли відео ще раз", show_alert=True)
        return
    await state.clear()
    await c.message.edit_reply_markup(reply_markup=None)
    await c.answer()
    cap = data.get("cap") or ""
    if c.data.endswith(":n"):
        await _story_from_video(c.message, bot, data["file_id"], "сторіс | | -")
    elif c.data.endswith(":s"):
        await _story_from_video(c.message, bot, data["file_id"], "сторіс | " + cap if cap else "сторіс")
    else:
        await _reel_from_video(c.message, bot, data["file_id"], "рілс | " + cap if cap else "рілс")


@router.message(Command("story"))
async def story_help(m: Message):
    await m.answer("📲 Сторіс: надішли фото з підписом\nсторіс | Назва продукту\n"
                   "Назву можна пропустити (просто «сторіс»). Свій підпис: сторіс | Назва | Текст на відео.\n"
                   "Своє відео: надішли його з підписом «сторіс» або «рілс» (без підпису запитаю, що зробити). Без тексту на відео: «сторіс | | -». До 20 МБ.\n"
                   "Я зроблю вертикальне відео з плашкою mozzarella і короткою підписом, без цін. Музика: /music.")


async def _render_and_send(m: Message, bot: Bot, file_id: str, caption: str):
    if caption.lower().startswith(STORY_WORDS):
        await _make_story(m, bot, file_id, caption)
        return
    parts = [p.strip() for p in caption.split("|")]
    is_promo = parts[0].lower() in ("акція", "акция", "акцiя")
    if is_promo:
        parts = parts[1:]
    if not parts or not parts[0]:
        await m.answer("Не бачу назви продукту. Приклад: акція | Моцарела буфала | 289 | 389")
        return

    def part(i: int) -> str:
        return parts[i] if len(parts) > i else ""

    await m.answer("Обробляю фото…")
    try:
        buf = BytesIO()
        await bot.download(file_id, destination=buf)
        if is_promo:
            # акція | Назва | Нова ціна | Стара ціна | Підзаголовок
            out = await asyncio.to_thread(
                photo.make_promo_image, buf.getvalue(), part(0), part(1), part(2), part(3)
            )
        else:
            # Назва | Ціна | Підзаголовок; якщо підзаголовка немає, підписуємо країною з фото
            subtitle = part(2)
            if not subtitle:
                try:
                    country = await ai.detect_country(buf.getvalue(), part(0))
                except Exception:
                    logging.exception("country detect failed")
                    country = ""
                subtitle = f"{country} · пряма поставка" if country else ""
            out = await asyncio.to_thread(
                photo.make_post_image, buf.getvalue(), part(0), part(1), subtitle
            )
    except Exception:
        logging.exception("photo failed")
        await m.answer("Не вдалося обробити фото, спробуй надіслати ще раз.")
        return
    await m.answer_photo(BufferedInputFile(out, filename="post.jpg"), caption="Готово ✅")

    # Claude дивиться на готову картинку й пише підпис; пост одразу іде на перевірку
    hint = ("АКЦІЯ: " if is_promo else "") + " | ".join(p for p in parts if p)
    await m.answer("Пишу підпис під це фото…")
    try:
        text = await ai.post_from_photo(out, hint)
    except Exception:
        logging.exception("caption failed")
        await m.answer("Картинка готова, але підпис написати не вдалося.")
        return
    # бот сам вирішує: звичайний пост чи Reels
    try:
        choice = await ai.choose_format(out, hint, await db.recent_published_formats(5))
    except Exception:
        logging.exception("choose_format failed")
        choice = {"format": "photo", "reason": ""}
    pid = await db.add_post_with_image(choice["format"], text, out)
    if choice["format"] == "reel":
        try:
            await m.answer("Роблю Reels…")
            clip = await reel_clip(out)
            await db.set_video(pid, clip)
            await m.answer_video(
                BufferedInputFile(clip, filename="reel.mp4"), width=1080, height=1920, supports_streaming=True,
                caption=f"🎞 Обрано Reels. {choice['reason']}".strip(),
            )
        except Exception:
            logging.exception("reel failed")
            await db.set_format(pid, "photo")
            choice = {"format": "photo", "reason": "Reels зробити не вдалося, тож звичайний пост"}
    if choice["format"] == "photo":
        await m.answer(f"🖼 Обрано звичайний пост. {choice['reason']}".strip())
    drafts = [d for d in await db.drafts_without_image(5) if d["id"] != pid]
    await m.answer(render(await db.get_post(pid)), reply_markup=kb(pid, drafts, media=True))
    if AUTO_PUBLISH:
        await _publish(m, pid)


async def _process_image(m: Message, bot: Bot, state: FSMContext, file_id: str):
    caption = (m.caption or "").strip()
    if not caption:
        # фото прийшло без підпису: запам'ятовуємо і чекаємо опис наступним повідомленням
        await state.set_state(PhotoFlow.waiting_caption)
        await state.update_data(file_id=file_id)
        await m.answer(
            "Фото отримала. Тепер надішли опис одним повідомленням:\n"
            "Назва | Ціна | Підзаголовок\n"
            "Для акції на початку додай слово «акція»:\n"
            "акція | Назва | Нова ціна | Стара ціна | Підзаголовок\n"
            "(усе, крім назви, необов'язкове)"
        )
        return
    await state.clear()
    await _render_and_send(m, bot, file_id, caption)


@router.message(F.photo)
async def on_photo(m: Message, bot: Bot, state: FSMContext):
    await _process_image(m, bot, state, m.photo[-1].file_id)


@router.message(F.document.mime_type.startswith("image/"))
async def on_image_file(m: Message, bot: Bot, state: FSMContext):
    await _process_image(m, bot, state, m.document.file_id)


@router.message(PhotoFlow.waiting_caption, F.text, ~F.text.startswith("/"))
async def on_caption(m: Message, bot: Bot, state: FSMContext):
    file_id = (await state.get_data())["file_id"]
    await state.clear()
    await _render_and_send(m, bot, file_id, m.text.strip())


@router.message(F.text, ~F.text.startswith("/"))
async def fallback(m: Message):
    await m.answer(
        "Не зрозуміла. Надішли фото продукту (краще як файл), потім опис: "
        "Назва | Ціна | Підзаголовок.\nАбо команда /plan 7 для контент-плану."
    )


async def main():
    await db.init(DATABASE_URL)
    await media_server.start()
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    if PUBLIC_URL:
        try:  # постійна кнопка дашборду біля поля введення
            await bot.set_chat_menu_button(
                chat_id=ADMIN_ID,
                menu_button=MenuButtonWebApp(text="📊 Дашборд", web_app=WebAppInfo(url=f"{PUBLIC_URL.rstrip('/')}/app")),
            )
        except Exception:
            logging.exception("menu button failed")
    try:
        from aiogram.types import BotCommand
        await bot.set_my_commands([BotCommand(command="calendar", description="Що вже заплановано"),
                                   BotCommand(command="plan", description="Контент-план на N днів"),
                                   BotCommand(command="dashboard", description="Дашборд з метриками"),
                                   BotCommand(command="report", description="Розбір результатів")])
    except Exception:
        logging.exception("set commands failed")
    # збір метрик і нагадування працюють у фоні поруч із ботом
    tasks = [asyncio.create_task(metrics.metrics_loop()), asyncio.create_task(metrics.schedule_loop(bot))]
    try:
        await dp.start_polling(bot)
    finally:
        for t in tasks:
            t.cancel()


if __name__ == "__main__":
    asyncio.run(main())
