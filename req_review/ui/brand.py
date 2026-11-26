"""Логотип ReqLens: знак (линза с галочкой на зелёном квадрате) + текст. Один источник геометрии → SVG и PNG.

    python -m req_review.ui.brand   →  design/brand/ (SVG-логотипы, favicon, иконки PWA 192/512/maskable, brand.json)

SVG собираются без зависимостей (их встраивают шаблоны отчёта, Studio, слайдов и витрины).
PNG рисуются Pillow (рендер в 4× и уменьшение — гладкие края); Pillow нужен только для этой команды.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path
from urllib.parse import quote

from markupsafe import Markup

from . import load_tokens

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "design" / "brand"

# геометрия знака в системе 48×48
VIEW = 48
GRAD = ("#14532D", "#2E8B57")  # как --grad-hero: от тёмного зелёного (сверху слева) к светлому
LENS = (21.0, 21.0, 10.5)  # cx, cy, r — оправа линзы
LENS_W = 4.0
HANDLE = ((28.9, 28.9), (37.0, 37.0))
HANDLE_W = 5.0
CHECK = ((15.9, 21.4), (19.7, 25.2), (26.3, 17.7))
CHECK_W = 3.2
GLYPH = "#FFFFFF"
TEXT = {"light": "#111813", "dark": "#EEF3EF"}

_ids = itertools.count(1)


def _glyph_svg() -> str:
    cx, cy, r = LENS
    (x1, y1), (x2, y2) = HANDLE
    pts = " ".join(f"{x},{y}" for x, y in CHECK)
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{GLYPH}" stroke-width="{LENS_W}"/>'
            f'<path d="M{x1} {y1}L{x2} {y2}" stroke="{GLYPH}" stroke-width="{HANDLE_W}" stroke-linecap="round"/>'
            f'<polyline points="{pts}" fill="none" stroke="{GLYPH}" stroke-width="{CHECK_W}" stroke-linecap="round" stroke-linejoin="round"/>')


def mark_svg(size: int | None = 48, gid: str = "rl") -> str:
    """Знак ReqLens (квадрат со скруглением 12/48 и градиентом бренда)."""
    wh = f' width="{size}" height="{size}"' if size else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEW} {VIEW}"{wh} role="img" aria-label="ReqLens">'
            f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{GRAD[0]}"/>'
            f'<stop offset="1" stop-color="{GRAD[1]}"/></linearGradient></defs>'
            f'<rect width="{VIEW}" height="{VIEW}" rx="12" fill="url(#{gid})"/>{_glyph_svg()}</svg>')


def logo_svg(theme: str = "light", height: int = 48) -> str:
    """Знак + слово «ReqLens» (Inter 700; без шрифта — системный sans)."""
    w = round(176 * height / VIEW)
    inner = mark_svg(None, f"rl-{theme}").replace('<svg xmlns="http://www.w3.org/2000/svg" ', '<svg x="0" y="0" width="48" height="48" ')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 176 {VIEW}" width="{w}" height="{height}" role="img" aria-label="ReqLens">'
            f'{inner}<text x="60" y="33" fill="{TEXT[theme]}" font-family="Inter, \'Segoe UI\', Roboto, Arial, sans-serif" '
            f'font-size="26" font-weight="700" letter-spacing="-0.6">ReqLens</text></svg>')


def logo_mark(size: int = 36) -> Markup:
    """Знак для шаблонов (уникальный id градиента — несколько знаков на одной странице не конфликтуют)."""
    return Markup(mark_svg(size, f"rl{next(_ids)}").replace('role="img" aria-label="ReqLens"', 'aria-hidden="true"'))


def favicon_href() -> str:
    """favicon как data:URI — офлайн-отчёт остаётся одним файлом."""
    return "data:image/svg+xml," + quote(mark_svg(None, "f"), safe=" =:/,\"'")  # '#' кодируется: иначе браузер обрежет SVG как фрагмент URL


# ---------------------------------------------------------------- PNG (Pillow)

def _png(size: int, maskable: bool = False, rounded: bool = True):
    from PIL import Image, ImageDraw

    ss = 4
    S = size * ss
    v = Image.linear_gradient("L")  # 0 сверху → 255 снизу
    g = Image.blend(v, v.rotate(90), 0.5).resize((S, S))  # (x + y) / 2: диагональ без пустых углов
    c0, c1 = (Image.new("RGB", (S, S), c) for c in GRAD)
    bg = Image.composite(c1, c0, g)  # верх-лево — GRAD[0], низ-право — GRAD[1]
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    mask = Image.new("L", (S, S), 0)
    md = ImageDraw.Draw(mask)
    if rounded and not maskable:
        md.rounded_rectangle((0, 0, S - 1, S - 1), radius=round(12 / VIEW * S), fill=255)
    else:
        md.rectangle((0, 0, S, S), fill=255)  # maskable: фон до краёв, обрезает система
    img.paste(bg, (0, 0), mask)

    # maskable: глиф внутри безопасной зоны (круг 80 %) — уменьшаем вокруг центра
    k0 = S / VIEW
    sc, c = (0.72, VIEW / 2) if maskable else (1.0, VIEW / 2)

    def P(x: float, y: float) -> tuple[float, float]:
        return ((c + (x - c) * sc) * k0, (c + (y - c) * sc) * k0)

    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)

    def stroke(points: list[tuple[float, float]], width: float):
        wpx = width * sc * k0
        pts = [P(x, y) for x, y in points]
        d.line(pts, fill=white, width=round(wpx), joint="curve")
        for x, y in pts:  # круглые концы и стыки
            d.ellipse((x - wpx / 2, y - wpx / 2, x + wpx / 2, y + wpx / 2), fill=white)

    cx, cy, r = LENS
    (px, py), rr, lw = P(cx, cy), r * sc * k0, LENS_W * sc * k0
    d.ellipse((px - rr - lw / 2, py - rr - lw / 2, px + rr + lw / 2, py + rr + lw / 2), outline=white, width=round(lw))
    stroke(list(HANDLE), HANDLE_W)
    stroke(list(CHECK), CHECK_W)
    return img.resize((size, size), Image.LANCZOS)


def build(out: Path = OUT) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "reqlens-mark.svg": mark_svg(48),
        "reqlens-logo-light.svg": logo_svg("light"),
        "reqlens-logo-dark.svg": logo_svg("dark"),
        "favicon.svg": mark_svg(None, "f"),
    }
    written = []
    for name, svg in files.items():
        (out / name).write_text(svg + "\n", encoding="utf-8")
        written.append(out / name)
    t = load_tokens()
    meta = {"name": "ReqLens", "short_name": "ReqLens", **t.get("brand", {}),
            "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                      {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                      {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]}
    (out / "brand.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    written.append(out / "brand.json")
    try:
        import PIL  # noqa: F401
    except ImportError:
        print("Pillow не установлен — PNG-иконки пропущены (SVG готовы)")
        return written
    for name, img in {"icon-192.png": _png(192), "icon-512.png": _png(512), "icon-maskable-512.png": _png(512, maskable=True),
                      "apple-touch-icon.png": _png(180, rounded=False), "favicon-32.png": _png(32)}.items():
        img.save(out / name, optimize=True)
        written.append(out / name)
    return written


if __name__ == "__main__":
    for p in build():
        print(p.relative_to(ROOT))
