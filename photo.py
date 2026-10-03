"""Автообробка фото продукту: кадрування 4:5, корекція кольору, плашки, логотип, акційний режим."""
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

W, H = 1080, 1350  # формат 4:5, оптимальний для стрічки Instagram
ASSETS = Path(__file__).parent / "assets"

# Один параметр для розміру всіх написів і плашок: менше число = дрібніше, більше = крупніше.
TEXT_SCALE = 0.52


def s(n: float) -> int:
    """Масштабує розмір під TEXT_SCALE."""
    return max(1, int(round(n * TEXT_SCALE)))


CREAM = (246, 239, 227)
GREEN = (47, 107, 58)
RED = (200, 56, 46)
WHITE = (255, 255, 255)
YELLOW = (255, 208, 0)
INK = (28, 28, 28)

BRAND = "mozzarella"
DEFAULT_SUBTITLE = "Європа · пряма поставка"
MARGIN = 52


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / name), size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _fit_title(draw, text: str, max_w: int, max_lines: int = 2, max_size: int = 96):
    """Підбирає найбільший розмір шрифту, при якому заголовок вміщається в max_lines рядків."""
    for size in range(max_size, 24, -2):
        font = _font("Inter-Bold.otf", size)
        lines = _wrap(draw, text, font, max_w)
        if len(lines) <= max_lines and all(draw.textlength(l, font=font) <= max_w for l in lines):
            return font, lines
    font = _font("Inter-Bold.otf", 24)
    return font, _wrap(draw, text, font, max_w)[:max_lines]


def _enhance(img: Image.Image) -> Image.Image:
    # м'яка автокорекція: половина ефекту, щоб не перетемнювати світлі фото
    stretched = ImageOps.autocontrast(img, cutoff=0.5)
    img = Image.blend(img, stretched, 0.5)
    img = ImageEnhance.Color(img).enhance(1.08)
    img = ImageEnhance.Contrast(img).enhance(1.04)
    img = ImageEnhance.Sharpness(img).enhance(1.15)
    return img


def _gradient(height: int, max_alpha: int = 215) -> Image.Image:
    grad = Image.new("RGBA", (W, height))
    px = grad.load()
    for y in range(height):
        a = int(max_alpha * (y / height) ** 1.6)
        for x in range(W):
            px[x, y] = (15, 15, 15, a)
    return grad


def _format_price(price: str) -> str:
    price = price.strip()
    if not price:
        return ""
    return f"{price} грн" if price.replace(",", "").replace(".", "").isdigit() else price


def _prepare(photo_bytes: bytes) -> Image.Image:
    img = Image.open(BytesIO(photo_bytes))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img = ImageOps.fit(img, (W, H), method=Image.LANCZOS, centering=(0.5, 0.5))
    return _enhance(img).convert("RGBA")


def _draw_logo(d: ImageDraw.ImageDraw) -> int:
    """Малює логотип зліва вгорі, повертає нижню межу плашки."""
    f_logo = _font("Inter-Bold.otf", s(52))
    h = s(104)
    tw = d.textlength(BRAND, font=f_logo)
    d.rounded_rectangle(
        (MARGIN, MARGIN, MARGIN + tw + s(72), MARGIN + h), radius=h // 2, fill=GREEN
    )
    d.text((MARGIN + s(36), MARGIN + h / 2), BRAND, font=f_logo, fill=CREAM, anchor="lm")
    return MARGIN + h


def _save(img: Image.Image) -> bytes:
    out = BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=92, optimize=True)
    return out.getvalue()


