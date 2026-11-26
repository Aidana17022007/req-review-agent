"""Предпросмотр HTML-отчёта на фикстуре схемы 2.2 — UI можно делать до готовности RAG-backend.

    python -m req_review.ui.preview [tests/fixtures/report_v22.json] [reports/preview_v22.html]

Документ прогоняется mock-моделью (без сети и ключа), затем поля 2.2 из фикстуры (basis, category, rewrite_pattern,
coverage, passport.context_mode) накладываются на объекты прогона — и отчёт рендерится обычным render_html.
Так проверяется ровно тот путь, по которому поля придут от backend.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "report_v22.json"
DOC = ROOT / "tests" / "fixtures" / "sample_requirements.md"


def overlay(ctx, data: dict) -> None:
    """Наложить поля 2.2 из report.json на контекст прогона (по rid требования, критерию и цитате замечания)."""
    by_rid = {r["rid"]: r for r in data.get("requirements", [])}
    for rr in ctx.rv.req_results:
        src = by_rid.get(rr.req.rid)
        if not src:
            continue
        rr.category = src.get("category", "")
        rr.rewrite_pattern = src.get("rewrite_pattern")
        pool = list(src.get("findings", []))
        for f in rr.findings:
            m = next((x for x in pool if x["criterion"] == f.criterion and x["quote"] == f.quote), None) or \
                next((x for x in pool if x["criterion"] == f.criterion), None)
            if m:
                pool.remove(m)
                f.basis = m.get("basis", [])
    for f, src in zip(ctx.rv.set_findings, data.get("set_findings", [])):
        f.basis = src.get("basis", [])
    ctx.coverage = data.get("coverage")
    for k in ("context_mode", "context_chunks", "tokens_per_call"):
        if k in data.get("passport", {}):
            ctx.passport[k] = data["passport"][k]


def build_ctx(doc: Path = DOC, fixture: Path | None = FIXTURE):
    from ..mock_llm import MockLLM
    from ..pipeline import Options, build_context, review_document

    llm, opts = MockLLM(), Options(profile="fast")
    t0 = time.monotonic()
    rv = review_document(doc, llm, opts, log=lambda m: None)
    ctx = build_context(rv, llm, opts, datetime.now().astimezone(), t0, str(doc.relative_to(ROOT) if doc.is_relative_to(ROOT) else doc))
    ctx.trace = [{"i": i, "t": round(i * 0.4, 2)} for i in range(8)]
    if fixture:
        overlay(ctx, json.loads(Path(fixture).read_text(encoding="utf-8")))
    return ctx


def main(argv: list[str]) -> Path:
    from ..html_report import write_html

    fixture = Path(argv[0]) if argv else FIXTURE
    out = Path(argv[1]) if len(argv) > 1 else ROOT / "reports" / "preview_v22.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_html(build_ctx(DOC, fixture), out)
    print(out)
    return out


if __name__ == "__main__":
    main(sys.argv[1:])
