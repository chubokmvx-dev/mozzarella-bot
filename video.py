"""Reels із фото: вертикальне відео 9:16 з повільним наближенням."""
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageFilter, ImageOps

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


def make_reel(poster_jpeg: bytes) -> bytes:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    frames = DURATION * FPS
    with tempfile.TemporaryDirectory() as d:
        img, out = Path(d) / "frame.jpg", Path(d) / "reel.mp4"
        _frame(poster_jpeg).save(img, quality=95)
        # повільне наближення до 1.07x, не зрізає краї тексту
        vf = (
            f"scale={RW * 3 // 2}:{RH * 3 // 2},"
            f"zoompan=z='min(zoom+0.0003,1.08)':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={RW}x{RH}:fps={FPS},"
            "format=yuv420p"
        )
        cmd = [
            ffmpeg, "-y", "-i", str(img),
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",  # беззвучна доріжка, Instagram її любить
            "-vf", vf, "-frames:v", str(frames),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "96k", "-shortest", "-movflags", "+faststart",
            str(out),
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=170)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode(errors="ignore")[-600:])
        return out.read_bytes()
