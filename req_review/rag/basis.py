"""Основания замечаний из базы знаний (R2): критерий стандарта, норма РК, шаблон хорошего требования.

Каждая цитата основания — дословный фрагмент файла kb/ (проверяется verify.quote_in); иначе основание не ставится.
Модель здесь не участвует: связь «замечание → пункт стандарта» детерминирована по ключу критерия,
норма РК и шаблон подбираются поиском и включаются только при достаточной лексической близости.
"""
from __future__ import annotations

import re

from ..verify import quote_in
from .index import KB_DIR, Index

LAW_MIN_SCORE = 6.0  # порог «сырого» BM25 для нормы РК: ниже — норма не релевантна, не притягиваем за уши
PATTERN_MIN_SCORE = 4.0
LAW_CRITERIA = {"complete", "verifiable", "unambiguous", "set_complete", "set_consistent", "correct"}
# Шаблон правки подходит только требованиям своих категорий (categories.CATEGORIES): лексическое совпадение
# со словом из примера «Плохо: …» (например, «надёжное подтверждение» у otp) не должно притягивать шаблон
# OTP к требованию «Система должна быть надёжной». Шаблоны без записи здесь подходят любой категории.
PATTERN_CATEGORIES = {
    "limit": {"functional", "data", "integration", "interface", "acceptance"},
    "otp": {"security"},
    "idempotency": {"functional", "integration"},
    "status": {"functional", "integration", "interface"},
    "notify": {"functional", "interface", "performance", "integration"},
    "threshold": {"functional", "interface", "acceptance"},
    "timezone": {"functional", "data", "acceptance"},
    "api_method": {"integration", "interface"},
    "audit": {"data", "security", "regulatory"},
    "retention": {"data", "regulatory"},
    "sla": {"performance", "availability"},
}


def pattern_fits(pattern_id: str, category: str | None) -> bool:
    allowed = PATTERN_CATEGORIES.get(pattern_id)
    return not allowed or not category or category == "other" or category in allowed


def _key(section: str) -> str:
    return section.split("·")[0].strip()


def _first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    return (m.group(1) if m else text).strip()


def _basis(c, raw: str) -> dict | None:
    q = _first_sentence(c.text)
    if not quote_in(q, raw):  # дословно ли цитата лежит в файле базы знаний
        return None
    return {"source": c.meta.get("title", c.source), "section": c.section.split("·", 1)[-1].strip(), "quote": q,
            "url": c.meta.get("url", ""), "kind": c.meta.get("kind", ""), "license": c.meta.get("license", ""),
            "file": f"kb/{c.source}"}


def attach_basis(rv, kb: Index, log=print) -> dict:
    raw = {}
    for c in kb.chunks:
        if c.source not in raw:
            p = KB_DIR / c.source
            raw[c.source] = p.read_text(encoding="utf-8") if p.exists() else c.text
    std = {_key(c.section): c for c in kb.chunks if c.meta.get("kind") == "standards"}
    law_idx = [i for i, c in enumerate(kb.chunks) if c.meta.get("kind") == "law_kz"]
    pat_idx = [i for i, c in enumerate(kb.chunks) if c.meta.get("kind") == "patterns"]
    stats = {"basis": 0, "law": 0, "patterns": 0}

    def best(idx: list[int], query: str, min_score: float):
        if not idx:
            return None
        sc = kb.bm25.scores(query)
        i = max(idx, key=lambda j: sc[j])
        return kb.chunks[i] if sc[i] >= min_score else None

    def link(f, text: str):
        out = []
        c = std.get(f.criterion)
        if c and (b := _basis(c, raw[c.source])):
            out.append(b)
        if f.criterion in LAW_CRITERIA and (lc := best(law_idx, f"{text} {f.problem}", LAW_MIN_SCORE)):
            if b := _basis(lc, raw[lc.source]):
                out.append(b)
                stats["law"] += 1
        f.basis = out
        stats["basis"] += bool(out)

    for rr in rv.req_results:
        for f in rr.findings:
            link(f, rr.req.text)
        fit = [i for i in pat_idx if pattern_fits(_key(kb.chunks[i].section), getattr(rr, "category", None))]
        if rr.findings and rr.rewrite and (pc := best(fit, rr.req.text, PATTERN_MIN_SCORE)):
            tpl = next((s for s in re.split(r"(?<=[.!?])\s+", pc.text) if s.startswith("Шаблон")), _first_sentence(pc.text))
            if quote_in(tpl, raw[pc.source]):
                rr.rewrite_pattern = {"id": _key(pc.section), "title": pc.section.split("·", 1)[-1].strip(), "template": tpl,
                                      "file": f"kb/{pc.source}"}
                stats["patterns"] += 1
    by_rid = {r.req.rid: r.req.text for r in rv.req_results}
    for f in rv.set_findings:
        link(f, " ".join(by_rid.get(r.req_id, r.quote) for r in f.refs))
    log(f"  база знаний: основания у {stats['basis']} замечаний (нормы РК: {stats['law']}), шаблонов правок: {stats['patterns']}")
    return stats
