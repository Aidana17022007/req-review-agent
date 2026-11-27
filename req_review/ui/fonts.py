"""Шрифт Manrope (OFL, см. assets/fonts/LICENSE-Manrope.txt) — встраивается в офлайн-HTML как data:-URI.

Подмножества: латиница, знак ₸, кириллица, казахские буквы (ә ғ қ ң ө ұ ү һ; і и Ұ Ү — в основной кириллице).
"""
from __future__ import annotations

import base64
from functools import lru_cache

from . import ASSETS

FAMILY = "Manrope"
SUBSETS = (  # файлы урезаны до этих символов (fontTools subset, оставлены kern и liga), чтобы отчёт был < 1 МБ
    ("latin", "U+0020-007E, U+00A0-00FF, U+2010-2027, U+2030-203A, U+20AC, U+2116, U+2190-2193, U+2212"),
    ("latin-ext", "U+20B8"),
    ("cyrillic", "U+0400-045F, U+0490-0491, U+04B0-04B1"),
    ("cyrillic-ext", "U+0492-0493, U+049A-049B, U+04A2-04A3, U+04AE-04AF, U+04BA-04BB, U+04D8-04D9, U+04E8-04E9"),
)


@lru_cache(maxsize=None)
def fonts_css() -> str:
    """@font-face для Manrope (вариативный, 400–800) с файлами внутри CSS — отчёт остаётся одним офлайн-файлом."""
    out = []
    for name, rng in SUBSETS:
        p = ASSETS / "fonts" / f"manrope-{name}.woff2"
        if not p.exists():
            continue
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        out.append(f'@font-face{{font-family:"{FAMILY}";font-style:normal;font-weight:400 800;font-display:swap;'
                   f'src:url(data:font/woff2;base64,{b64}) format("woff2");unicode-range:{rng}}}')
    return "\n".join(out)
