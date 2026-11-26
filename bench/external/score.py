"""Оценка отчёта ReqLens по внешней разметке (bench/external/PROTOCOL.md): совпадение по месту и классу дефекта.

Запуск: python bench/external/score.py annotations.<имя>.json reports/requirements-report.json [--md out.md]
Никаких регулярных выражений по формулировкам: дефект разметчика найден, если цитата замечания агента лежит в
отмеченных строках документа (±1) и критерий замечания совместим с классом дефекта.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# класс разметки → критерии ReqLens (ISO/IEC/IEEE 29148, IEEE 830), которые его покрывают
CLASS_CRITERIA = {
    "ambiguous": {"unambiguous", "verifiable", "set_comprehensible"},
    "unverifiable": {"verifiable", "set_validatable"},
    "incomplete": {"complete", "set_complete", "set_validatable"},
    "contradiction": {"set_consistent", "correct", "consistent"},
    "inconsistent_terms": {"set_consistent", "set_comprehensible", "unambiguous"},
    "undefined_term": {"set_comprehensible", "unambiguous", "complete"},
    "design_in_requirement": {"appropriate", "necessary"},
    "compound": {"singular"},
    "infeasible": {"feasible", "verifiable"},
    "structure": {"conforming", "set_traceable", "set_complete", "traceable"},
}


def quote_lines(quote: str, doc_lines: list[str]) -> set[int]:
    """Номера строк документа (с 1), в которых встречается начало цитаты."""
    from req_review.verify import quote_in

    q = " ".join(quote.split())
    probe = q[:60]
    hits = {i for i, ln in enumerate(doc_lines, 1) if probe and quote_in(probe, ln)}
    if not hits and len(q) > 20:  # цитата через несколько строк — ищем по началу
        hits = {i for i, ln in enumerate(doc_lines, 1) if quote_in(q[:25], ln)}
    return hits


def agent_findings(report: dict) -> list[dict]:
    out = []
    for r in report.get("requirements", []):
        for f in r.get("findings", []):
            out.append({"id": r["rid"], "criterion": f["criterion"], "severity": f["severity"], "quotes": [f["quote"]],
                        "problem": f["problem"]})
    for i, f in enumerate(report.get("set_findings", []), 1):
        out.append({"id": f"S-{i:02d}", "criterion": f["criterion"], "severity": f["severity"],
                    "quotes": [x["quote"] for x in f.get("refs", [])], "problem": f["problem"]})
    return out


def score(ann: dict, report: dict) -> dict:
    doc = (ROOT / ann["document"]).read_text(encoding="utf-8").splitlines()
    fs = agent_findings(report)
    for f in fs:
        f["lines"] = set().union(*(quote_lines(q, doc) for q in f["quotes"])) if f["quotes"] else set()
    rows, used = [], set()
    for d in ann["defects"]:
        near = {n for x in d["lines"] for n in (x - 1, x, x + 1)}
        ok = CLASS_CRITERIA.get(d["class"], set())
        hit = [f for f in fs if f["lines"] & near and f["criterion"] in ok]
        rows.append({**d, "found": bool(hit), "by": [f["id"] for f in hit][:5]})
        used |= {id(f) for f in hit}
    extra = [f for f in fs if id(f) not in used]
    by_class, by_sev = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for r in rows:
        by_class[r["class"]][0] += r["found"]
        by_class[r["class"]][1] += 1
        by_sev[r["severity"]][0] += r["found"]
        by_sev[r["severity"]][1] += 1
    found = sum(r["found"] for r in rows)
    return {"annotator": ann.get("annotator", ""), "total": len(rows), "found": found,
            "recall": found / len(rows) if rows else 0, "rows": rows, "by_class": dict(by_class), "by_severity": dict(by_sev),
            "agent_only": [{"id": f["id"], "severity": f["severity"], "criterion": f["criterion"], "problem": f["problem"][:160]}
                           for f in extra]}


def to_md(res: dict) -> str:
    pct = lambda a, b: f"{round(100 * a / b)} %" if b else "—"  # noqa: E731
    L = [f"# Внешняя разметка: {res['annotator'] or 'разметчик не указан'}", "",
         f"Найдено агентом: **{res['found']} из {res['total']}** ({pct(res['found'], res['total'])}).", "",
         "| Серьёзность | Найдено |", "|---|---|"]
    L += [f"| {k} | {a} из {b} |" for k, (a, b) in res["by_severity"].items()]
    L += ["", "| Класс | Найдено |", "|---|---|"] + [f"| {k} | {a} из {b} |" for k, (a, b) in res["by_class"].items()]
    L += ["", "## Пропуски агента", ""] + [f"- строки {r['lines']}: {r['class']} ({r['severity']}) — {r.get('note', '')}"
                                           for r in res["rows"] if not r["found"]]
    L += ["", f"## Замечания агента вне разметки ({len(res['agent_only'])}) — отметьте «верно / ложно» для precision", ""]
    L += [f"- [ ] {f['id']} ({f['severity']}, {f['criterion']}): {f['problem']}" for f in res["agent_only"]]
    return "\n".join(L) + "\n"


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        return 2
    ann = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    rep = json.loads(Path(args[1]).read_text(encoding="utf-8"))
    res = score(ann, rep)
    md = to_md(res)
    if "--md" in argv:
        Path(argv[argv.index("--md") + 1]).write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
