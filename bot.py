import asyncio
import logging
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
    Message,
)

import ai
import db
import ig
import media_server
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
    return (
        f"📝 Пост #{p['id']} · {p['format']} · {p['slot']}\n\n"
        f"{p['text']}\n\n"
        f"📷 Фото: {p['photo_idea']}"
    )


@router.message(Command("start"))
async def start(m: Message):
    await m.answer(
        "Привіт! Команди:\n"
        "/plan 7 — контент-план на 7 днів\n"
        "/plan 7 більше рецептів — з побажанням\n\n"
        "Обробка фото: надішли фото продукту (краще як файл), потім опис:\n"
        "Назва | Ціна | Підзаголовок\n"
        "Наприклад: Моцарела буфала | 389 | Свіжа поставка\n\n"
        "Акційне фото (з плашкою АКЦІЯ, знижкою і закресленою ціною):\n"
        "акція | Назва | Нова ціна | Стара ціна | Підзаголовок\n"
        "Наприклад: акція | Моцарела буфала | 289 | 389 | Діє до 15.10\n\n"
        "Опис можна додати і одразу в підпис до фото."
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


@router.message(Command("ig_status"))
async def ig_status(m: Message):
    info = await ig.status()
    if not info:
        await m.answer("Instagram ще не підключений. Команда: /ig_connect")
        return
    await m.answer(f"Instagram: @{info['ig_username']}, сторінка «{info['page']}» ✅")


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
    for it in items:
        pid = await db.add_post(
            it.get("format", "photo"), it.get("slot", ""), it["text"], it.get("photo_idea", "")
        )
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
            clip = await db.get_video(pid) or await asyncio.to_thread(video.make_reel, image)
        except Exception:
            logging.exception("reel failed")
            await c.message.answer("Reels зробити не вдалося.")
            return
        await db.set_video(pid, clip)
        await db.set_format(pid, "reel")
        await c.message.answer_video(BufferedInputFile(clip, filename="reel.mp4"), caption="🎞 Reels")
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
            clip = await asyncio.to_thread(video.make_reel, image)
            await db.set_video(old_id, clip)
            await c.message.answer_video(BufferedInputFile(clip, filename="reel.mp4"), caption="🎞 Reels")
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


async def _render_and_send(m: Message, bot: Bot, file_id: str, caption: str):
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
            clip = await asyncio.to_thread(video.make_reel, out)
            await db.set_video(pid, clip)
            await m.answer_video(
                BufferedInputFile(clip, filename="reel.mp4"),
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
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
