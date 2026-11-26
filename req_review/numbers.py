"""Детерминированный поиск числовых противоречий между требованиями.

Извлекаем величины с единицами (суммы, время, попытки, проценты) и их контекст, затем ищем пары требований,
которые говорят об одном и том же (общие слова рядом с числом, одна размерность, один период),
но задают разные значения: «после 3 неверных вводов» vs «после 5 неверных вводов».
Каждая цитата — дословный фрагмент текста требования, поэтому проходит verify.quote_in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .splitter import Requirement

_NUM = r"\d{1,3}(?:[  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_UNITS = [
    ("money", r"(?:тенге|тг\.?|₸|руб\w*|₽|долл\w*|usd|\$|eur|евро)"),
    ("time", r"(?:миллисекунд\w*|мс|секунд\w*|сек\.?|с(?=[\s.,;)]|$)|минут\w*|мин\.?|час\w*|ч(?=[\s.,;)]|$)|сут\w*|дн\w*|день|недел\w*|месяц\w*|мес\.?|год\w*|лет)"),
    ("percent", r"%"),
    ("count", r"(?:\w+\s+)?(?:попыт\w*|ввод\w*|раз(?:а)?|запрос\w*|символ\w*|знак\w*|устройств\w*|сесси\w*|операц\w*|шаг\w*|цифр\w*)"),
]
_QTY = re.compile(r"(?<![\w.,])(" + _NUM + r")\s*(" + "|".join(u for _, u in _UNITS) + r")", re.IGNORECASE)
_TIME_SEC = [(r"^миллисекунд|^мс", 0.001), (r"^сек|^с$", 1), (r"^мин", 60), (r"^час|^ч$", 3600), (r"^сут|^дн|^день", 86400),
             (r"^недел", 604800), (r"^месяц|^мес", 2592000), (r"^год|^лет", 31536000)]
_PERIOD = re.compile(r"\b(в|за)\s+(сутки|день|месяц|неделю|год|час|минуту)\b|\bежедневн\w*|\bежемесячн\w*|\bсуточн\w*|\bмесячн\w*",
                     re.IGNORECASE)
_STOP = set("""должен должна должно должны система сервис клиент может могут быть более менее после перед одного одной один
также который которая которые каждый каждой всех этого если когда чтобы через только между составляет составлять
""".split())


@dataclass
class Quantity:
    rid: str
    value: float
    dim: str
    raw: str  # дословный фрагмент «5 неверных вводов»
    quote: str  # дословная цитата с контекстом
    period: str
    stems: frozenset


def _value(num: str) -> float:
    return float(re.sub(r"[  ]", "", num).replace(",", "."))


def _dim(unit: str) -> tuple[str, float]:
    u = unit.lower().strip()
    for dim, pat in _UNITS:
        if re.fullmatch(pat, u, re.IGNORECASE):
            if dim == "time":
                for p, k in _TIME_SEC:
                    if re.search(p, u):
                        return "time", k
            return dim, 1.0
    return "other", 1.0


def _stems(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[а-яёa-z]{4,}", text.lower()) if w not in _STOP}


def _context(text: str, start: int, end: int, width: int = 40) -> str:
    s, e = max(0, start - width), min(len(text), end + width)
    if s > 0:
        sp = text.find(" ", s)
        s = sp + 1 if 0 <= sp < start else s
    if e < len(text):
        sp = text.rfind(" ", end, e)
        e = sp if sp > end else e
    return text[s:e].strip(" ,;")


def extract(req: Requirement) -> list[Quantity]:
    text = req.text
    out = []
    for m in _QTY.finditer(text):
        dim, k = _dim(m.group(2))
        if dim == "other":
            continue
        clause_s = max(text.rfind(",", 0, m.start()), text.rfind(";", 0, m.start()), text.rfind(" и ", 0, m.start()))
        clause_e = min([p for p in (text.find(",", m.end()), text.find(";", m.end()), text.find(" и ", m.end())) if p >= 0] or [len(text)])
        clause = text[clause_s + 1:clause_e]
        per = _PERIOD.search(clause)
        period = (per.group(2) if per and per.group(2) else per.group(0)[:5]).lower() if per else "операция"
        window = text[max(0, m.start() - 60): m.end() + 60]
        out.append(Quantity(req.rid, _value(m.group(1)) * k, dim, m.group(0), _context(text, m.start(), m.end()), period,
                            frozenset(_stems(window) | _stems(m.group(2)))))
    return out


@dataclass
class Conflict:
    a: Quantity
    b: Quantity
    reason: str


_LIMIT = re.compile(r"максимальн\w*|лимит\w*|не более|не превыша\w*|минимальн\w*|не менее|ограничен\w*", re.I)
_OBJ = ("перевод", "платеж", "платёж", "операц", "кредит", "займ", "сумм", "выплат", "пополнен", "снят")


def _skeleton(text: str) -> str:
    t = re.sub(_NUM, "#", text.lower())
    return re.sub(r"\s+", " ", t)


def _similar(a: str, b: str) -> float:
    import difflib

    return difflib.SequenceMatcher(None, _skeleton(a), _skeleton(b)).ratio()


def _objects(text: str) -> set[str]:
    low = text.lower()
    return {o for o in _OBJ if o in low}


def find_conflicts(reqs: list[Requirement], min_similarity: float = 0.65) -> list[Conflict]:
    """Высокоточные эвристики (лучше пропустить, чем выдать ложное противоречие):
    (a) формулировки совпадают, если заменить числа на #, а значения разные — «3 попытки» vs «5 попыток»;
    (b) оба требования задают лимит денежной суммы для одного объекта (перевод, платёж…) и периода;
    (c) счётные величины с одинаковым существительным рядом («неверных вводов») и общим контекстом."""
    qs = {r.rid: extract(r) for r in reqs}
    texts = {r.rid: r.text for r in reqs}
    out: list[Conflict] = []
    rids = [r.rid for r in reqs]
    for i, ra in enumerate(rids):
        for rb in rids[i + 1:]:
            sim = None
            found = None
            for qa in qs[ra]:
                for qb in qs[rb]:
                    if qa.dim != qb.dim or qa.period != qb.period or abs(qa.value - qb.value) < 1e-9:
                        continue
                    if sim is None:
                        sim = _similar(texts[ra], texts[rb])
                    if sim >= min_similarity:
                        found = Conflict(qa, qb, f"формулировки совпадают на {sim:.0%}, отличаются только значения")
                    elif (qa.dim == "money" and _LIMIT.search(texts[ra]) and _LIMIT.search(texts[rb])
                          and _objects(texts[ra]) & _objects(texts[rb])):
                        found = Conflict(qa, qb, "оба требования задают лимит суммы для одного объекта и периода")
                    elif qa.dim == "count" and qa.raw.split()[-1][:5].lower() == qb.raw.split()[-1][:5].lower()                             and len(qa.stems & qb.stems) >= 4:
                        found = Conflict(qa, qb, "одна и та же счётная величина в общем контексте")
                    if found:
                        break
                if found:
                    break
            if found:
                out.append(found)
    return out


def fmt_value(q: Quantity) -> str:
    return q.raw
