"""Тесты функций ReqLens v2 (без сети и ключа: LLM_PROVIDER=mock)."""
import json
from pathlib import Path

import pytest

from req_review.checker import Finding, ReqResult, _apply_test_probe
from req_review.cli import main
from req_review.exports import compare
from req_review.fixer import build_fixed_document, word_diff
from req_review.graph import build_graph, mermaid
from req_review.llm import BaseLLM
from req_review.mock_llm import MockLLM
from req_review.pipeline import Options, review_document
from req_review.rules import check_requirement
from req_review.scoring import compute, req_score
from req_review.splitter import Requirement
from req_review.ui import tokens_css

FIX = Path(__file__).parent / "fixtures" / "sample_requirements.md"


@pytest.fixture(scope="module")
def rv():
    return review_document(FIX, MockLLM(), Options(profile="full"), log=lambda m: None)


def _req(text, rid="R-001"):
    return Requirement(rid=rid, doc_id=None, text=text, section="", line_start=1, line_end=1)


# ---------------------------------------------------------------- scoring

def test_req_score_penalties_once_per_criterion():
    f = lambda c, s: Finding("R-001", c, "q", "p", s, "f", "LLM")
    assert req_score([]) == 100
    assert req_score([f("verifiable", "critical"), f("verifiable", "minor")]) == 65
    assert req_score([f("verifiable", "critical"), f("complete", "critical"), f("singular", "critical")]) == 0


def test_compute_scores_are_consistent(rv):
    sc = compute(rv)
    assert 0 <= sc.doc_score <= 100 and 0 <= sc.readiness <= 100
    assert len(sc.radar_req) == 9 and len(sc.radar_set) == 8
    assert sc.tests_total == len(rv.req_results)
    assert sc.cost[0][1] * 100 == pytest.approx(sc.cost[-1][1], rel=0.01)


# ---------------------------------------------------------------- testability probe

def test_probe_impossible_test_becomes_critical_verifiable_finding():
    rr = ReqResult(req=_req("Интерфейс должен быть удобным."))
    _apply_test_probe(rr, {"possible": False, "reason": "нет критерия", "blocker_quote": "должен быть удобным"}, [])
    assert rr.test_possible is False
    assert rr.findings[0].criterion == "verifiable" and rr.findings[0].severity == "critical"
    assert rr.findings[0].source == "тест-проба"


def test_probe_hallucinated_blocker_is_dropped():
    rr, dropped = ReqResult(req=_req("Система должна хранить логи 90 дней.")), []
    _apply_test_probe(rr, {"possible": False, "reason": "x", "blocker_quote": "этого нет"}, dropped)
    assert rr.test_possible is None and not rr.findings and dropped


def test_probe_results_present_in_review(rv):
    probed = [r for r in rv.req_results if r.test_possible is not None]
    assert probed and any(r.test_possible for r in probed) and any(r.test_possible is False for r in probed)
    assert all(r.ears for r in rv.req_results)


# ---------------------------------------------------------------- critic, domain, glossary

def test_critic_sets_confidence_and_logs_rejections(rv):
    assert rv.critic_used
    for rr in rv.req_results:
        for f in rr.findings:
            assert f.confidence in ("high", "medium", "low")


def test_domain_coverage_requires_verified_quotes(rv):
    d = rv.domain
    assert d is not None and len(d.areas) >= 15
    for a in d.areas:
        if a.status != "missing":
            assert a.quotes
    assert any(f.source == "домен" for f in rv.set_findings)


def test_glossary_reads_terms_section(rv):
    terms = {t.term for t in rv.glossary.terms if t.defined}
    assert {"Клиент", "Перевод"} <= terms


def test_kazakh_and_english_vague_words():
    assert any(h.criterion == "verifiable" for h in check_requirement(_req("Жүйе тез жұмыс істеуі керек.")))
    assert any(h.criterion == "verifiable" for h in check_requirement(_req("The system shall be user-friendly.")))


# ---------------------------------------------------------------- fixer, graph, compare

