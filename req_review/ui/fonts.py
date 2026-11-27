"""Шрифт Inter (OFL, см. assets/fonts/LICENSE-Inter.txt) — тот же, что на сайте; встраивается в HTML как data:-URI.

Без него Studio и отчёт на Windows показывались шрифтом Segoe UI, а сайт — Inter. Подмножества (fontTools subset,
вариативная ось wght сохранена): латиница, кириллица, казахские буквы (ә ғ қ ң ө ұ ү һ).
"""
from __future__ import annotations

import base64
from functools import lru_cache

from . import ASSETS

FAMILY = "Inter"
SUBSETS = (
    ("latin", "U+0020-007E, U+00A0, U+00A7, U+00AB, U+00B0, U+00B7, U+00BB, U+00D7, U+2013-2014, U+2018-201E, U+2022, U+2026, U+2030, U+2039-203A, U+20AC, U+2122, U+2190-2193, U+2212"),
    ("cyrillic", "U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116"),
    ("cyrillic-ext", "U+0492-0493, U+049A-049B, U+04A2-04A3, U+04AE-04AF, U+04BA-04BB, U+04D8-04D9, U+04E8-04E9"),
)


@lru_cache(maxsize=None)
def fonts_css() -> str:
    """@font-face для Inter (вариативный, 400–700) с файлами внутри CSS — отчёт остаётся одним офлайн-файлом."""
    out = []
    for name, rng in SUBSETS:
        p = ASSETS / "fonts" / f"inter-{name}.woff2"
        if not p.exists():
            continue
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        out.append(f'@font-face{{font-family:"{FAMILY}";font-style:normal;font-weight:400 700;font-display:swap;'
                   f'src:url(data:font/woff2;base64,{b64}) format("woff2");unicode-range:{rng}}}')
    return "\n".join(out)
