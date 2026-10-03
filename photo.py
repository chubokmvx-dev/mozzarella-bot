"""Автообробка фото продукту: кадрування 4:5, корекція кольору, плашка ціни, логотип."""
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

W, H = 1080, 1350  # формат 4:5, оптимальний для стрічки Instagram
ASSETS = Path(__file__).parent / "assets"

CREAM = (246, 239, 227)
GREEN = (47, 107, 58)
RED = (200, 56, 46)
WHITE = (255, 255, 255)

BRAND = "mozzarella"
DEFAULT_SUBTITLE = "Італія · пряма поставка"


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
    for size in range(max_size, 40, -4):
        font = _font("Inter-Bold.otf", size)
        lines = _wrap(draw, text, font, max_w)
        if len(lines) <= max_lines and all(draw.textlength(l, font=font) <= max_w for l in lines):
            return font, lines
    font = _font("Inter-Bold.otf", 40)
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


def make_post_image(
    photo_bytes: bytes, title: str, price: str = "", subtitle: str = ""
) -> bytes:
    img = Image.open(BytesIO(photo_bytes))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img = ImageOps.fit(img, (W, H), method=Image.LANCZOS, centering=(0.5, 0.5))
    img = _enhance(img)

    # затемнення знизу під текст
    grad_h = int(H * 0.42)
    img = img.convert("RGBA")
    img.alpha_composite(_gradient(grad_h), (0, H - grad_h))

    d = ImageDraw.Draw(img)
    margin = 56

    # логотип: зелена плашка зліва вгорі
    f_logo = _font("Inter-Bold.otf", 40)
    tw = d.textlength(BRAND, font=f_logo)
    d.rounded_rectangle(
        (margin, margin, margin + tw + 56, margin + 80), radius=40, fill=GREEN
    )
    d.text((margin + 28, margin + 40), BRAND, font=f_logo, fill=CREAM, anchor="lm")

    # ціна: червона плашка справа вгорі
    price_text = _format_price(price)
    if price_text:
        f_price = _font("Inter-Bold.otf", 52)
        pw = d.textlength(price_text, font=f_price)
        x1 = W - margin
        x0 = x1 - pw - 64
        d.rounded_rectangle((x0, margin, x1, margin + 96), radius=48, fill=RED)
        d.text(((x0 + x1) / 2, margin + 48), price_text, font=f_price, fill=WHITE, anchor="mm")

    # назва продукту знизу
    f_sub = _font("Inter-Regular.otf", 36)
    sub = subtitle.strip() or DEFAULT_SUBTITLE
    title_font, lines = _fit_title(d, title.strip(), W - 2 * margin)
    line_h = int(title_font.size * 1.15)
    y = H - margin - 36 - 30 - line_h * len(lines)
    for line in lines:
        d.text((margin, y), line, font=title_font, fill=WHITE)
        y += line_h
    d.rectangle((margin, y + 14, margin + 96, y + 20), fill=RED)
    d.text((margin, y + 40), sub, font=f_sub, fill=CREAM)

    out = BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=92, optimize=True)
    return out.getvalue()


