"""Автоисправленный документ: проблемные требования заменяются предлагаемыми формулировками.

Структура исходного документа сохраняется (строки, разделы, таблицы); к каждому исправлению — сноска.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass

from .checker import ReviewResult
from .criteria import criterion_name


@dataclass
class Change:
    rid: str
    doc_id: str | None
    before: str
    after: str
    criteria: list[str]
    unified: str = ""  # unified diff формулировки (для UI и патчей)


def collect_changes(rv: ReviewResult) -> list[Change]:
    out = []
    for rr in rv.req_results:
        if rr.rewrite and rr.findings and rr.rewrite.strip() != rr.req.text.strip():
            crit = list(dict.fromkeys(criterion_name(f.criterion) for f in rr.findings))
            ud = "\n".join(difflib.unified_diff([rr.req.text], [rr.rewrite], fromfile=f"{rr.req.doc_id or rr.req.rid} (было)",
                                                tofile=f"{rr.req.doc_id or rr.req.rid} (стало)", lineterm="", n=0))
            out.append(Change(rr.req.rid, rr.req.doc_id, rr.req.text, rr.rewrite, crit, ud))
    return out


def build_fixed_document(rv: ReviewResult) -> tuple[str, list[Change]]:
    changes = collect_changes(rv)
    by_line: dict[int, list] = {}
    for ch in changes:
        rr = next(x for x in rv.req_results if x.req.rid == ch.rid)
        by_line.setdefault(rr.req.line_start, []).append((rr.req, ch))
    lines = rv.doc.lines
    out: list[str] = []
    notes: list[str] = []
    skip_until = 0
    for l in lines:
        if l.lineno <= skip_until:
            continue
        items = by_line.get(l.lineno)
        if not items:
            out.append(l.text)
            continue
        req, ch = items[0]
        n = len(notes) + 1
        mark = f"[^fix{n}]"
        span = "\n".join(x.text for x in lines if req.line_start <= x.lineno <= req.line_end)
        if req.text in span and req.line_start == req.line_end:
            out.append(l.text.replace(req.text, ch.after + " " + mark, 1))
        else:
            first = l.text
            if first.strip().startswith("|"):
                out.append(first.replace(req.text, ch.after + " " + mark, 1) if req.text in first
                           else f"| {req.doc_id or req.rid} | {ch.after} {mark} |")
            else:
                label = f"**{req.doc_id}.** " if req.doc_id else ""
                out.append(f"- {label}{ch.after} {mark}")
            skip_until = req.line_end
        notes.append(f"[^fix{n}]: Исправлено агентом ({ch.rid}): {', '.join(ch.criteria)}. Было: «{' '.join(ch.before.split())}»")
    head = ("> ⚙️ Исправленная версия, сформированная агентом ReqLens. Формулировки — предложения для обсуждения "
            "с заказчиком, а не утверждённые требования.\n")
    body = "\n".join(out).rstrip() + "\n\n---\n\n" + "\n".join(notes) + "\n"
    return head + "\n" + body, changes


def word_diff(a: str, b: str) -> list[tuple[str, str]]:
    """Пословный diff: [(op, text)], op ∈ {'eq','del','ins'}."""
    aw, bw = a.split(), b.split()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, aw, bw).get_opcodes():
        if op == "equal":
            out.append(("eq", " ".join(aw[i1:i2])))
        else:
            if i2 > i1:
                out.append(("del", " ".join(aw[i1:i2])))
            if j2 > j1:
                out.append(("ins", " ".join(bw[j1:j2])))
    return out


def document_diff(rv: ReviewResult, fixed_text: str) -> str:
    """Unified diff всего документа: исходный текст → исправленная версия (файл .diff)."""
    name = rv.doc.path.name
    return "\n".join(difflib.unified_diff([l.text for l in rv.doc.lines], fixed_text.splitlines(),
                                           fromfile=f"a/{name}", tofile=f"b/{name} (исправлено ReqLens)", lineterm="")) + "\n"
