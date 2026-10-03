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
import photo
from config import ADMIN_ID, BOT_TOKEN, DATABASE_URL

logging.basicConfig(level=logging.INFO)

router = Router()
# бот відповідає лише власнику
router.message.filter(F.from_user.id == ADMIN_ID)
router.callback_query.filter(F.from_user.id == ADMIN_ID)


class Edit(StatesGroup):
    waiting = State()


def kb(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Підтвердити", callback_data=f"ok:{post_id}"),
                InlineKeyboardButton(text="✏️ Змінити", callback_data=f"edit:{post_id}"),
                InlineKeyboardButton(text="❌ Скасувати", callback_data=f"no:{post_id}"),
            ]
        ]
    )


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
        "Обробка фото: надішли фото продукту з підписом\n"
        "Назва | Ціна | Підзаголовок (ціна і підзаголовок необов'язкові)\n"
        "Наприклад: Моцарела буфала | 389 | Свіжа поставка з Кампанії\n"
        "Для найкращої якості надсилай фото як файл."
    )


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
    await m.answer(render(await db.get_post(pid)), reply_markup=kb(pid))


async def _process_image(m: Message, bot: Bot, file_id: str):
    caption = (m.caption or "").strip()
    if not caption:
        await m.answer(
            "Додай підпис до фото у форматі: Назва | Ціна\n"
            "Наприклад: Моцарела буфала | 389"
        )
        return
    parts = [p.strip() for p in caption.split("|")]
    title = parts[0]
    price = parts[1] if len(parts) > 1 else ""
    subtitle = parts[2] if len(parts) > 2 else ""
    await m.answer("Обробляю фото…")
    try:
        buf = BytesIO()
        await bot.download(file_id, destination=buf)
        out = await asyncio.to_thread(
            photo.make_post_image, buf.getvalue(), title, price, subtitle
        )
    except Exception:
        logging.exception("photo failed")
        await m.answer("Не вдалося обробити фото, спробуй надіслати ще раз.")
        return
    await m.answer_photo(BufferedInputFile(out, filename="post.jpg"), caption="Готово ✅")


@router.message(F.photo)
async def on_photo(m: Message, bot: Bot):
    await _process_image(m, bot, m.photo[-1].file_id)


@router.message(F.document.mime_type.startswith("image/"))
async def on_image_file(m: Message, bot: Bot):
    await _process_image(m, bot, m.document.file_id)


async def main():
    await db.init(DATABASE_URL)
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
