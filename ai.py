import base64
import json
from anthropic import AsyncAnthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

BRAND = """Ти SMM-менеджер Instagram-магазину «mozzarella».
Магазин продає європейські продукти, які привозять напряму з-за кордону. Це не лише Італія: є й інші країни.
Країну походження товару визнач за фото (упаковка, етикетка, прапор, назва, мова написів) або за даними від власника.
Якщо країну можна визначити впевнено, пиши саме її. Якщо не впевнений, не вгадуй і не згадуй конкретну країну, пиши загально: «смак Європи».
Не став Італію за замовчуванням.
Коли доречна фраза про доставку, використовуй формулу: «Ми привозимо європейські продукти напряму з-за кордону, щоб смак <країни походження> був у вас вдома.» (наприклад: «щоб смак Іспанії був у вас вдома», «щоб смак Франції був у вас вдома»).
Мова: українська. Тон: теплий, апетитний, без пафосу й канцеляриту.
Не вигадуй цін, акцій, термінів доставки та фактів про товар, яких тобі не дали.
Пости пишеш для Instagram: чіпляючий перший рядок, коротко, 3-6 доречних хештегів.
Не додавай закликів замовляти чи писати: жодних фраз на кшталт «Хочете замовити? Пишіть у direct», «замовляйте», «пишіть нам в особисті». Пост закінчується описом товару, фразою про доставку (де доречно) та хештегами."""


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
        "ВАЖЛИВО: у плані лише два формати, обидва робляться з фото товару, яке власник надішле боту:\n"
        '  - "photo": звичайний пост з фото продукту;\n'
        '  - "reel": Reels, зроблений із фото продукту (повільне наближення, без зйомки відео).\n'
        "Жодних рецептів, відео з готуванням, каруселей, зйомки закулісся чи інших відео. "
        "Кожен пост це один конкретний продукт із фото.\n"
        "Теми: презентація продукту, його смак і чим він хороший, країна походження, новинка в наявності, "
        "чим продукт хороший, коли доречно: акція (лише якщо власник дав умови). "
        "Не вигадуй конкретних продуктів, цін і фактів: де потрібен товар, пиши «[продукт]» "
        "або тему загально, країна походження може бути різною, не лише Італія. "
        "Чергуй photo та reel, приблизно порівну.\n"
        "Поверни ТІЛЬКИ JSON-масив без пояснень. Кожен елемент має поля:\n"
        '  "format": "photo" | "reel",\n'
        f'  "day": номер дня плану від 1 до {days} (один пост на день),\n'
        '  "time": година публікації, напр. "12:00",\n'
        '  "text": готовий підпис до поста (400-700 символів, з хештегами),\n'
        '  "photo_idea": який саме продукт і який кадр сфотографувати (одне речення).\n'
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


async def detect_country(photo_bytes: bytes, hint: str = "") -> str:
    """Країна походження товару за фото (українською, називний відмінок) або порожній рядок, якщо не впевнений."""
    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img.thumbnail((1024, 1024))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()
    task = (
        "З якої країни цей продукт? Дивись на упаковку, етикетку, написи, прапори, мову, тип товару. "
        f"Назва від власника: {hint or 'немає'}.\n"
        "Відповідай ОДНИМ словом: назва країни українською в називному відмінку (наприклад: Італія, Іспанія, Франція, Греція). "
        "Якщо не впевнений, відповідай словом: невідомо."
    )
    msg = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=30,
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
    country = _text(msg).strip().strip(".").split("\n")[0]
    return "" if not country or country.lower().startswith("невід") or len(country) > 25 else country


async def analyze_week(posts: list[dict]) -> str:
    """Аналіз метрик опублікованих постів: що спрацювало краще й що робити далі."""
    msg = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2500,
        system=BRAND,
        messages=[
            {
                "role": "user",
                "content": (
                    "Ось дані по опублікованих постах Instagram-магазину (JSON). Поля метрик: reach охоплення, "
                    "views перегляди, likes/comments/shares/saved реакції, total_interactions сума взаємодій, "
                    "ig_reels_avg_watch_time середній час перегляду Reels у мілісекундах. after_24h і after_7d це "
                    "знімки через 24 години й 7 днів, latest актуальний стан.\n\n"
                    f"{json.dumps(posts, ensure_ascii=False)}\n\n"
                    "Зроби короткий розбір українською для власника, без вступів:\n"
                    "1. Який пост показав себе найкраще й чому так (за даними, а не вигадками).\n"
                    "2. Порівняння форматів photo і reel, якщо є обидва.\n"
                    "3. Який пост відстав.\n"
                    "4. 2-3 конкретні поради на наступний тиждень.\n"
                    "Якщо постів мало (менше 5), прямо скажи, що висновки попередні. "
                    "Не вигадуй цифр, яких немає в даних, і не роби категоричних висновків із малої вибірки. "
                    "Формат: короткі абзаци, без таблиць, без заголовків markdown, до 1500 символів."
                ),
            }
        ],
    )
    return _text(msg).strip()
