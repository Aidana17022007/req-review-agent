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


# ---------------------------------------------------------------- позиции цитат в исходном документе

_Q = str.maketrans({"«": '"', "»": '"', "“": '"', "”": '"', "„": '"', "ё": "е", "Ё": "Е", "—": "-", "–": "-", " ": " "})


def find_span(quote: str, text: str) -> tuple[int, int] | None:
    if not quote or not text:
        return None
    i = text.find(quote)
    if i >= 0:
        return i, i + len(quote)
    tl, ql = text.translate(_Q).lower(), quote.translate(_Q).lower()
    i = tl.find(ql)
    if i >= 0:
        return i, i + len(ql)
    # нормализация пробелов: ищем по регулярке с \s+
    parts = [re.escape(p) for p in re.split(r"\s+", ql.strip(" .,;:\"'")) if p]
    if parts:
        m = re.search(r"\s+".join(parts), tl)
        if m:
            return m.start(), m.end()
    pieces = [p.strip(" .,;:\"'") for p in re.split(r"\.\.\.|…", ql) if len(p.strip()) >= 3]
    if len(pieces) > 1:
        a, b = tl.find(pieces[0]), -1
        if a >= 0:
            b = tl.find(pieces[-1], a)
        if a >= 0 and b >= 0:
            return a, b + len(pieces[-1])
    return None


def locate(quote: str, lines, lo: int, hi: int, fallback: str = ""):
    rng = [l for l in lines if lo <= l.lineno <= hi] if lo else lines
    for l in rng:
        span = find_span(quote, l.text)
        if span:
            return l.lineno, span
    if fallback:
        for l in rng:
            span = find_span(fallback[:60], l.text)
            if span:
                return l.lineno, (span[0], min(len(l.text), span[0] + len(fallback)))
    if lo and rng:
        l = rng[0]
        s = len(l.text) - len(l.text.lstrip())
        return l.lineno, (s, len(l.text))
    return None
