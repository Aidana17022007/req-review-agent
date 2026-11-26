"""Q&A по отчёту с источниками (R6): ответ строится только из проверенных фрагментов.

answer_with_sources(question, report_json, doc_text, kb_index, llm=None) → {"answer", "sources", "mode"}.
Источники трёх видов: требования отчёта (rid), фрагменты документа (строка), фрагменты базы знаний (файл kb/).
Каждый источник проверяется verify.quote_in; модель (если передана) формулирует ответ только по этим фрагментам,
а ссылки на несуществующие источники из ответа удаляются. Без модели — детерминированная сводка источников.
"""
from __future__ import annotations

import json
import re

from ..verify import quote_in
from .lexical import BM25

SYSTEM = ("Ты — ассистент ReqLens. Ответь на вопрос аналитика ТОЛЬКО по приведённым источникам, по-русски, до 6 предложений. "
          "Ссылайся на источники их номерами в квадратных скобках: [1], [2]. Если ответа в источниках нет — так и скажи. "
          'Верни только JSON: {"answer": "..."}')


def _req_sources(report: dict, question: str, k: int) -> list[dict]:
    reqs = report.get("requirements", [])
    docs = [f"{r['rid']} {r.get('doc_id') or ''} {r['text']} " + " ".join(f["problem"] for f in r.get("findings", [])) for r in reqs]
    out = []
    ids = {m.upper().replace(" ", "") for m in re.findall(r"\b[RrРр]-?\s?\d{1,4}\b|\b[А-ЯA-Z]{1,4}-\d{1,4}\b", question)}
    for r in reqs:
        if r["rid"] in ids or (r.get("doc_id") or "").upper() in ids:
            out.append(r)
    if len(out) < k and reqs:
        for i, _ in BM25(docs).search(question, k):
            if reqs[i] not in out:
                out.append(reqs[i])
    res = []
    for r in out[:k]:
        f = r.get("findings", [])
        note = "; ".join(f"{x['severity']}: {x['problem']}" for x in f[:3]) or "замечаний нет"
        res.append({"kind": "requirement", "ref": r["rid"], "label": r.get("doc_id") or r["rid"], "quote": r["text"],
                    "line": r.get("line_start"), "note": note})
    return res


def _doc_sources(doc_text: str, question: str, k: int) -> list[dict]:
    lines = [ln for ln in doc_text.splitlines()]
    idx = [i for i, ln in enumerate(lines) if len(ln.strip()) > 15]
    if not idx:
        return []
    bm = BM25([lines[i] for i in idx])
    return [{"kind": "document", "ref": f"L{idx[j] + 1}", "label": f"строка {idx[j] + 1}", "quote": lines[idx[j]].strip(),
             "line": idx[j] + 1} for j, _ in bm.search(question, k)]


def _kb_sources(kb, question: str, k: int) -> list[dict]:
    if kb is None:
        return []
    return [{"kind": "kb", "ref": c.source, "label": c.section, "quote": c.text, "file": f"kb/{c.source}",
             "url": c.meta.get("url", "")} for c, _ in kb.search(question, k)]


def answer_with_sources(question: str, report: dict, doc_text: str = "", kb=None, llm=None, k: int = 4) -> dict:
    q = (question or "").strip()[:500]
    sources = _req_sources(report, q, k) + _doc_sources(doc_text, q, 2) + _kb_sources(kb, q, 2)
    # проверка источников: требования и строки — дословно в документе (если он есть), kb — в тексте фрагмента
    checked = []
    for s in sources:
        if s["kind"] in ("requirement", "document") and doc_text and not quote_in(s["quote"][:200], doc_text):
            continue
        checked.append(s)
    for n, s in enumerate(checked, 1):
        s["n"] = n
    if llm is not None and getattr(llm, "provider", "") != "mock" and checked:
        try:
            ctx = "\n".join(f"[{s['n']}] ({s['kind']} {s['label']}) {s['quote'][:400]}"
                            + (f" — {s['note']}" if s.get("note") else "") for s in checked)
            data = llm.generate_json(SYSTEM, f"ИСТОЧНИКИ:\n{ctx}\n\nВОПРОС: {q}", task="qa")
            text = str((data or {}).get("answer", "")).strip()
            valid = {str(s["n"]) for s in checked}
            text = re.sub(r"\[(\d+)\]", lambda m: m.group(0) if m.group(1) in valid else "", text)
            if text:
                return {"answer": text, "sources": checked, "mode": "модель по источникам"}
        except Exception:  # лимит API/нет сети — детерминированный ответ ниже
            pass
    if not checked:
        return {"answer": "В отчёте, документе и базе знаний нет фрагментов, относящихся к вопросу.", "sources": [],
                "mode": "по данным отчёта"}
    lines = []
    for s in checked:
        if s["kind"] == "requirement":
            lines.append(f"[{s['n']}] {s['label']}: {s['note']}")
        elif s["kind"] == "document":
            lines.append(f"[{s['n']}] {s['label']} документа: «{s['quote'][:160]}»")
        else:
            lines.append(f"[{s['n']}] {s['label']}: {s['quote'][:200]}")
    return {"answer": "\n".join(lines), "sources": checked, "mode": "по данным отчёта"}


def to_json(res: dict) -> str:
    return json.dumps(res, ensure_ascii=False, indent=2)