def test_fixed_document_keeps_structure_and_footnotes(rv):
    text, changes = build_fixed_document(rv)
    assert changes
    assert "## 3. Функциональные требования" in text
    assert "[^fix1]:" in text and "Было:" in text


def test_word_diff():
    d = word_diff("должен быстро проверять", "должен проверять за 2 с")
    assert ("del", "быстро") in d and any(op == "ins" for op, _ in d)


def test_graph_has_contradiction_edge_and_mermaid(rv):
    g = build_graph(rv)
    assert any(e["kind"] == "contradiction" for e in g["edges"])
    assert mermaid(g).startswith("graph LR")


def test_compare_statuses():
    old = [{"rid": "R-001", "doc_id": "FR-1", "text": "a b c", "score": 40, "worst": "critical"},
           {"rid": "R-002", "doc_id": "FR-2", "text": "x y z", "score": 100, "worst": "ok"}]
    new = [{"rid": "R-001", "doc_id": "FR-1", "text": "a b c d", "score": 100, "worst": "ok"},
           {"rid": "R-002", "doc_id": "FR-2", "text": "x y z", "score": 65, "worst": "critical"},
           {"rid": "R-003", "doc_id": "FR-3", "text": "new", "score": 100, "worst": "ok"}]
    c = compare(old, new)
    st = {r["rid"]: r["status"] for r in c["rows"]}
    assert st == {"R-001": "fixed", "R-002": "worse", "R-003": "new"}


# ---------------------------------------------------------------- cache

def test_llm_cache_avoids_second_call(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CACHE", "1")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))

    class Fake(BaseLLM):
        provider, model = "fake", "m"

        def _call(self, system, prompt, *, task, context):
            return '{"ok": 1}'

    llm = Fake()
    assert llm.generate_json("s", "p") == {"ok": 1}
    assert llm.generate_json("s", "p") == {"ok": 1}
    assert llm.stats.calls == 1 and llm.stats.cached == 1


# ---------------------------------------------------------------- end to end: все артефакты

def test_full_run_writes_all_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    out = tmp_path / "report.md"
    assert main([str(FIX), str(out), "--env", str(tmp_path / "none.env"), "--profile", "full", "--quiet"]) == 0
    md = out.read_text(encoding="utf-8")
    for s in ("Балл документа", "Готовность к разработке", "Тест-проба", "Доменная полнота", "Вопросы заказчику",
              "Методика оценки", "```mermaid", "Эффект исправлений"):
        assert s in md, s
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "<script" in html and "http://" not in html.split("<body>")[1].replace("http://www.w3.org", "")
    data = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == "2.0" and data["scores"]["document"] >= 0
    assert (tmp_path / "report_traceability.xlsx").stat().st_size > 3000
    assert "Summary" in (tmp_path / "report_jira_import.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert "[^fix1]" in (tmp_path / "report_requirements_fixed.md").read_text(encoding="utf-8")
    # сравнение с предыдущим прогоном по report.json
    out2 = tmp_path / "v2" / "report.md"
    assert main([str(FIX), str(out2), "--env", str(tmp_path / "none.env"), "--compare", str(tmp_path / "report.json"),
                 "--quiet", "--no-xlsx", "--no-jira"]) == 0
    assert "Динамика относительно предыдущей версии" in out2.read_text(encoding="utf-8")


def test_html_highlights_every_finding(rv):
    from datetime import datetime

    from req_review.html_report import build_data
    from req_review.pipeline import build_context

    llm = MockLLM()
    ctx = build_context(rv, llm, Options(), datetime.now().astimezone(), 0.0, str(FIX))
    data = build_data(ctx)
    req_f = [f for f in data["findings"].values() if f["kind"] == "req"]
    assert req_f and all("line" in f for f in req_f)
    for ms in data["marks"].values():
        for a, b in zip(ms, ms[1:]):
            assert a[1] <= b[0]  # метки на строке не пересекаются


def test_tokens_css_has_both_themes():
    css = tokens_css()
    assert "--brand:" in css and '[data-theme="dark"]' in css and "prefers-color-scheme" in css
