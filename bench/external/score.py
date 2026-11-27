"""Оценка отчёта ReqLens по внешней разметке (bench/external/PROTOCOL.md): совпадение по месту и классу дефекта.

Запуск: python bench/external/score.py annotations.<имя>.json reports/requirements-report.json [--md out.md] [--json out.json]
Никаких регулярных выражений по формулировкам: дефект разметчика найден, если цитата замечания агента лежит в
отмеченных строках документа (±1) и критерий замечания совместим с классом дефекта.

v14 (слепой набор, bench/blind/README.md) — дополнительно, если в разметке есть:
  source — текстовый слой документа (для DOCX / PDF): номера строк разметки считаются по нему;
  clean  — заведомо чистые требования [{"lines": [...], "note": "..."}]: замечание агента в этих строках, не совпавшее
           ни с одним дефектом разметки, считается ложным.
Точность: размеченная = совпавшие / (совпавшие + ложные к чистым); строгая = совпавшие / все замечания (всё, чего
нет в разметке, — как ложное). 95 % интервалы — перцентильный бутстреп (1000 повторов, seed 13), см. aggregate().
"""
from __future__ import annotations

import json
import random
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
SIGNIFICANT = ("critical", "major")


def quote_lines(quote: str, doc_lines: list[str]) -> set[int]:
    """Номера строк документа (с 1), в которых встречается начало цитаты."""
    from req_review.verify import quote_in

    q = " ".join(quote.split())
    probe = q[:60]
    hits = {i for i, ln in enumerate(doc_lines, 1) if probe and quote_in(probe, ln)}
    if not hits and len(q) > 20:  # цитата через несколько строк — ищем по началу
        hits = {i for i, ln in enumerate(doc_lines, 1) if quote_in(q[:25], ln)}
    return hits


def doc_lines(ann: dict, root: Path = ROOT) -> list[str]:
    """Строки, по которым считаются номера разметки: текстовый слой (source) или сам текстовый документ."""
    src = ann.get("source") or ann["document"]
    p = root / src
    if p.suffix.lower() in (".docx", ".pdf"):
        raise ValueError(f"{src}: для DOCX / PDF в разметке нужен текстовый слой — поле source (.txt / .md)")
    return p.read_text(encoding="utf-8").splitlines()


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


def score(ann: dict, report: dict, root: Path = ROOT) -> dict:
    doc = doc_lines(ann, root)
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
    # v14: заведомо чистые требования — замечание в их строках, не совпавшее ни с одним дефектом, ложное
    clean_lines = {n for c in ann.get("clean", []) for n in c["lines"]}
    false_clean = [f for f in extra if f["lines"] & clean_lines]
    clean_hit = [c for c in ann.get("clean", []) if any(set(c["lines"]) & f["lines"] for f in false_clean)]
    by_class, by_sev = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for r in rows:
        by_class[r["class"]][0] += r["found"]
        by_class[r["class"]][1] += 1
        by_sev[r["severity"]][0] += r["found"]
        by_sev[r["severity"]][1] += 1
    found = sum(r["found"] for r in rows)
    matched = len(fs) - len(extra)
    marked = matched + len(false_clean)
    return {"annotator": ann.get("annotator", ""), "document": ann.get("document", ""), "total": len(rows), "found": found,
            "recall": found / len(rows) if rows else 0, "rows": rows, "by_class": dict(by_class), "by_severity": dict(by_sev),
            "findings": len(fs), "findings_significant": sum(f["severity"] in SIGNIFICANT for f in fs),
            "matched": matched, "clean_total": len(ann.get("clean", [])), "clean_flagged": len(clean_hit),
            "false_clean": len(false_clean), "false_clean_significant": sum(f["severity"] in SIGNIFICANT for f in false_clean),
            "precision": matched / marked if marked else None,
            "precision_strict": matched / len(fs) if fs else None,
            # 1 / 0 по каждому замечанию для бутстрепа точности: совпавшие — 1, ложные к чистым — 0
            "_precision_values": [1] * matched + [0] * len(false_clean),
            "_strict_values": [1] * matched + [0] * (len(fs) - matched),
            "agent_only": [{"id": f["id"], "severity": f["severity"], "criterion": f["criterion"], "problem": f["problem"][:160],
                            "on_clean": id(f) in {id(x) for x in false_clean}} for f in extra]}


