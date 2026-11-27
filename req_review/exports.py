"""Машиночитаемые и командные экспорты: report.json, traceability.xlsx, jira_import.csv; сравнение версий."""
from __future__ import annotations

import csv
import difflib
import json
from dataclasses import asdict
from pathlib import Path

from .criteria import INDIVIDUAL, SEVERITY, criterion_name, criterion_ref
from .verify import norm

SCHEMA_VERSION = "2.5"  # 2.5: bank_rules (чек-лист банка, --rules); 2.4: questions[].qid/closes, answers, decisions, passport.log; 2.3: line_coverage, criteria_matrix, acceptance_coverage, review_stats, verdict, fix_plan; 2.1: span, confidence_score, char_start, tests[], values, unified (только добавления)


# ---------------------------------------------------------------- report.json

def _line_offsets(doc) -> dict[int, int]:
    off, pos = {}, 0
    for line in doc.lines:
        off[line.lineno] = pos
        pos += len(line.text) + 1
    return off


def _finding_json(f, rr, doc, offsets) -> dict:
    from .critic import confidence_score
    from .verify import locate

    d = asdict(f)
    loc = locate(f.quote, doc.lines, rr.req.line_start, rr.req.line_end)
    if loc:
        ln, (a, b) = loc
        d["span"] = {"line": ln, "start": a, "end": b, "offset": offsets.get(ln, 0) + a}
    d["confidence_score"] = confidence_score(f)
    return d


def _set_json(f, doc, by_rid, offsets) -> dict:
    from .critic import confidence_score
    from .verify import locate

    d = {k: v for k, v in asdict(f).items() if k != "refs"}
    refs = []
    for r in f.refs:
        x = asdict(r)
        req = by_rid.get(r.req_id)
        loc = locate(r.quote, doc.lines, req.line_start if req else 0, req.line_end if req else 0)
        if loc:
            x["span"] = {"line": loc[0], "start": loc[1][0], "end": loc[1][1], "offset": offsets.get(loc[0], 0) + loc[1][0]}
        refs.append(x)
    d["refs"] = refs
    d["confidence_score"] = confidence_score(f)
    return d


def _compliance(rv) -> dict:
    from .compliance import to_json as compliance_json

    return compliance_json(rv)


def _trace(rv) -> dict:
    from .traceability import to_json as trace_json

    return trace_json(rv)


def to_json(ctx) -> dict:
    rv, sc = ctx.rv, ctx.scores
    offsets = _line_offsets(rv.doc)
    by_rid = {r.rid: r for r in rv.split.requirements}
    return {
        "schema_version": SCHEMA_VERSION,
        "passport": ctx.passport,
        "scores": {"document": sc.doc_score, "set": sc.set_score, "readiness": sc.readiness,
                   "radar_requirements": sc.radar_req, "radar_set": sc.radar_set,
                   "tests": {"ok": sc.tests_ok, "total": sc.tests_total}, "cost_hours": sc.cost},
        "requirements": [{
            "rid": rr.req.rid, "doc_id": rr.req.doc_id, "text": rr.req.text, "section": rr.req.section,
            "kind": getattr(rr.req, "kind", "requirement"),
            "location": rr.req.location, "line_start": rr.req.line_start, "line_end": rr.req.line_end, "page": rr.req.page,
            "score": sc.req[rr.req.rid], "ears": rr.ears, "rewrite": rr.rewrite, "llm_checked": rr.llm_checked,
            "rewrite_pattern": rr.rewrite_pattern, "category": rr.category,
            "char_start": offsets.get(rr.req.line_start, 0),
            "test": {"possible": rr.test_possible, "gherkin": rr.test_gherkin, "blocker": rr.test_blocker, "reason": rr.test_reason},
            "tests": list(getattr(rr, "test_scenarios", []) or []),
            "findings": [_finding_json(f, rr, rv.doc, offsets) for f in rr.findings],
        } for rr in rv.req_results],
        "set_findings": [_set_json(f, rv.doc, by_rid, offsets) for f in rv.set_findings],
        "domain": asdict(rv.domain) if rv.domain else None,
        "categories": getattr(rv, "categories", {}),
        "coverage_map": getattr(rv, "coverage", []),
        # 2.3 (v5): учёт строк документа, матрица «требование × критерий», покрытие приёмкой, самопроверка, вердикты, план
        **{k: (getattr(rv, "depth", None) or {}).get(k) for k in
           ("line_coverage", "criteria_matrix", "acceptance_coverage", "review_stats", "verdict", "fix_plan",
            "citation_audit")},
        "glossary": asdict(rv.glossary) if rv.glossary else None,
        "questions": [asdict(q) for q in ctx.questions],
        "changes": [asdict(c) for c in ctx.changes],
        "graph": ctx.graph,
        "dropped": rv.dropped,
        "rejected": rv.rejected,
        "compare": ctx.compare,
        "rescore": ctx.rescore,
        **({"answers": ctx.answers} if getattr(ctx, "answers", None) else {}),
        "decisions": list(getattr(ctx, "decisions", []) or []),
        **({"bank_rules": rv.bank_rules} if getattr(rv, "bank_rules", None) else {}),
        **({"traceability": _trace(rv)} if getattr(rv, "traceability", None) else {}),
        **({"compliance": _compliance(rv)} if getattr(rv, "compliance", None) else {}),
    }


