"""Обрезка текста для отчётов: по границе слова, а не посреди слова или символа.

clip — для заголовков и описаний: «…» в конце; clip_quote — для цитат: без многоточия, результат остаётся
дословной подстрокой исходного текста (проверяется verify.quote_in).
"""
from __future__ import annotations


def clip(s: str, n: int, ellipsis: str = "…") -> str:
    s = " ".join(str(s or "").split())
    if len(s) <= n:
        return s
    cut = s[: max(1, n - len(ellipsis))]
    sp = cut.rfind(" ")
    if sp > 0 and s[len(cut)] != " ":  # не режем слово: отступаем к последнему пробелу (если он есть)
        cut = cut[:sp]
    return cut.rstrip(" ,;:—-(«\"") + ellipsis


def clip_quote(s: str, n: int) -> str:
    """Начало строки длиной не больше n по границе слова — дословно (без многоточия и без схлопывания пробелов)."""
    s = str(s or "").strip()
    if len(s) <= n:
        return s
    cut = s[:n]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 0 and s[n] != " " else cut).rstrip(" ,;:")


def first_sentence(s: str, n: int) -> str:
    """Первое предложение, обрезанное по границе слова."""
    s = " ".join(str(s or "").split())
    head = s.split(". ")[0]
    return clip(head, n)
