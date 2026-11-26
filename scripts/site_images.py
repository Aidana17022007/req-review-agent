"""Картинки сайта: скриншоты интерфейса → WebP (site/img/). Запуск: python scripts/site_images.py

Полные экраны — 1200 px по ширине; мини-иллюстрации карточек — кропы реального интерфейса 640×400.
Источник — docs/assets/screenshot-*.png (их пересъёмка: python scripts/screenshots.py), после пересъёмки
запустите этот скрипт снова. Нужен Pillow (только для сборки картинок, не для агента).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC, OUT = ROOT / "docs" / "assets", ROOT / "site" / "img"

FULL = ["doc-dark", "graph-dark", "tests-dark", "fixes-dark", "overview-dark", "set-dark", "export-dark",
        "studio-assistant", "studio-live", "studio-compare"]
# кроп (x0, y0, x1, y1) в координатах 1440×900 → мини-иллюстрация карточки
CROPS = {
    "f-probe": ("tests-dark", (300, 150, 1440, 860)),
    "f-report": ("doc-dark", (300, 330, 1440, 900)),
    "f-fix": ("fixes-dark", (300, 380, 1440, 900)),
    "f-guard": ("trace-dark", (300, 170, 1440, 760)),
    "f-fintech": ("set-dark", (300, 100, 1440, 760)),
    "f-metrics": ("overview-dark", (300, 90, 1440, 800)),
    "f-offline": ("export-dark", (300, 150, 1440, 860)),
    "f-team": ("requirements-dark", (300, 150, 1440, 860)),
    "f-graph": ("graph-dark", (300, 120, 1440, 860)),
    "f-studio": ("studio-assistant", None),
}


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
        save(im, name, 640)
    total = sum(f.stat().st_size for f in OUT.glob("*.webp"))
    print(f"site/img: {len(list(OUT.glob('*.webp')))} файлов, {total // 1024} КБ")


if __name__ == "__main__":
    main()