# ---------------------------------------------------------------- сравнение версий

def summarize_for_compare(data: dict) -> list[dict]:
    return [{"rid": r["rid"], "doc_id": r.get("doc_id"), "text": r["text"], "score": r["score"],
             "worst": min((f["severity"] for f in r["findings"]), key={"critical": 0, "major": 1, "minor": 2}.get, default="ok")}
            for r in data["requirements"]]


def compare(old: list[dict], new: list[dict]) -> dict:
    used = set()
    rows = []
    for n in new:
        match = None
        if n.get("doc_id"):
            match = next((o for o in old if o.get("doc_id") == n["doc_id"] and o["rid"] not in used), None)
        if match is None:
            best, ratio = None, 0.0
            for o in old:
                if o["rid"] in used:
                    continue
                r = difflib.SequenceMatcher(None, norm(o["text"]), norm(n["text"])).ratio()
                if r > ratio:
                    best, ratio = o, r
            match = best if ratio >= 0.6 else None
        if match is None:
            rows.append({"rid": n["rid"], "doc_id": n.get("doc_id"), "status": "new", "before": None, "after": n["score"]})
            continue
        used.add(match["rid"])
        d = n["score"] - match["score"]
        if match["worst"] in ("critical", "major") and n["worst"] not in ("critical", "major"):
            st = "fixed"
        elif d < 0:
            st = "worse"
        elif d > 0:
            st = "improved"
        else:
            st = "same"
        rows.append({"rid": n["rid"], "doc_id": n.get("doc_id"), "status": st, "before": match["score"], "after": n["score"]})
    removed = [o for o in old if o["rid"] not in used]
    avg = lambda xs: round(sum(x["score"] for x in xs) / len(xs)) if xs else 0
    return {"rows": rows, "removed": [{"rid": o["rid"], "doc_id": o.get("doc_id")} for o in removed],
            "score_before": avg(old), "score_after": avg(new),
            "counts": {k: sum(1 for r in rows if r["status"] == k) for k in ("fixed", "improved", "new", "worse", "same")}}


# ---------------------------------------------------------------- Jira CSV

def write_jira_csv(ctx, path: Path) -> None:
    prio = {"critical": "Highest", "major": "High", "minor": "Low"}
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Summary", "Description", "Priority", "Labels", "Issue Type"])
        for rr in ctx.rv.req_results:
            r = rr.req
            for f in rr.findings:
                w.writerow([f"[{r.doc_id or r.rid}] {criterion_name(f.criterion)}: {f.problem[:120]}",
                            f"Требование: {r.text}\nМесто: {r.location}\nЦитата: «{f.quote}»\nПроблема: {f.problem}\n"
                            f"Как исправить: {f.fix}\nКритерий: {criterion_ref(f.criterion)}\nИсточник: {f.source}",
                            prio[f.severity], f"requirements-review {f.criterion} {f.severity}", "Task"])
        for i, f in enumerate(ctx.rv.set_findings, 1):
            refs = "\n".join(f"- {x.req_id}: «{x.quote}»" for x in f.refs)
            w.writerow([f"[S-{i:02d}] {criterion_name(f.criterion)}: {f.problem[:120]}",
                        f"Ссылки:\n{refs}\nПроблема: {f.problem}\nКак исправить: {f.fix}\nКритерий: {criterion_ref(f.criterion)}",
                        prio[f.severity], f"requirements-review {f.criterion} {f.severity}", "Task"])


# ---------------------------------------------------------------- Excel