YELLOW = (255, 208, 0)
INK = (28, 28, 28)


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
    """Акційна картинка: велика плашка АКЦІЯ!, нова ціна, закреслена стара, відсоток знижки."""
    img = Image.open(BytesIO(photo_bytes))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img = ImageOps.fit(img, (W, H), method=Image.LANCZOS, centering=(0.5, 0.5))
    img = _enhance(img).convert("RGBA")

    # затемнення зверху (під плашку) і знизу (під текст)
    img.alpha_composite(ImageOps.flip(_gradient(330, 120)), (0, 0))
    bottom_h = int(H * 0.5)
    img.alpha_composite(_gradient(bottom_h, 205), (0, H - bottom_h))

    d = ImageDraw.Draw(img)
    margin = 56

    # логотип
    f_logo = _font("Inter-Bold.otf", 40)
    tw = d.textlength(BRAND, font=f_logo)
    d.rounded_rectangle((margin, margin, margin + tw + 56, margin + 80), radius=40, fill=GREEN)
    d.text((margin + 28, margin + 40), BRAND, font=f_logo, fill=CREAM, anchor="lm")

    # відсоток знижки: жовте коло справа вгорі
    pct = _discount_percent(price, old_price)
    if pct:
        diam = 214
        x0, y0 = W - margin - diam, margin - 8
        d.ellipse((x0, y0, x0 + diam, y0 + diam), fill=YELLOW)
        f_pct = _font("Inter-Bold.otf", 62)
        d.text((x0 + diam / 2, y0 + diam / 2), f"-{pct}%", font=f_pct, fill=RED,
               anchor="mm", stroke_width=2, stroke_fill=RED)

    # плашка АКЦІЯ + знак оклику
    stroke = 4
    size = 150
    icon_d = 120
    gap, pad = 26, 48
    while True:
        f_promo = _font("Inter-Bold.otf", size)
        text_w = d.textlength("АКЦІЯ", font=f_promo) + 2 * stroke
        banner_w = pad + text_w + gap + icon_d + pad
        if banner_w <= W - 2 * margin or size <= 80:
            break
        size -= 8
    banner_h = 190
    by0 = 180
    d.rounded_rectangle((margin, by0, margin + banner_w, by0 + banner_h), radius=36, fill=RED)
    d.text((margin + pad, by0 + banner_h / 2), "АКЦІЯ", font=f_promo, fill=WHITE,
           anchor="lm", stroke_width=stroke, stroke_fill=WHITE)
    cx = margin + pad + text_w + gap + icon_d / 2
    cy = by0 + banner_h / 2
    d.ellipse((cx - icon_d / 2, cy - icon_d / 2, cx + icon_d / 2, cy + icon_d / 2), fill=YELLOW)
    f_excl = _font("Inter-Bold.otf", 96)
    d.text((cx, cy + 2), "!", font=f_excl, fill=RED, anchor="mm", stroke_width=3, stroke_fill=RED)

    # знизу вгору: підзаголовок, ряд цін, назва
    y_bottom = H - margin
    if subtitle.strip():
        f_sub = _font("Inter-Regular.otf", 38)
        d.text((margin, y_bottom), subtitle.strip(), font=f_sub, fill=CREAM, anchor="ls")
        y_bottom -= 38 + 32

    price_text = _format_price(price)
    if price_text:
        row_h = 124
        f_new = _font("Inter-Bold.otf", 84)
        nw = d.textlength(price_text, font=f_new)
        row_y1 = y_bottom
        row_y0 = row_y1 - row_h
        d.rounded_rectangle((margin, row_y0, margin + nw + 80, row_y1), radius=62, fill=YELLOW)
        d.text((margin + 40 + nw / 2, (row_y0 + row_y1) / 2 + 2), price_text,
               font=f_new, fill=INK, anchor="mm")
        old_text = _format_price(old_price)
        if old_text:
            f_old = _font("Inter-Bold.otf", 54)
            ox = margin + nw + 80 + 36
            oy = (row_y0 + row_y1) / 2
            d.text((ox, oy), old_text, font=f_old, fill=CREAM, anchor="lm")
            ow = d.textlength(old_text, font=f_old)
            d.line((ox - 6, oy + 2, ox + ow + 6, oy + 2), fill=RED, width=7)
        y_bottom = row_y0 - 30

    title_font, lines = _fit_title(d, title.strip(), W - 2 * margin, max_size=84)
    line_h = int(title_font.size * 1.15)
    y = y_bottom - line_h * len(lines)
    for line in lines:
        d.text((margin, y), line, font=title_font, fill=WHITE)
        y += line_h

    out = BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=92, optimize=True)
    return out.getvalue()
