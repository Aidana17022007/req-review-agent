"""Проверка, что цитата из замечания LLM действительно есть в документе (анти-галлюцинации)."""
from __future__ import annotations

import re

_QUOTES = str.maketrans({"«": '"', "»": '"', "“": '"', "”": '"', "„": '"', "’": "'", "‘": "'",
                         "—": "-", "–": "-", "−": "-", "ё": "е", "Ё": "Е", " ": " "})


def norm(s: str) -> str:
    s = s.translate(_QUOTES)
    s = re.sub(r"(\*\*|__|`)", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def quote_in(quote: str, text: str) -> bool:
    """True, если цитата (после нормализации) — подстрока текста.

    Цитата с многоточием проверяется по частям: каждая часть длиной ≥ 3 символов
    должна встречаться в тексте в том же порядке.
    """
    q = norm(quote).strip(" .,;:\"'")
    t = norm(text)
    if not q:
        return False
    if q in t:
        return True
    parts = [p.strip(" .,;:\"'") for p in re.split(r"\.\.\.|…", q)]
    parts = [p for p in parts if len(p) >= 3]
    if len(parts) > 1:
        pos = 0
        for p in parts:
            i = t.find(p, pos)
            if i < 0:
                return False
            pos = i + len(p)
        return True
    return False
