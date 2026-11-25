"""Граф требований: противоречия, дубли, ссылки и общие термины."""
from __future__ import annotations

import re

from .checker import ReviewResult

EDGE_KIND = {"contradiction": "contradiction", "duplicate": "duplicate", "dependency": "dependency",
             "terminology": "term"}
ORDER = {"critical": 0, "major": 1, "minor": 2}


def build_graph(rv: ReviewResult) -> dict:
    reqs = rv.split.requirements
    by_doc = {r.doc_id: r.rid for r in reqs if r.doc_id}
    nodes = []
    for rr in rv.req_results:
        worst = min((f.severity for f in rr.findings), key=ORDER.get, default="ok")
        nodes.append({"id": rr.req.rid, "label": rr.req.doc_id or rr.req.rid, "severity": worst,
                      "text": rr.req.short, "section": rr.req.section})
    edges: dict[tuple, dict] = {}

    def add(a, b, kind, title):
        if a == b or a == "DOC" or b == "DOC":
            return
        key = (min(a, b), max(a, b), kind)
        edges.setdefault(key, {"source": key[0], "target": key[1], "kind": kind, "title": title})

    for i, f in enumerate(rv.set_findings, 1):
        kind = EDGE_KIND.get(f.kind)
        if not kind:
            continue
        ids = [r.req_id for r in f.refs if r.req_id != "DOC"]
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                add(ids[x], ids[y], kind, f"S-{i:02d}: {f.problem[:140]}")
    # явные ссылки на другие требования в тексте
    for r in reqs:
        for did, rid in by_doc.items():
            if rid != r.rid and re.search(r"(?<![\w-])" + re.escape(did) + r"(?![\w-])", r.text):
                add(r.rid, rid, "dependency", f"{r.doc_id or r.rid} ссылается на {did}")
    deg: dict[str, int] = {}
    for e in edges.values():
        deg[e["source"]] = deg.get(e["source"], 0) + 1
        deg[e["target"]] = deg.get(e["target"], 0) + 1
    for n in nodes:
        n["degree"] = deg.get(n["id"], 0)
    return {"nodes": nodes, "edges": list(edges.values())}


def mermaid(graph: dict) -> str:
    style = {"contradiction": "-. противоречие .-", "duplicate": "-. дубль .-", "dependency": "-->", "term": "-. термин .-"}
    lines = ["graph LR"]
    used = {e["source"] for e in graph["edges"]} | {e["target"] for e in graph["edges"]}
    for n in graph["nodes"]:
        if n["id"] in used:
            lines.append(f'  {n["id"].replace("-", "_")}["{n["label"]}"]')
    for e in graph["edges"]:
        a, b = e["source"].replace("-", "_"), e["target"].replace("-", "_")
        arrow = style[e["kind"]]
        lines.append(f"  {a} {arrow}> {b}" if arrow.startswith("-.") else f"  {a} {arrow} {b}")
    for n in graph["nodes"]:
        if n["id"] in used and n["severity"] in ("critical", "major"):
            lines.append(f'  style {n["id"].replace("-", "_")} fill:{"#FEECEC" if n["severity"] == "critical" else "#FFF4E0"},'
                         f'stroke:{"#E5484D" if n["severity"] == "critical" else "#F59E0B"}')
    return "\n".join(lines)
