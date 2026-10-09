"""Reels із фото: вертикальне відео 9:16 з повільним наближенням."""
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFilter, ImageOps

RW, RH = 1080, 1920
DURATION = 8  # секунд
FPS = 30


def _frame(poster_jpeg: bytes) -> Image.Image:
    """Готова картинка по центру кадру 9:16, фон: її ж розмите й затемнене розтягування."""
    poster = Image.open(BytesIO(poster_jpeg)).convert("RGB")
    bg = ImageOps.fit(poster, (RW, RH), method=Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new("RGB", (RW, RH), (0, 0, 0)), 0.35)
    fg = poster.resize((RW, int(poster.height * RW / poster.width)), Image.LANCZOS)
    bg.paste(fg, (0, (RH - fg.height) // 2))
    return bg


def _synth_args(off: int = 1):
    """Власна музика без авторських прав: тихий ambient із 4 акордів (Am-F-C-G), що плавно змінюються."""
    chords = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (261.63, 329.63, 392.0), (196.0, 246.94, 293.66)]
    seg = DURATION / 4
    ins, labels = [], []
    for i, ch in enumerate(chords):
        expr = "+".join(f"sin(2*PI*{f}*t)" for f in ch) + "+0.5*sin(2*PI*" + f"{ch[0] / 2}" + "*t)"
        ins += ["-f", "lavfi", "-t", f"{seg + 0.4}", "-i", f"aevalsrc='0.12*({expr})':s=44100:c=stereo"]
        labels.append(f"[{i + off}:a]afade=t=in:d=0.4,afade=t=out:st={seg:.2f}:d=0.4[c{i}]")
    mix = "".join(f"[c{i}]" for i in range(4)) + f"concat=n=4:v=0:a=1,lowpass=f=1400,aecho=0.8:0.6:300:0.35,afade=t=in:d=1,afade=t=out:st={DURATION - 1.5}:d=1.5,volume=1.8[aud]"
    return ins, ";".join(labels + [mix])


def make_reel(poster_jpeg: bytes, music: bytes | None = None, synth: bool = True, overlay: Image.Image | None = None) -> bytes:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    frames = DURATION * FPS
    with tempfile.TemporaryDirectory() as d:
        img, out = Path(d) / "frame.jpg", Path(d) / "reel.mp4"
        _frame(poster_jpeg).save(img, quality=95)
        off = 1
        ov_in = []
        if overlay is not None:       # плашка й підпис поверх відео (для сторіс), з плавною появою
            ovp = Path(d) / "overlay.png"
            overlay.save(ovp)
            ov_in = ["-loop", "1", "-t", str(DURATION), "-i", str(ovp)]
            off = 2
        # повільне наближення до 1.07x, не зрізає краї тексту
        vf = (
            f"scale={RW * 3 // 2}:{RH * 3 // 2},"
            f"zoompan=z='min(zoom+0.0003,1.08)':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={RW}x{RH}:fps={FPS},"
            "format=yuv420p"
        )
        if music:
            mp = Path(d) / "music.bin"
            mp.write_bytes(music)
            ains = ["-i", str(mp)]
            # випадкова точка старту не потрібна: беремо початок, плавне вхід/вихід
            fc = f"[{off}:a]atrim=0:{DURATION},asetpts=PTS-STARTPTS,afade=t=in:d=0.8,afade=t=out:st={DURATION - 1.5}:d=1.5,volume=0.9[aud]"
        elif synth:
            ains, fc = _synth_args(off)
        else:
            ains, fc = ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"], f"[{off}:a]atrim=0:{DURATION}[aud]"
        cmd = [
            ffmpeg, "-y", "-i", str(img), *ov_in, *ains,
            "-filter_complex", (f"[0:v]{vf}[bg];[1:v]format=rgba,fade=t=in:st=0.4:d=0.7:alpha=1[ov];[bg][ov]overlay=0:0:shortest=1,format=yuv420p[vid];{fc}"
                                if overlay is not None else f"[0:v]{vf}[vid];{fc}"),
            "-map", "[vid]", "-map", "[aud]",
            "-frames:v", str(frames), "-t", str(DURATION),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            str(out),
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=170)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode(errors="ignore")[-600:])
        return out.read_bytes()


def story_overlay(caption: str, brand: str = "mozzarella") -> Image.Image:
    """Прозорий шар 1080x1920: зелена плашка з назвою зверху й короткий підпис знизу (поза зонами інтерфейсу Stories)."""
    from photo import CREAM, GREEN, _font, _wrap

    layer = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f_logo = _font("Inter-Bold.otf", 64)
    h = 124
    tw = d.textlength(brand, font=f_logo)
    x0, y0 = 70, 230                     # трохи нижче, щоб не накривало аватар і назву акаунта в Stories
    d.rounded_rectangle((x0, y0, x0 + tw + 90, y0 + h), radius=h // 2, fill=GREEN)
    d.text((x0 + 45, y0 + h / 2), brand, font=f_logo, fill=CREAM, anchor="lm")
    import re
    cap = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200d]", "", caption).strip()   # шрифт без емодзі
    if cap:
        f = _font("Inter-Bold.otf", 66)
        lines = _wrap(d, cap, f, 860)[:3]
        lh = 86
        bh = len(lines) * lh + 70
        bottom = 1560                    # нижні ~350 px у Stories займає поле відповіді
        top = bottom - bh
        d.rounded_rectangle((70, top, RW - 70, bottom), radius=44, fill=(14, 22, 16, 205))
        y = top + 35
        for ln in lines:
            d.text((RW / 2, y + lh / 2), ln, font=f, fill=CREAM, anchor="mm")
            y += lh
    return layer


def make_story(photo_bytes: bytes, caption: str, music: bytes | None = None, synth: bool = True) -> bytes:
    return make_reel(photo_bytes, music, synth, overlay=story_overlay(caption))
