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