def make_post_image(
    photo_bytes: bytes, title: str, price: str = "", subtitle: str = ""
) -> bytes:
    img = _prepare(photo_bytes)

    # затемнення знизу під текст
    grad_h = int(H * 0.36)
    img.alpha_composite(_gradient(grad_h), (0, H - grad_h))

    d = ImageDraw.Draw(img)
    _draw_logo(d)

    # ціна: червона плашка справа вгорі
    price_text = _format_price(price)
    if price_text:
        f_price = _font("Inter-Bold.otf", s(70))
        ph = s(126)
        pw = d.textlength(price_text, font=f_price)
        x1 = W - MARGIN
        x0 = x1 - pw - s(88)
        d.rounded_rectangle((x0, MARGIN, x1, MARGIN + ph), radius=ph // 2, fill=RED)
        d.text(((x0 + x1) / 2, MARGIN + ph / 2), price_text, font=f_price, fill=WHITE, anchor="mm")

    # назва продукту знизу
    f_sub = _font("Inter-Regular.otf", s(50))
    sub = subtitle.strip() or DEFAULT_SUBTITLE
    title_font, lines = _fit_title(d, title.strip(), W - 2 * MARGIN, max_size=s(130))
    line_h = int(title_font.size * 1.15)
    y = H - MARGIN - s(50) - s(46) - line_h * len(lines)
    for line in lines:
        d.text((MARGIN, y), line, font=title_font, fill=WHITE)
        y += line_h
    d.rectangle((MARGIN, y + s(18), MARGIN + s(130), y + s(18) + max(4, s(9))), fill=RED)
    d.text((MARGIN, y + s(18) + s(44)), sub, font=f_sub, fill=CREAM)

    return _save(img)


def _to_number(value: str):
    try:
        return float(value.strip().replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def _discount_percent(price: str, old_price: str):
    new, old = _to_number(price), _to_number(old_price)
    if new and old and old > new > 0:
        return round((1 - new / old) * 100)
    return None


def make_promo_image(
    photo_bytes: bytes,
    title: str,
    price: str = "",
    old_price: str = "",
    subtitle: str = "",
) -> bytes:
    """Акційна картинка: плашка АКЦІЯ!, нова ціна, закреслена стара, відсоток знижки."""
    img = _prepare(photo_bytes)

    # затемнення зверху (під плашку) і знизу (під текст)
    top_h = int(H * 0.22)
    img.alpha_composite(ImageOps.flip(_gradient(top_h, 110)), (0, 0))
    bottom_h = int(H * 0.44)
    img.alpha_composite(_gradient(bottom_h, 205), (0, H - bottom_h))

    d = ImageDraw.Draw(img)
    logo_bottom = _draw_logo(d)

    # відсоток знижки: жовте коло справа вгорі
    pct = _discount_percent(price, old_price)
    if pct:
        diam = s(290)
        x0, y0 = W - MARGIN - diam, MARGIN - s(10)
        d.ellipse((x0, y0, x0 + diam, y0 + diam), fill=YELLOW)
        f_pct = _font("Inter-Bold.otf", s(86))
        d.text((x0 + diam / 2, y0 + diam / 2), f"-{pct}%", font=f_pct, fill=RED,
               anchor="mm", stroke_width=1, stroke_fill=RED)

    # плашка АКЦІЯ + знак оклику
    stroke = max(2, s(5))
    size = s(210)
    icon_d = s(170)
    gap, pad = s(36), s(66)
    while True:
        f_promo = _font("Inter-Bold.otf", size)
        text_w = d.textlength("АКЦІЯ", font=f_promo) + 2 * stroke
        banner_w = pad + text_w + gap + icon_d + pad
        if banner_w <= W - 2 * MARGIN or size <= 60:
            break
        size -= 4
    banner_h = s(270)
    by0 = logo_bottom + s(40)
    d.rounded_rectangle((MARGIN, by0, MARGIN + banner_w, by0 + banner_h),
                        radius=s(50), fill=RED)
    d.text((MARGIN + pad, by0 + banner_h / 2), "АКЦІЯ", font=f_promo, fill=WHITE,
           anchor="lm", stroke_width=stroke, stroke_fill=WHITE)
    cx = MARGIN + pad + text_w + gap + icon_d / 2
    cy = by0 + banner_h / 2
    d.ellipse((cx - icon_d / 2, cy - icon_d / 2, cx + icon_d / 2, cy + icon_d / 2), fill=YELLOW)
    f_excl = _font("Inter-Bold.otf", s(136))
    d.text((cx, cy + 2), "!", font=f_excl, fill=RED, anchor="mm",
           stroke_width=max(1, s(4)), stroke_fill=RED)

    # знизу вгору: підзаголовок, ряд цін, назва
    y_bottom = H - MARGIN
    if subtitle.strip():
        f_sub = _font("Inter-Regular.otf", s(54))
        d.text((MARGIN, y_bottom), subtitle.strip(), font=f_sub, fill=CREAM, anchor="ls")
        y_bottom -= s(54) + s(40)

    price_text = _format_price(price)
    if price_text:
        row_h = s(176)
        f_new = _font("Inter-Bold.otf", s(120))
        nw = d.textlength(price_text, font=f_new)
        row_y1 = y_bottom
        row_y0 = row_y1 - row_h
        padx = s(56)
        d.rounded_rectangle((MARGIN, row_y0, MARGIN + nw + 2 * padx, row_y1),
                            radius=row_h // 2, fill=YELLOW)
        d.text((MARGIN + padx + nw / 2, (row_y0 + row_y1) / 2 + 2), price_text,
               font=f_new, fill=INK, anchor="mm")
        old_text = _format_price(old_price)
        if old_text:
            f_old = _font("Inter-Bold.otf", s(78))
            ox = MARGIN + nw + 2 * padx + s(50)
            oy = (row_y0 + row_y1) / 2
            d.text((ox, oy), old_text, font=f_old, fill=CREAM, anchor="lm")
            ow = d.textlength(old_text, font=f_old)
            d.line((ox - 6, oy + 2, ox + ow + 6, oy + 2), fill=RED, width=max(4, s(10)))
        y_bottom = row_y0 - s(40)

    title_font, lines = _fit_title(d, title.strip(), W - 2 * MARGIN, max_size=s(120))
    line_h = int(title_font.size * 1.15)
    y = y_bottom - line_h * len(lines)
    for line in lines:
        d.text((MARGIN, y), line, font=title_font, fill=WHITE)
        y += line_h

    return _save(img)