def write_xlsx(ctx, path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.formatting.rule import FormulaRule
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    brand = PatternFill("solid", fgColor="0B5FFF")
    fills = {"Критичный": "FEECEC", "Существенный": "FFF4E0", "Незначительный": "FEF9E1"}
    wb = Workbook()

    def sheet(title, header, rows, widths, sev_col=None):
        ws = wb.create_sheet(title)
        ws.append(header)
        for c in ws[1]:
            c.fill, c.font = brand, Font(bold=True, color="FFFFFF")
            c.alignment = Alignment(vertical="center", wrap_text=True)
        for row in rows:
            ws.append(row)
        for i, wdt in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = wdt
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(vertical="top", wrap_text=True)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        if sev_col and ws.max_row > 1:
            col = get_column_letter(sev_col)
            rng = f"A2:{get_column_letter(len(header))}{ws.max_row}"
            for label, color in fills.items():
                ws.conditional_formatting.add(rng, FormulaRule(formula=[f'${col}2="{label}"'],
                                                               fill=PatternFill("solid", fgColor=color)))
        return ws

    rv, sc = ctx.rv, ctx.scores
    sheet("Требования", ["ID в отчёте", "ID в документе", "Раздел", "Место", "Текст", "Балл", "EARS", "Нарушений", "Предлагаемая формулировка"],
          [[rr.req.rid, rr.req.doc_id or "—", rr.req.section, rr.req.location, rr.req.text, sc.req[rr.req.rid], rr.ears,
            len(rr.findings), rr.rewrite] for rr in rv.req_results], [11, 12, 22, 28, 60, 8, 12, 10, 60])
    sheet("Нарушения", ["ID", "ID в документе", "Критерий", "Пункт стандарта", "Цитата", "Проблема", "Серьёзность", "Как исправить", "Источник", "Уверенность"],
          [[rr.req.rid, rr.req.doc_id or "—", criterion_name(f.criterion), criterion_ref(f.criterion), f.quote, f.problem,
            SEVERITY[f.severity], f.fix, f.source, f.confidence] for rr in rv.req_results for f in rr.findings]
          + [[f"S-{i:02d}", ", ".join(r.req_id for r in f.refs), criterion_name(f.criterion), criterion_ref(f.criterion),
              " / ".join(r.quote for r in f.refs), f.problem, SEVERITY[f.severity], f.fix, f.source, f.confidence]
             for i, f in enumerate(rv.set_findings, 1)],
          [9, 14, 22, 24, 40, 60, 14, 50, 12, 11], sev_col=7)
    sheet("Тест-кейсы", ["ID", "ID в документе", "Тест составлен", "Gherkin", "Почему нельзя", "Блокирующий фрагмент"],
          [[rr.req.rid, rr.req.doc_id or "—", {True: "да", False: "нет", None: "—"}[rr.test_possible], rr.test_gherkin,
            rr.test_reason, rr.test_blocker] for rr in rv.req_results], [9, 14, 12, 70, 40, 40])
    crit_keys = list(INDIVIDUAL)
    matrix = []
    for rr in rv.req_results:
        worst = {}
        for f in rr.findings:
            worst.setdefault(f.criterion, SEVERITY[f.severity])
        matrix.append([rr.req.rid, rr.req.doc_id or "—"] + [worst.get(k, "✓") for k in crit_keys])
    sheet("Матрица трассировки", ["ID", "ID в документе"] + [INDIVIDUAL[k][0] for k in crit_keys], matrix,
          [9, 14] + [16] * len(crit_keys))
    sheet("Вопросы", ["Раздел", "Ссылка", "Вопрос", "Серьёзность"],
          [[q.section, q.ref, q.text, SEVERITY[q.severity]] for q in ctx.questions], [24, 18, 100, 14], sev_col=4)
    del wb["Sheet"]
    wb.save(path)


def write_json(ctx, path: Path) -> None:
    path.write_text(json.dumps(to_json(ctx), ensure_ascii=False, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------- tests.feature (Gherkin, русский)

def feature_text(ctx) -> str:
    rv, p = ctx.rv, ctx.passport
    ok = [rr for rr in rv.req_results if rr.test_possible]
    bad = [rr for rr in rv.req_results if rr.test_possible is False]
    out = ["# language: ru", f"# Сгенерировано ReqLens · {p.get('agent_version', '')} · {p.get('started', '')}",
           f"# Документ: {p.get('document', '')}", f"# Тестируемо {len(ok)} из {len(ok) + len(bad)} требований", "",
           f"Функция: Приёмочные тесты — {p.get('document', '')}", ""]
    for rr in ok:
        r = rr.req
        out.append(f"  # {r.rid}{f' · {r.doc_id}' if r.doc_id else ''} · {r.location}")
        scen = rr.test_scenarios or [{"title": r.doc_id or r.rid, "gherkin": rr.test_gherkin}]
        for x in scen:
            out.append(f"  Сценарий: {x['title']}")
            out += ["    " + ln.strip() for ln in x["gherkin"].splitlines() if ln.strip() and not ln.strip().startswith("Сценарий")]
            out.append("")
    if bad:
        out.append("  # ---- Тест составить невозможно (доказательство непроверяемости) ----")
        for rr in bad:
            out.append(f"  # {rr.req.doc_id or rr.req.rid}: {rr.test_reason} · мешает «{rr.test_blocker}»")
    return "\n".join(out) + "\n"
