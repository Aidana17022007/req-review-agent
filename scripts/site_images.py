"""Картинки сайта: скриншоты интерфейса → WebP (site/img/). Запуск: python scripts/site_images.py

Полные экраны — 1200 px по ширине; иллюстрации карточек — кропы реального интерфейса 960×600; постер видео.
Источник — docs/assets/screenshot-*.png (их пересъёмка: python scripts/screenshots.py), после пересъёмки
запустите этот скрипт снова. Нужен Pillow (только для сборки картинок, не для агента).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC, OUT = ROOT / "docs" / "assets", ROOT / "site" / "img"

FULL = ["doc-dark", "graph-dark", "tests-dark", "fixes-dark", "overview-dark", "studio-sources"]  # hero и вкладки
# кроп (x0, y0, x1, y1) в координатах 1440×900 → иллюстрация карточки «Возможностей» (960×600)
CROPS = {
    "f-probe": ("tests-dark", (300, 150, 1440, 860)),
    "f-report": ("doc-dark", (300, 330, 1440, 900)),
    "f-fix": ("fixes-dark", (300, 380, 1440, 900)),
    "f-guard": ("trace-dark", (300, 170, 1440, 760)),
    "f-graph": ("graph-dark", (300, 120, 1440, 860)),
    "f-studio": ("studio-sources", None),
}
VIDEO = ROOT / "docs" / "assets" / "demo-60s.mp4"


def save(im: Image.Image, name: str, width: int) -> None:
    im = im.convert("RGB")
    h = round(im.height * width / im.width)
    im.resize((width, h), Image.LANCZOS).save(OUT / f"{name}.webp", "WEBP", quality=78, method=6)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for n in FULL:
        p = SRC / f"screenshot-{n}.png"
        if p.exists():
            im = Image.open(p)
            th = round(im.width * 10 / 16)  # полные экраны — 16:10 (длинные снимки страницы обрезаются сверху)
            save(im.crop((0, 0, im.width, th)) if im.height > th else im, n, 1200)
    for name, (src, box) in CROPS.items():
        p = SRC / f"screenshot-{src}.png"
        if not p.exists():
            continue
        im = Image.open(p)
        if box:
            sx, sy = im.width / 1440, im.height / 900
            im = im.crop((round(box[0] * sx), round(box[1] * sy), round(box[2] * sx), round(box[3] * sy)))
        # в пропорцию 16:10 — по центру сверху
        w, h = im.size
        th = round(w * 10 / 16)
        im = im.crop((0, 0, w, min(h, th))) if h >= th else im
        save(im, name, 960)
    # постер видео «ReqLens за 60 секунд» — кадр на 12-й секунде (нужен ffmpeg; без него браузер покажет первый кадр)
    if VIDEO.exists() and shutil.which("ffmpeg"):
        png = OUT / "demo-poster.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "12", "-i", str(VIDEO), "-frames:v", "1", str(png)], check=True)
        save(Image.open(png), "demo-poster", 1280)
        png.unlink()
    gif = SRC / "live-run.gif"  # кадр живого прогона — фон блока, пока GIF загружается (и на снимках страницы)
    if gif.exists():
        g = Image.open(gif)
        g.seek(g.n_frames - 1)
        save(g.convert("RGB"), "live-poster", 960)
    for old in OUT.glob("*.webp"):  # убрать картинки, которых больше нет в списках
        if old.stem not in {*FULL, *CROPS, "demo-poster", "live-poster"}:
            old.unlink()
    total = sum(f.stat().st_size for f in OUT.glob("*.webp"))
    print(f"site/img: {len(list(OUT.glob('*.webp')))} файлов, {total // 1024} КБ")


if __name__ == "__main__":
    main()
