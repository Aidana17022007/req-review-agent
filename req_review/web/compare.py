"""Сравнение двух версий документа для экрана Studio «До / После»: баллы, исправленные и новые дефекты.

Работает только с готовыми report.json (схема 2.0) — логику проверки не трогает.
"""
from __future__ import annotations

import difflib
import re

from ..criteria import criterion_name

ORDER = {"critical": 0, "major": 1, "minor": 2}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (s or "").lower().replace("ё", "е"))).strip()


def match_requirements(old: list[dict], new: list[dict]) -> dict[str, str]:
    """old rid → new rid: сначала по ID документа, затем по похожести текста (≥ 0.6)."""
    out, used = {}, set()
    by_doc = {r["doc_id"]: r for r in new if r.get("doc_id")}
    for o in old:
        n = by_doc.get(o.get("doc_id")) if o.get("doc_id") else None
        if n and n["rid"] not in used:
            out[o["rid"]] = n["rid"]
            used.add(n["rid"])
    for o in old:
        if o["rid"] in out:
            continue
        best, ratio = None, 0.0
        for n in new:
            if n["rid"] in used:
                continue
            r = difflib.SequenceMatcher(None, _norm(o["text"]), _norm(n["text"])).ratio()
            if r > ratio:
                best, ratio = n, r
        if best and ratio >= 0.6:
            out[o["rid"]] = best["rid"]
            used.add(best["rid"])
    return out


def _summary(d: dict) -> dict:
    fs = [f for r in d["requirements"] for f in r["findings"]] + list(d.get("set_findings", []))
    sc = d["scores"]
    return {"score": sc["document"], "readiness": sc["readiness"], "set": sc["set"], "reqs": sum(1 for r in d["requirements"] if r.get("kind", "requirement") == "requirement"),
            "tests_ok": sc["tests"]["ok"], "tests_total": sc["tests"]["total"], "findings": len(fs),
            "counts": {s: sum(1 for f in fs if f["severity"] == s) for s in ORDER},
            "document": d.get("passport", {}).get("document", "")}


def diff_reports(old: dict, new: dict) -> dict:
    m = match_requirements(old["requirements"], new["requirements"])
    lbl = lambda r: r.get("doc_id") or r["rid"]  # noqa: E731

    def item(r, f, rid):
        return {"rid": rid, "label": lbl(r), "criterion": f["criterion"], "cname": criterion_name(f["criterion"]),
                "severity": f["severity"], "problem": f["problem"], "quote": f.get("quote", "")}

    def worst_by_key(reqs, key_of):
        acc = {}
        for r in reqs:
            for f in r["findings"]:
                k = key_of(r, f)
                if k not in acc or ORDER[f["severity"]] < ORDER[acc[k][1]["severity"]]:
                    acc[k] = (r, f)
        return acc

    old_keys = worst_by_key(old["requirements"], lambda r, f: (m.get(r["rid"], "old:" + r["rid"]), f["criterion"]))
    new_keys = worst_by_key(new["requirements"], lambda r, f: (r["rid"], f["criterion"]))
    fixed = [item(r, f, m.get(r["rid"])) for k, (r, f) in old_keys.items() if k not in new_keys]
    added = [item(r, f, r["rid"]) for k, (r, f) in new_keys.items() if k not in old_keys]

    # замечания к набору: тип + критерий + множество связанных требований (в нумерации новой версии)
    def set_key(f, mapping):
        return (f["kind"], f["criterion"], frozenset(mapping(x["req_id"]) for x in f.get("refs", []) if x["req_id"] != "DOC"))
    old_set = {set_key(f, lambda rid: m.get(rid, "old:" + rid)): f for f in old.get("set_findings", [])}
    new_set = {set_key(f, lambda rid: rid): f for f in new.get("set_findings", [])}
    sitem = lambda f: {"rid": None, "label": "набор", "criterion": f["criterion"], "cname": criterion_name(f["criterion"]),  # noqa: E731
                       "severity": f["severity"], "problem": f["problem"], "quote": " / ".join(x.get("quote", "") for x in f.get("refs", []))}
    fixed += [sitem(f) for k, f in old_set.items() if k not in new_set]
    added += [sitem(f) for k, f in new_set.items() if k not in old_set]
    sort = lambda xs: sorted(xs, key=lambda x: (ORDER[x["severity"]], x["label"]))  # noqa: E731

    rows = []
    rev = {v: k for k, v in m.items()}
    old_by = {r["rid"]: r for r in old["requirements"]}
    for r in new["requirements"]:
        o = old_by.get(rev.get(r["rid"], ""))
        ws = lambda x: min((f["severity"] for f in x["findings"]), key=ORDER.get, default="ok")  # noqa: E731
        if o is None:
            st = "new"
        elif ws(o) in ("critical", "major") and ws(r) not in ("critical", "major"):
            st = "fixed"
        elif r["score"] > o["score"]:
            st = "improved"
        elif r["score"] < o["score"]:
            st = "worse"
        else:
            st = "same"
        rows.append({"rid": r["rid"], "label": lbl(r), "text": r["text"][:160], "status": st,
                     "before": o["score"] if o else None, "after": r["score"], "worst": ws(r)})
    removed = [{"rid": o["rid"], "label": lbl(o)} for o in old["requirements"] if o["rid"] not in m]
    return {"before": _summary(old), "after": _summary(new), "fixed": sort(fixed), "new": sort(added), "rows": rows, "removed": removed,
            "counts": {k: sum(1 for r in rows if r["status"] == k) for k in ("fixed", "improved", "new", "worse", "same")}}
