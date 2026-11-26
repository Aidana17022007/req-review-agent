"""Контраст цветов по WCAG 2.1 — для витрины дизайн-системы и тестов (все пары «текст / фон» из токенов ≥ AA)."""
from __future__ import annotations

import re

AA_TEXT = 4.5  # обычный текст
AA_LARGE = 3.0  # крупный текст (≥ 18.66 px жирный / 24 px) и графика

# текстовые токены → фоны, на которых они встречаются в интерфейсе
TEXT_ON = {
    "text": ("bg", "surface", "surface-2"),
    "text-2": ("bg", "surface", "surface-2"),
    "text-3": ("bg", "surface", "surface-2"),
    "brand": ("bg", "surface", "brand-soft"),
    "critical": ("surface", "critical-soft"),
    "major": ("surface", "major-soft"),
    "minor": ("surface", "minor-soft"),
    "ok": ("surface", "ok-soft"),
    "info": ("surface", "info-soft"),
    "on-brand": ("brand",),
    "on-danger": ("danger",),
}


def rgb(value: str, under: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    """#RRGGBB или rgba(...) → RGB; полупрозрачный цвет накладывается на подложку `under`."""
    v = value.strip()
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    m = re.match(r"rgba?\(([^)]+)\)", v)
    if not m:
        raise ValueError(f"не цвет: {value}")
    p = [float(x) for x in m[1].split(",")]
    a = p[3] if len(p) > 3 else 1.0
    return tuple(round(p[i] * a + under[i] * (1 - a)) for i in range(3))  # type: ignore[return-value]


def luminance(c: tuple[int, int, int]) -> float:
    def ch(x: float) -> float:
        x /= 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = (ch(x) for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def contrast_table(tokens: dict) -> list[dict]:
    """Все пары «текст / фон» обеих тем: {theme, fg, bg, ratio, ok}. Полупрозрачные фоны — поверх surface."""
    rows = []
    for theme, c in tokens["color"].items():
        surface = rgb(c["surface"])
        for fg, bgs in TEXT_ON.items():
            if fg not in c:
                continue
            for bg in bgs:
                if bg not in c:
                    continue
                r = contrast(rgb(c[fg], surface), rgb(c[bg], surface))
                rows.append({"theme": theme, "fg": fg, "bg": bg, "ratio": round(r, 2), "ok": r >= AA_TEXT})
    return rows
