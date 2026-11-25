"""Вопросы заказчику/аналитику: выводятся из замечаний без дополнительных обращений к модели."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .checker import ReviewResult
from .criteria import criterion_name

TEMPLATES = {
    "verifiable": "Как проверить выполнение «{q}»? Укажите измеримый критерий приёмки (число, единицы, условия измерения).",
    "unambiguous": "Что именно означает «{q}»? Дайте одно толкование с конкретными значениями.",
    "complete": "Чего не хватает во фрагменте «{q}»? Уточните условия, ограничения, реакцию на ошибки и закройте перечисления.",
    "singular": "Фрагмент «{q}» объединяет несколько требований — можно ли разделить их и назначить отдельные ID?",
    "appropriate": "«{q}» — это ограничение заказчика или проектное решение команды? Если ограничение — укажите обоснование.",
    "feasible": "Реализуемо ли «{q}» в рамках проекта? Какая допустимая доля отказов/исключений?",
    "necessary": "Нужно ли требование с фрагментом «{q}»? Какую потребность оно закрывает?",
    "correct": "Верно ли отражает потребность фрагмент «{q}»? Подтвердите источник.",
    "conforming": "Можно ли оформить «{q}» по шаблону «Система должна …» с ID и приоритетом?",
}


@dataclass
class Question:
    section: str
    ref: str  # R-001 (FR-02) / S-01
    text: str
    severity: str


def _short(q: str, n: int = 70) -> str:
    q = " ".join(q.split())
    return q if len(q) <= n else q[: n - 1].rstrip() + "…"


def build_questions(rv: ReviewResult) -> list[Question]:
    out: list[Question] = []
    seen: set[str] = set()
    for rr in rv.req_results:
        r = rr.req
        label = r.rid + (f" ({r.doc_id})" if r.doc_id else "")
        for f in rr.findings:
            if f.severity == "minor":
                continue
            key = r.rid + f.criterion
            if key in seen:
                continue
            seen.add(key)
            tpl = TEMPLATES.get(f.criterion, "Уточните фрагмент «{q}».")
            text = tpl.format(q=_short(f.quote))
            if f.fix:
                text += f" Предложение агента: {_short(re.sub(r'[.。]$', '', f.fix), 160)}."
            out.append(Question(r.section or "Без раздела", label, text, f.severity))
    for i, f in enumerate(rv.set_findings, 1):
        if f.severity == "minor":
            continue
        ids = ", ".join(ref.req_id for ref in f.refs if ref.req_id != "DOC") or "документ"
        out.append(Question("Набор требований", f"S-{i:02d}",
                            f"{criterion_name(f.criterion)} ({ids}): {_short(f.problem, 220)} Как исправить: {_short(f.fix, 200)}",
                            f.severity))
    if rv.domain:
        for a in rv.domain.areas:
            if a.status == "missing":
                out.append(Question("Доменная полнота (финтех)", a.id, f"{a.title}: {a.question}", "major"))
    order = {"critical": 0, "major": 1, "minor": 2}
    out.sort(key=lambda q: order[q.severity])
    return out
