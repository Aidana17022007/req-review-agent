"""Иконки приложения ReqLens (PWA): icon.svg, icon-192.png, icon-512.png, icon-maskable-512.png.

Временный знак — лупа с плюсом на фирменном зелёном (--brand из tokens.css). Когда в дизайн-системе v2
появится логотип, замените файлы в req_review/web/static/ и перезапустите этот скрипт или положите свои PNG.
Запуск: python scripts/make_pwa_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

BRAND = "#1F6B45"
OUT = Path(__file__).resolve().parent.parent / "req_review" / "web" / "static"

SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="112" fill="{BRAND}"/>
<g fill="none" stroke="#fff" stroke-width="36" stroke-linecap="round">
<circle cx="232" cy="232" r="118"/><path d="M318 318l92 92M180 232h104M232 180v104"/></g></svg>
"""


def draw(size: int, safe: float) -> Image.Image:
    """safe — доля холста под знак: у maskable-иконки ОС обрезает края, знак должен быть в центральных 80 %."""
    s = 4 * size  # рисуем крупно и уменьшаем — сглаженные края
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if safe < 1:
        d.rectangle([0, 0, s, s], fill=BRAND)
    else:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=BRAND)
    k = s * safe / 512
    o = (s - 512 * k) / 2
    w = int(36 * k)
    p = lambda x: o + x * k  # noqa: E731
    d.ellipse([p(232 - 118), p(232 - 118), p(232 + 118), p(232 + 118)], outline="white", width=w)
    for a, b in (((318, 318), (410, 410)), ((180, 232), (284, 232)), ((232, 180), (232, 284))):
        d.line([p(a[0]), p(a[1]), p(b[0]), p(b[1])], fill="white", width=w)
        for x, y in (a, b):
            d.ellipse([p(x) - w / 2, p(y) - w / 2, p(x) + w / 2, p(y) + w / 2], fill="white")
    return img.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "icon.svg").write_text(SVG, encoding="utf-8")
    draw(192, 1).save(OUT / "icon-192.png", optimize=True)
    draw(512, 1).save(OUT / "icon-512.png", optimize=True)
    draw(512, 0.72).save(OUT / "icon-maskable-512.png", optimize=True)
    print("иконки:", OUT)


if __name__ == "__main__":
    main()
