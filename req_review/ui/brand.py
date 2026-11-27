"""Логотип ReqLens: знак (линза с галочкой — кольцо в градиенте рассвета на ночной плитке) + текст.
Один источник геометрии → SVG и PNG. Дизайн-система v3 «Ecliptic Dawn».

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
NIGHT = "#02030C"  # плитка — ночь
GLOW = "#4459C8"  # свечение кобальта снизу плитки
GRAD = ("#4459C8", "#9191D3", "#E3CDDB")  # кольцо и ручка: кобальт → перивинкл → заря (сверху слева вниз вправо)
LENS = (21.0, 21.0, 10.5)  # cx, cy, r — оправа линзы
LENS_W = 4.0
HANDLE = ((28.9, 28.9), (37.0, 37.0))
HANDLE_W = 5.0
CHECK = ((15.9, 21.4), (19.7, 25.2), (26.3, 17.7))
CHECK_W = 3.2
GLYPH = "#FFFFFF"  # галочка
TEXT = {"light": "#0A0D2A", "dark": "#F4F5FF"}

_ids = itertools.count(1)


def _glyph_svg(gid: str) -> str:
    cx, cy, r = LENS
    (x1, y1), (x2, y2) = HANDLE
    pts = " ".join(f"{x},{y}" for x, y in CHECK)
    return (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="url(#{gid})" stroke-width="{LENS_W}"/>'
            f'<path d="M{x1} {y1}L{x2} {y2}" stroke="url(#{gid})" stroke-width="{HANDLE_W}" stroke-linecap="round"/>'
            f'<polyline points="{pts}" fill="none" stroke="{GLYPH}" stroke-width="{CHECK_W}" stroke-linecap="round" stroke-linejoin="round"/>')


def mark_svg(size: int | None = 48, gid: str = "rl") -> str:
    """Знак ReqLens: ночная плитка (скругление 12/48) с кобальтовым свечением снизу, кольцо в градиенте рассвета."""
    wh = f' width="{size}" height="{size}"' if size else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEW} {VIEW}"{wh} role="img" aria-label="ReqLens">'
            f'<defs><linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="10" y1="9" x2="38" y2="38">'
            f'<stop offset="0" stop-color="{GRAD[0]}"/><stop offset=".55" stop-color="{GRAD[1]}"/><stop offset="1" stop-color="{GRAD[2]}"/>'
            f'</linearGradient><radialGradient id="{gid}g" cx=".5" cy="1" r=".85"><stop offset="0" stop-color="{GLOW}" stop-opacity=".6"/>'
            f'<stop offset="1" stop-color="{GLOW}" stop-opacity="0"/></radialGradient></defs>'
            f'<rect width="{VIEW}" height="{VIEW}" rx="12" fill="{NIGHT}"/><rect width="{VIEW}" height="{VIEW}" rx="12" fill="url(#{gid}g)"/>'
            f'{_glyph_svg(gid)}</svg>')


def logo_svg(theme: str = "light", height: int = 48) -> str:
    """Знак + слово «ReqLens» (Inter 700; без шрифта — системный sans)."""
    w = round(176 * height / VIEW)
    inner = mark_svg(None, f"rl-{theme}").replace('<svg xmlns="http://www.w3.org/2000/svg" ', '<svg x="0" y="0" width="48" height="48" ')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 176 {VIEW}" width="{w}" height="{height}" role="img" aria-label="ReqLens">'
            f'{inner}<text x="60" y="33" fill="{TEXT[theme]}" font-family="Inter, \'Segoe UI\', Roboto, Arial, sans-serif" '
            f'font-size="26" font-weight="700" letter-spacing="-0.6">ReqLens</text></svg>')


def logo_mark(size: int = 36, gid: str | None = None) -> Markup:
    """Знак для шаблонов (уникальный id градиента — несколько знаков на одной странице не конфликтуют)."""
    return Markup(mark_svg(size, gid or f"rl{next(_ids)}").replace('role="img" aria-label="ReqLens"', 'aria-hidden="true"'))


def logo_mark_factory():
    """logo_mark со своим счётчиком id: у каждого рендера id одинаковые — сборка воспроизводима, без шума в git diff."""
    ids = itertools.count(1)
    return lambda size=36: logo_mark(size, f"rl{next(ids)}")


def favicon_href() -> str:
    """favicon как data:URI — офлайн-отчёт остаётся одним файлом."""
    return "data:image/svg+xml," + quote(mark_svg(None, "f"), safe=" =:/,\"'")  # '#' кодируется: иначе браузер обрежет SVG как фрагмент URL


# ---------------------------------------------------------------- PNG (Pillow)

def _png(size: int, maskable: bool = False, rounded: bool = True):
    from PIL import Image, ImageDraw, ImageFilter

    ss = 4
    S = size * ss

    def rgb(h: str) -> tuple[int, int, int]:
        return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))

    # плитка: ночь + кобальтовое свечение снизу
    bg = Image.new("RGB", (S, S), rgb(NIGHT))
    glow = Image.new("L", (S, S), 0)
    ImageDraw.Draw(glow).ellipse((-0.35 * S, 0.55 * S, 1.35 * S, 1.75 * S), fill=150)
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.14))
    bg = Image.composite(Image.new("RGB", (S, S), rgb(GLOW)), bg, glow)
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

    # кольцо и ручка — маска, залитая диагональным градиентом рассвета
    ring = Image.new("L", (S, S), 0)
    rd = ImageDraw.Draw(ring)

    def stroke(draw, points: list[tuple[float, float]], width: float, fill):
        wpx = width * sc * k0
        pts = [P(x, y) for x, y in points]
        draw.line(pts, fill=fill, width=round(wpx), joint="curve")
        for x, y in pts:  # круглые концы и стыки
            draw.ellipse((x - wpx / 2, y - wpx / 2, x + wpx / 2, y + wpx / 2), fill=fill)

    cx, cy, r = LENS
    (px, py), rr, lw = P(cx, cy), r * sc * k0, LENS_W * sc * k0
    rd.ellipse((px - rr - lw / 2, py - rr - lw / 2, px + rr + lw / 2, py + rr + lw / 2), outline=255, width=round(lw))
    stroke(rd, list(HANDLE), HANDLE_W, 255)
    v = Image.linear_gradient("L")
    diag = Image.blend(v, v.rotate(90), 0.5).resize((S, S))  # 0 — сверху слева, 255 — снизу справа
    c0, c1, c2 = (Image.new("RGB", (S, S), rgb(h)) for h in GRAD)
    half = diag.point(lambda x: min(255, x * 2))
    grad = Image.composite(c1, c0, half)
    grad = Image.composite(c2, grad, diag.point(lambda x: max(0, (x - 128) * 2)))
    img.paste(grad, (0, 0), ring)
    stroke(ImageDraw.Draw(img), list(CHECK), CHECK_W, (255, 255, 255, 255))
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
    # иконки приложения (PWA) — те же файлы знака: один источник для отчёта, Studio, сайта и установки на телефон
    static = ROOT / "req_review" / "web" / "static"
    if out == OUT and static.exists():
        import shutil

        for name in ("icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png"):
            shutil.copy2(out / name, static / name)
        (static / "icon.svg").write_text(files["favicon.svg"] + "\n", encoding="utf-8")
        site = ROOT / "site"
        if site.exists():
            (site / "favicon.svg").write_text(files["favicon.svg"] + "\n", encoding="utf-8")
    return written


if __name__ == "__main__":
    for p in build():
        print(p.relative_to(ROOT))
