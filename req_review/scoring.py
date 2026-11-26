"""Quality Score, индекс готовности, радар по критериям и «цена дефекта».

Все числа считаются кодом по прозрачным формулам (описаны в METHOD_MD и попадают в отчёт).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .checker import ReviewResult
from .criteria import INDIVIDUAL, SET

PENALTY = {"critical": 35, "major": 15, "minor": 5}
SET_PENALTY = {"critical": 25, "major": 10, "minor": 3}
# Ориентировочные множители стоимости исправления дефекта по стадиям (по литературе о стоимости дефектов,
# порядок величин; значения условные): требования 1×, разработка 5×, тестирование 10×, эксплуатация 100×.
STAGES = [("Ревью требований (сейчас)", 1), ("Разработка", 5), ("Тестирование", 10), ("Эксплуатация", 100)]
BASE_HOURS = {"critical": 2.0, "major": 1.0, "minor": 0.25}  # часы аналитика на исправление на этапе требований

METHOD_MD = f"""**Балл требования** (0–100): 100 минус штраф за каждый критерий с нарушением — по самому серьёзному нарушению
в критерии: критичное −{PENALTY['critical']}, существенное −{PENALTY['major']}, незначительное −{PENALTY['minor']}; не ниже 0.

**Балл набора** (0–100): 100 минус штрафы за замечания уровня набора: критичное −{SET_PENALTY['critical']},
существенное −{SET_PENALTY['major']}, незначительное −{SET_PENALTY['minor']}; не ниже 0.

**Балл документа** = 0,7 × средний балл требований + 0,3 × балл набора.

**Готовность к разработке** = доля требований без критичных и существенных замечаний — и не затронутых критичными
или существенными замечаниями к набору — × (1 − 0,1 × число критичных замечаний набора), не ниже 0.

**Радар**: для каждого критерия — доля требований без нарушений по нему.

**Цена дефекта**: условные часы на исправление на этапе требований (критичный {BASE_HOURS['critical']} ч, существенный
{BASE_HOURS['major']} ч, незначительный {BASE_HOURS['minor']} ч) × ориентировочный множитель стадии
({', '.join(f'{n.lower()} {m}×' for n, m in STAGES)}). Оценка иллюстративная, а не бюджетная."""


@dataclass
class Scores:
    req: dict[str, int]
    set_score: int
    doc_score: int
    readiness: int
    radar_req: dict[str, int]
    radar_set: dict[str, int]
    ready_ids: list[str]
    tests_ok: int = 0
    tests_total: int = 0
    cost: list[tuple[str, float]] = field(default_factory=list)


def req_score(findings) -> int:
    worst: dict[str, str] = {}
    order = {"critical": 0, "major": 1, "minor": 2}
    for f in findings:
        if f.criterion not in worst or order[f.severity] < order[worst[f.criterion]]:
            worst[f.criterion] = f.severity
    return max(0, 100 - sum(PENALTY[s] for s in worst.values()))


def compute(rv: ReviewResult) -> Scores:
    reqs = rv.req_results
    rs = {rr.req.rid: req_score(rr.findings) for rr in reqs}
    set_score = max(0, 100 - sum(SET_PENALTY[f.severity] for f in rv.set_findings))
    avg = sum(rs.values()) / len(rs) if rs else 0
    doc_score = round(0.7 * avg + 0.3 * set_score)
    # требование, на которое ссылается критичное/существенное замечание к набору (противоречие, пропуск), тоже не готово
    blocked = {r.req_id for f in rv.set_findings if f.severity in ("critical", "major") for r in f.refs}
    ready = [rr.req.rid for rr in reqs
             if rr.req.rid not in blocked and not any(f.severity in ("critical", "major") for f in rr.findings)]
    set_crit = sum(1 for f in rv.set_findings if f.severity == "critical")
    readiness = round(100 * (len(ready) / len(reqs) if reqs else 0) * max(0.0, 1 - 0.1 * set_crit))
    radar_req = {}
    for k in INDIVIDUAL:
        ok = sum(1 for rr in reqs if not any(f.criterion == k for f in rr.findings))
        radar_req[k] = round(100 * ok / len(reqs)) if reqs else 0
    radar_set = {}
    for k in SET:
        fs = [f for f in rv.set_findings if f.criterion == k]
        radar_set[k] = max(0, 100 - sum(SET_PENALTY[f.severity] * 2 for f in fs))
    probed = [rr for rr in reqs if rr.test_possible is not None]
    tests_ok = sum(1 for rr in probed if rr.test_possible)
    hours = sum(BASE_HOURS[f.severity] for rr in reqs for f in rr.findings) + \
        sum(BASE_HOURS[f.severity] for f in rv.set_findings)
    cost = [(name, round(hours * m, 1)) for name, m in STAGES]
    return Scores(rs, set_score, doc_score, readiness, radar_req, radar_set, ready, tests_ok, len(probed), cost)


def bar(value: int, width: int = 10) -> str:
    n = round(value / 100 * width)
    return "█" * n + "░" * (width - n) + f" {value}"
