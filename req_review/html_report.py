"""Интерактивный HTML-отчёт ReqLens («Grammarly для требований»).

Один самодостаточный файл: CSS, JS, иконки и данные встроены, внешних запросов нет — открывается офлайн.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from .criteria import INDIVIDUAL, SET, SEVERITY, criterion_name, criterion_ref
from .fixer import word_diff
from .scoring import METHOD_MD
from .verify import locate as _locate  # общая логика позиций цитат (verify.py)

ORDER = {"critical": 0, "major": 1, "minor": 2}


# ---------------------------------------------------------------- поля схемы 2.2 (RAG): только чтение, всё необязательно

BASIS_KINDS = {"standard", "law", "template"}
# backend (docs/SCHEMA.md 2.2) пишет вид по папке kb/: standards / law_kz / patterns
KIND_ALIASES = {"standards": "standard", "law_kz": "law", "patterns": "template", "pattern": "template"}


def _basis(f) -> list[dict]:
    """Основания замечания из kb/: {source, section, quote, url, kind, license, file} → вид для UI.

    quote — дословный фрагмент файла kb/ (проверен backend-ом); paraphrase — если источник помечен как пересказ.
    """
    out = []
    for b in getattr(f, "basis", None) or []:
        b = b if isinstance(b, dict) else getattr(b, "__dict__", {})
        quote = str(b.get("quote", "") or "").strip()
        source = str(b.get("source", "") or "").strip()
        if not (quote and source):
            continue  # основание без цитаты или источника не показываем
        kind = KIND_ALIASES.get(b.get("kind"), b.get("kind"))
        url = str(b.get("url", "") or "").strip()
        lic = str(b.get("license", "") or "")
        out.append({"kind": kind if kind in BASIS_KINDS else "standard", "source": source,
                    "clause": str(b.get("section") or b.get("clause") or "").strip(), "quote": quote,
                    "url": url if url.startswith("https://") else "", "file": str(b.get("file", "") or ""),
                    "paraphrase": bool(b.get("paraphrase")) or "пересказ" in lic.lower()})
    return out


def _pattern(p, rewrite: str = "") -> dict | None:
    """Шаблон хорошего требования из kb/patterns ({id, title, template, file}) + формулировка агента по нему."""
    if not p:
        return None
    p = p if isinstance(p, dict) else getattr(p, "__dict__", {})
    template = str(p.get("template", "") or "").strip()
    text = str(p.get("text", "") or rewrite or "").strip()
    if not (template or text):
        return None
    return {"title": str(p.get("title", "") or ""), "ears": str(p.get("ears", "") or ""), "template": template, "text": text,
            "file": str(p.get("file", "") or "")}


def _category(key: str) -> str:
    """Ключ категории backend (functional, security…) → подпись на русском."""
    if not key:
        return ""
    try:
        from .categories import CATEGORIES
    except ImportError:  # pragma: no cover — старый backend без категорий
        return key
    label = CATEGORIES.get(key, key)
    return label[:1].upper() + label[1:]


def _coverage(c, process: str = "") -> dict | None:
    """Карта покрытия процесса: backend отдаёт список шагов [{id, title, reqs, covered, question}]."""
    if not c:
        return None
    if isinstance(c, dict):  # формат фикстуры UI: {process, steps: [{…, rids}]}
        process, c = c.get("process", process), c.get("steps", [])
    steps = [{"id": str(x.get("id", i)), "title": str(x.get("title", "")),
              "rids": [str(r) for r in (x.get("reqs") if x.get("reqs") is not None else x.get("rids")) or []],
              "question": str(x.get("question", "") or "")} for i, x in enumerate(c or []) if x.get("title")]
    return {"process": process, "steps": steps} if steps else None


def _verdict(ctx) -> dict:
    rv = ctx.rv
    crit = sum(1 for rr in rv.req_results for f in rr.findings if f.severity == "critical") + \
        sum(1 for f in rv.set_findings if f.severity == "critical")
    major = sum(1 for rr in rv.req_results for f in rr.findings if f.severity == "major") + \
        sum(1 for f in rv.set_findings if f.severity == "major")
    if crit:
        return {"level": "critical", "title": "Не готово", "headline": "Начинать разработку нельзя",
                "text": f"{crit} критичных дефектов: по затронутым требованиям нельзя составить тесты и критерии приёмки."}
    if major:
        return {"level": "major", "title": "Нужны правки", "headline": "Можно начинать условно",
                "text": "Критичных дефектов нет, но существенные замечания нужно закрыть до написания тест-кейсов."}
    return {"level": "ok", "title": "Готово", "headline": "Можно начинать разработку и тестирование",
            "text": "Критичных и существенных дефектов не найдено."}


def build_trace(ctx) -> list[dict]:
    """Шаги прогона для таймлайна «Трассировка агента»: время, длительность, статус и детали."""
    from datetime import datetime, timedelta

    rv, sc = ctx.rv, ctx.scores
    try:
        start = datetime.strptime(ctx.passport["started"][:19], "%Y-%m-%d %H:%M:%S")
    except (KeyError, ValueError):
        start = None
    at = {e["i"]: e["t"] for e in ctx.trace}
    nf = sum(len(r.findings) for r in rv.req_results)
    failed = [r.req.rid for r in rv.req_results if not r.llm_checked]
    method = {"ids": "по ID документа", "modal": "по модальным фразам", "llm": "моделью"}[rv.split.method]
    steps = [
        (0, "Чтение документа", f"{len(rv.doc.lines)} строк · {rv.doc.fmt.upper()}", "ok"),
        (1, "Нарезка требований", f"{len(rv.req_results)} требований · {method}", "ok"),
        (2, "Проверка требований",
         (f"Модель не ответила по {len(failed)} треб.: {', '.join(failed[:4])}" if failed else
          f"{nf} замечаний · тест-проба {sc.tests_ok}/{sc.tests_total}")
         + (f" · отброшено цитат: {len(rv.dropped)}" if rv.dropped else ""), "err" if failed else "ok"),
        (3, "Проверка набора", f"{len(rv.set_findings)} замечаний" if rv.set_llm_checked else
         "Модель не ответила — только детерминированные проверки", "ok" if rv.set_llm_checked else "err"),
        (4, "Домен и глоссарий", f"покрытие чек-листа {rv.domain.coverage_pct}%" if rv.domain else "домен отключён",
         "ok" if rv.glossary is not None else "warn"),
        (5, "Критик-агент", f"отклонено замечаний: {len(rv.rejected)}" if rv.critic_used else "пропущен (профиль fast)",
         "ok" if rv.critic_used else "skip"),
        (6, "Запись отчёта", "Markdown · HTML · JSON · Excel · CSV", "ok"),
    ]
    out = []
    for i, title, detail, status in steps:
        t = at.get(i)
        nxt = next((at[j] for j in range(i + 1, 9) if j in at), None)
        out.append({"title": title, "detail": detail, "status": status,
                    "clock": (start + timedelta(seconds=t)).strftime("%H:%M:%S") if (start and t is not None) else "",
                    "dur": round(nxt - t, 1) if (t is not None and nxt is not None) else None})
    return out


def _depth(rv) -> dict | None:
    """v7: поля 2.3 для HTML (итог за 30 секунд, аудит цитат, учёт строк, покрытие приёмкой, матрица); None — старый отчёт."""
    d = getattr(rv, "depth", None) or {}
    if not d:
        return None
    lc = d.get("line_coverage") or {}
    m = d.get("criteria_matrix") or {}
    return {
        "verdict": d.get("verdict"), "fix_plan": d.get("fix_plan") or [], "citation_audit": d.get("citation_audit"),
        "review_stats": d.get("review_stats"), "acceptance": d.get("acceptance_coverage"),
        "lines": {k: lc.get(k) for k in ("total", "accounted", "percent", "requirements")} | {
            "excluded": lc.get("excluded") or [], "uncovered": (lc.get("uncovered") or [])[:20]} if lc else None,
        # матрица: только требования с замечаниями (компактно; пустые строки не нужны для тепловой карты)
        "matrix": [{"rid": r["rid"], "cells": r["cells"]} for r in m.get("rows", []) if r.get("cells")] if m else [],
    }


def build_data(ctx) -> dict:
    rv, sc = ctx.rv, ctx.scores
    lines = rv.doc.lines
    findings: dict[str, dict] = {}
    marks: dict[int, list] = {}

    def add_mark(lineno, span, fid, sev, kind):
        marks.setdefault(lineno, []).append([span[0], span[1], fid, sev, kind])

    reqs = []
    for rr in rv.req_results:
        r = rr.req
        fids = []
        for i, f in enumerate(rr.findings, 1):
            fid = f"{r.rid}.{i}"
            fids.append(fid)
            findings[fid] = {"fid": fid, "kind": "req", "rid": r.rid, "doc_id": r.doc_id, "criterion": f.criterion,
                             "cname": criterion_name(f.criterion), "cref": criterion_ref(f.criterion), "quote": f.quote,
                             "problem": f.problem, "severity": f.severity, "fix": f.fix, "source": f.source,
                             "confidence": f.confidence, "critic": f.critic_note, "rewrite": rr.rewrite,
                             "location": r.location, "basis": _basis(f)}
            loc = _locate(f.quote, lines, r.line_start, r.line_end, r.text)
            if loc:
                findings[fid]["line"] = loc[0]
                add_mark(loc[0], loc[1], fid, f.severity, "req")
        worst = min((f.severity for f in rr.findings), key=ORDER.get, default="ok")
        reqs.append({"rid": r.rid, "kind": r.kind, "doc_id": r.doc_id, "text": r.text, "section": r.section, "location": r.location,
                     "line": r.line_start, "line_end": r.line_end, "score": sc.req[r.rid], "ears": rr.ears, "rewrite": rr.rewrite,
                     "llm_checked": rr.llm_checked, "note": rr.note, "worst": worst, "findings": fids,
                     "crit": sorted({f.criterion for f in rr.findings}),
                     "test": {"possible": rr.test_possible, "gherkin": rr.test_gherkin, "blocker": rr.test_blocker,
                              "reason": rr.test_reason},
                     # 2.2 (RAG, человек 1): категория и шаблон EARS «плохо → хорошо»; нет данных — поля пустые
                     "category": _category(str(getattr(rr, "category", "") or "")),
                     "rewrite_pattern": _pattern(getattr(rr, "rewrite_pattern", None), rr.rewrite)})
    by_rid = {r.rid: r for r in rv.split.requirements}
    set_list = []
    for i, f in enumerate(rv.set_findings, 1):
        fid = f"S-{i:02d}"
        refs = []
        for ref in f.refs:
            r = by_rid.get(ref.req_id)
            refs.append({"rid": ref.req_id, "quote": ref.quote, "label": (r.doc_id or r.rid) if r else "документ"})
            loc = _locate(ref.quote, lines, r.line_start if r else 0, r.line_end if r else 0)
            if loc:
                add_mark(loc[0], loc[1], fid, f.severity, "set")
                refs[-1]["line"] = loc[0]
        findings[fid] = {"fid": fid, "kind": "set", "set_kind": f.kind, "criterion": f.criterion,
                         "cname": criterion_name(f.criterion), "cref": criterion_ref(f.criterion), "problem": f.problem,
                         "severity": f.severity, "fix": f.fix, "source": f.source, "confidence": f.confidence,
                         "critic": f.critic_note, "refs": refs, "quote": " / ".join(x["quote"] for x in refs), "basis": _basis(f),
                         "values": [{**v, "label": (by_rid[v["rid"]].doc_id or v["rid"]) if v["rid"] in by_rid else v["rid"]}
                                    for v in getattr(f, "values", []) or []]}
        set_list.append(fid)

    # снять пересечения: на строке оставляем более серьёзные метки
    for ln, ms in marks.items():
        ms.sort(key=lambda m: (ORDER[m[3]], m[4] != "req", m[0]))
        kept = []
        for m in ms:
            if all(m[1] <= k[0] or m[0] >= k[1] for k in kept):
                kept.append(m)
        marks[ln] = sorted(kept, key=lambda m: m[0])

    heading = re.compile(r"^\s*#{1,6}\s+")
    for l in lines:
        m = heading.match(l.text)
        if m and l.lineno in marks:
            k = m.end()
            marks[l.lineno] = [[max(0, x[0] - k), max(0, x[1] - k)] + x[2:] for x in marks[l.lineno]]

    set_criteria = []
    for k, v in SET.items():
        fs = [f for f in rv.set_findings if f.criterion == k]
        set_criteria.append({"key": k, "name": v[0], "ref": v[1], "desc": v[2], "count": len(fs),
                             "worst": min((f.severity for f in fs), key=ORDER.get, default="ok"),
                             "fids": [fid for fid in set_list if findings[fid]["criterion"] == k]})
    data = {
        "passport": ctx.passport,
        "mock": "mock" in ctx.model_label,
        "verdict": _verdict(ctx),
        "scores": {"doc": sc.doc_score, "set": sc.set_score, "readiness": sc.readiness, "ready": sc.ready_ids,
                   "tests_ok": sc.tests_ok, "tests_total": sc.tests_total, "cost": sc.cost,
                   "radar_req": [{"key": k, "name": INDIVIDUAL[k][0], "v": v} for k, v in sc.radar_req.items()],
                   "radar_set": [{"key": k, "name": SET[k][0], "v": v} for k, v in sc.radar_set.items()]},
        "counts": {s: sum(1 for f in findings.values() if f["severity"] == s) for s in SEVERITY},
        "lines": [{"n": l.lineno, "t": heading.sub("", l.text) if heading.match(l.text) else l.text, "p": l.page,
                   "h": bool(heading.match(l.text))} for l in lines],
        "marks": marks,
        "reqs": reqs,
        "findings": findings,
        "set": set_list,
        "set_criteria": set_criteria,
        "criteria": [{"key": k, "name": v[0], "ref": v[1]} for k, v in INDIVIDUAL.items()],
        "domain": asdict(rv.domain) | {"coverage": rv.domain.coverage_pct} if rv.domain else None,
        "glossary": asdict(rv.glossary) if rv.glossary else None,
        "questions": [asdict(q) for q in ctx.questions],
        "changes": [{**asdict(c), "diff": word_diff(c.before, c.after)} for c in ctx.changes],
        "fixed_text": ctx.fixed_text,
        "graph": ctx.graph,
        "coverage": _coverage(getattr(ctx, "coverage", None) or getattr(rv, "coverage", None),
                              f"Типовой процесс: {rv.domain.name}" if getattr(rv, "domain", None) else "Типовой процесс"),
        "compare": ctx.compare,
        "rescore": ctx.rescore,
        "dropped": rv.dropped,
        "rejected": rv.rejected,
        "notes": rv.doc.warnings + rv.notes,
        "method": METHOD_MD,
        "split_method": rv.split.method,
        "trace": build_trace(ctx),
        "report_md": getattr(ctx, "report_md", ""),
        "depth": _depth(rv),
    }
    return data


def render_html(ctx) -> str:
    from .ui import env

    data = build_data(ctx)
    # Markdown-отчёт нужен только кнопке «Скачать .md» — хранится сжатым (gzip+base64, распаковка по клику),
    # чтобы HTML-отчёт оставался меньше 1 МБ и на длинных документах
    md = data.pop("report_md", "") or ""
    blob = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")
    tpl = env().get_template("report.html.j2")
    return tpl.render(title=ctx.rv.doc.title, data_json=blob, mock=data["mock"], report_md_b64=gzip_b64(md))


def gzip_b64(text: str) -> str:
    """Текст → gzip (mtime=0, воспроизводимо) → base64 для инлайна в офлайн-HTML."""
    import base64
    import gzip

    return base64.b64encode(gzip.compress(text.encode("utf-8"), 9, mtime=0)).decode("ascii") if text else ""


def write_html(ctx, path: Path) -> None:
    path.write_text(render_html(ctx), encoding="utf-8")
