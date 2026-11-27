"""v13: стабильность — N независимых прогонов (разная температура), «найдено в k из N» у каждого замечания.

Замечание основного прогона ищется в остальных теми же правилами совпадения, что у ансамбля (ensemble.py): к требованию —
тот же текст требования, критерий и перекрывающиеся цитаты; к набору — тот же вид и те же требования (или цитаты).
Найденное в ≥ 2 из N — «устойчивое». Замечания правил одинаковы во всех прогонах — у них N из N. Новых обращений к модели
сопоставление не делает. Каждый прогон дополнительно сохраняется кратко (<отчёт>_runs.json) — bench/stability.py считает
по нему среднее и разброс полноты на документе организаторов.
"""
from __future__ import annotations

import os

from .ensemble import _overlap


def temperatures(n: int) -> list[float]:
    raw = os.getenv("REQLENS_RUNS_TEMPS", "0,0.4,0.8,0.6,0.2")
    ts = [float(x) for x in raw.split(",") if x.strip()]
    while len(ts) < n:
        ts.append(round(ts[-1] / 2 + 0.05, 2))
    return ts[:n]


def _req_twin(f, rr_other) -> bool:
    return any(g.criterion == f.criterion and _overlap(f.quote, g.quote) for g in rr_other.findings) if rr_other else False


def _set_twin(f, other, remap) -> bool:
    ids = frozenset(r.req_id for r in f.refs)
    for g in other.set_findings:
        gid = frozenset(remap.get(r.req_id, r.req_id) for r in g.refs)
        if (g.kind == f.kind and gid == ids) or any(_overlap(x.quote, y.quote) for x in f.refs for y in g.refs):
            return True
    return False


def mark(rv, others: list) -> dict:
    """Проставить f.stability = «k из N» в основном прогоне; вернуть сводку для паспорта."""
    n = 1 + len(others)
    by_text = [{rr.req.text: rr for rr in o.req_results} for o in others]
    remaps = []
    for o in others:
        a = {rr.req.text: rr.req.rid for rr in rv.req_results}
        remaps.append({rr.req.rid: a[rr.req.text] for rr in o.req_results if rr.req.text in a})
    stable = unstable = 0
    for rr in rv.req_results:
        for f in rr.findings:
            k = 1 + sum(_req_twin(f, bt.get(rr.req.text)) for bt in by_text)
            f.stability = f"{k} из {n}"
            stable, unstable = (stable + 1, unstable) if k >= 2 else (stable, unstable + 1)
    for f in rv.set_findings:
        k = 1 + sum(_set_twin(f, o, rm) for o, rm in zip(others, remaps))
        f.stability = f"{k} из {n}"
        stable, unstable = (stable + 1, unstable) if k >= 2 else (stable, unstable + 1)
    counts = [sum(len(rr.findings) for rr in x.req_results) + len(x.set_findings) for x in [rv, *others]]
    return {"n": n, "temperatures": temperatures(n), "findings_per_run": counts, "stable": stable, "unstable": unstable,
            "rule": "устойчивое — найдено минимум в 2 прогонах из N"}


def brief(rv) -> dict:
    """Краткая копия прогона в формате report.json (только тексты замечаний) — для bench/stability.py."""
    return {"requirements": [{"rid": rr.req.rid, "findings": [{"problem": f.problem, "fix": f.fix, "severity": f.severity,
                                                               "criterion": f.criterion} for f in rr.findings]}
                             for rr in rv.req_results],
            "set_findings": [{"problem": f.problem, "fix": f.fix, "severity": f.severity, "criterion": f.criterion}
                             for f in rv.set_findings]}