def bootstrap(values: list[int], reps: int = 1000, seed: int = 13) -> tuple[float, float] | None:
    """95 % перцентильный интервал доли единиц в values (повторы с возвращением, фиксированный seed)."""
    if not values:
        return None
    rnd = random.Random(seed)
    n = len(values)
    stats = sorted(sum(values[rnd.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return stats[int(0.025 * reps)], stats[min(reps - 1, int(0.975 * reps))]


def aggregate(results: list[dict], reps: int = 1000, seed: int = 13) -> dict:
    """Итог по нескольким документам: доли по всем дефектам / замечаниям вместе и 95 % интервалы бутстрепом."""
    rec = [int(r["found"]) for res in results for r in res["rows"]]
    crit = [int(r["found"]) for res in results for r in res["rows"] if r["severity"] == "critical"]
    pv = [v for res in results for v in res["_precision_values"]]
    sv = [v for res in results for v in res["_strict_values"]]
    share = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    return {"found": sum(rec), "total": len(rec), "recall": share(rec), "recall_ci": bootstrap(rec, reps, seed),
            "critical_found": sum(crit), "critical_total": len(crit),
            "findings": sum(r["findings"] for r in results), "matched": sum(r["matched"] for r in results),
            "false_clean": sum(r["false_clean"] for r in results),
            "false_clean_significant": sum(r["false_clean_significant"] for r in results),
            "clean_total": sum(r["clean_total"] for r in results), "clean_flagged": sum(r["clean_flagged"] for r in results),
            "precision": share(pv), "precision_ci": bootstrap(pv, reps, seed),
            "precision_strict": share(sv), "precision_strict_ci": bootstrap(sv, reps, seed),
            "method": f"перцентильный бутстреп, {reps} повторов, seed {seed}"}


def to_md(res: dict) -> str:
    pct = lambda a, b: f"{round(100 * a / b)} %" if b else "—"  # noqa: E731
    L = [f"# Внешняя разметка: {res['annotator'] or 'разметчик не указан'}", "",
         f"Найдено агентом: **{res['found']} из {res['total']}** ({pct(res['found'], res['total'])}).", "",
         "| Серьёзность | Найдено |", "|---|---|"]
    L += [f"| {k} | {a} из {b} |" for k, (a, b) in res["by_severity"].items()]
    L += ["", "| Класс | Найдено |", "|---|---|"] + [f"| {k} | {a} из {b} |" for k, (a, b) in res["by_class"].items()]
    if res.get("clean_total"):
        L += ["", f"Чистые требования: замечания есть у {res['clean_flagged']} из {res['clean_total']}; ложных замечаний "
                  f"к ним {res['false_clean']} (существенных {res['false_clean_significant']})."]
    L += ["", "## Пропуски агента", ""] + [f"- строки {r['lines']}: {r['class']} ({r['severity']}) — {r.get('note', '')}"
                                           for r in res["rows"] if not r["found"]]
    L += ["", f"## Замечания агента вне разметки ({len(res['agent_only'])}) — отметьте «верно / ложно» для precision", ""]
    L += [f"- [ ] {f['id']} ({f['severity']}, {f['criterion']}{', к чистому' if f.get('on_clean') else ''}): {f['problem']}"
          for f in res["agent_only"]]
    return "\n".join(L) + "\n"


def main(argv: list[str]) -> int:
    args = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] not in ("--md", "--json"))]
    if len(args) < 2:
        print(__doc__)
        return 2
    ann = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    rep = json.loads(Path(args[1]).read_text(encoding="utf-8"))
    res = score(ann, rep)
    md = to_md(res)
    if "--md" in argv:
        Path(argv[argv.index("--md") + 1]).write_text(md, encoding="utf-8")
    if "--json" in argv:
        out = {k: v for k, v in res.items() if not k.startswith("_")}
        Path(argv[argv.index("--json") + 1]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
