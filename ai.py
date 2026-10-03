import base64
import json
from anthropic import AsyncAnthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

BRAND = """Ти SMM-менеджер Instagram-магазину «mozzarella».
Магазин продає італійські продукти (моцарела та інші), які привозять напряму з-за кордону.
Мова: українська. Тон: теплий, апетитний, без пафосу й канцеляриту.
Не вигадуй цін, акцій, термінів доставки та фактів про товар, яких тобі не дали.
Пости пишеш для Instagram: чіпляючий перший рядок, коротко, заклик до дії, 3-6 доречних хештегів."""


def _text(msg) -> str:
    # у відповіді може бути блок thinking перед текстом, тому беремо лише text-блоки
    return "".join(b.text for b in msg.content if b.type == "text")


def _extract_json(raw: str) -> list[dict]:
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("У відповіді немає JSON-масиву")
    return json.loads(raw[start : end + 1])


async def generate_plan(days: int, note: str = "") -> list[dict]:
    prompt = (
        f"Склади контент-план для Instagram на {days} днів: один пост на день.\n"
        "Чергуй формати (photo, carousel, reel) і теми: продукт, історія походження, "
        "рецепт, закулісся доставки, відповіді на питання клієнтів.\n"
        "Поверни ТІЛЬКИ JSON-масив без пояснень. Кожен елемент має поля:\n"
        '  "format": "photo" | "carousel" | "reel",\n'
        '  "slot": день тижня і година публікації, напр. "Вт 12:00",\n'
        '  "text": готовий підпис до поста (400-700 символів, з хештегами),\n'
        '  "photo_idea": коротко, що має бути на фото чи відео.\n'
    )
    if note:
        prompt += f"\nПобажання власника: {note}"
    msg = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=10000,
        system=BRAND,
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_json(_text(msg))


async def revise_post(text: str, instruction: str) -> str:
    msg = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4000,
        system=BRAND,
        messages=[
            {
                "role": "user",
                "content": f"Ось поточний пост:\n\n{text}\n\nПравка від власника: {instruction}\n\n"
                "Поверни ТІЛЬКИ новий текст поста, без пояснень.",
            }
        ],
    )
    return _text(msg).strip()


async def post_from_photo(photo_jpeg: bytes, hint: str = "", existing: str = "") -> str:
    """Пише підпис під фото (Claude дивиться на картинку). Якщо є existing, переписує пост з плану під це фото."""
    b64 = base64.b64encode(photo_jpeg).decode()
    if existing:
        task = (
            "Ось пост із контент-плану:\n\n" + existing + "\n\n"
            "Власник надав фото, яке має до нього йти. Перепиши пост так, щоб він пасував до того, "
            "що реально на фото. Збережи тему, тон, структуру та хештеги, прибери те, що не збігається з фото."
        )
    else:
        task = "Напиши підпис для Instagram-поста до цього фото."
    if hint:
        task += f"\n\nДані від власника про товар (єдине джерело цін і фактів): {hint}"
    task += (
        "\n\nНе вигадуй цін, акцій і фактів, яких немає в даних чи на фото. "
        "Поверни ТІЛЬКИ готовий текст поста, без пояснень."
    )
    msg = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        system=BRAND,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
                    },
                    {"type": "text", "text": task},
                ],
            }
        ],
    )
    return _text(msg).strip()


async def choose_format(photo_jpeg: bytes, hint: str, recent: list[str]) -> dict:
    """Claude вирішує, чим краще публікувати це фото: звичайним постом чи Reels."""
    b64 = base64.b64encode(photo_jpeg).decode()
    task = (
        "Обери формат публікації для цього фото в Instagram: \"photo\" або \"reel\".\n"
        "Орієнтири: Reels зазвичай дають більше охоплення нових людей, тож добре для апетитних "
        "красивих кадрів і новинок. Звичайне фото краще, коли на картинці багато тексту, цін чи умов акції, "
        "які треба встигнути прочитати.\n"
        f"Останні опубліковані формати (від нових до старих): {', '.join(recent) or 'ще немає'}. "
        "Не став reel більше двох разів поспіль, чергуй для різноманіття.\n"
        f"Дані про товар: {hint or 'немає'}\n\n"
        'Поверни ТІЛЬКИ JSON: {"format": "photo" | "reel", "reason": "одне речення українською"}'
    )
    msg = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=300,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": task},
                ],
            }
        ],
    )
    raw = _text(msg)
    start, end = raw.find("{"), raw.rfind("}")
    data = json.loads(raw[start : end + 1])
    fmt = "reel" if data.get("format") == "reel" else "photo"
    return {"format": fmt, "reason": str(data.get("reason", ""))}
