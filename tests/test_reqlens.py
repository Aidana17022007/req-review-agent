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
    # самодостаточный файл: нет внешних скриптов, стилей, шрифтов и картинок
    import re as _re
    assert "<script" in html
    assert not _re.search(r'<(script|img|iframe)[^>]+src="https?://|<link[^>]+href="https?://|url\(\s*["\']?https?://|@import', html)
    assert "reportMD()" in html and '"trace"' in html  # «Скачать отчёт» и таймлайн агента
    # Markdown-отчёт встроен сжатым и распаковывается ровно в report.md; сам HTML — меньше 1 МБ
    import base64 as _b64
    import gzip as _gz
    blob = _re.search(r'<script type="application/octet-stream" id="report-md"[^>]*>([^<]+)</script>', html).group(1)
    assert _gz.decompress(_b64.b64decode(blob)).decode("utf-8") == md
    assert '"report_md"' not in html
    assert len(html.encode("utf-8")) < 1_000_000
    _check_offline_3d_bundle(html)
    data = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == "2.3" and data["scores"]["document"] >= 0
    assert (tmp_path / "report_traceability.xlsx").stat().st_size > 3000
    assert "Summary" in (tmp_path / "report_jira_import.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert "[^fix1]" in (tmp_path / "report_requirements_fixed.md").read_text(encoding="utf-8")
    # сравнение с предыдущим прогоном по report.json
    out2 = tmp_path / "v2" / "report.md"
    assert main([str(FIX), str(out2), "--env", str(tmp_path / "none.env"), "--compare", str(tmp_path / "report.json"),
                 "--quiet", "--no-xlsx", "--no-jira"]) == 0
    assert "Динамика относительно предыдущей версии" in out2.read_text(encoding="utf-8")


def _check_offline_3d_bundle(html: str):
    """3D-движок встроен в отчёт (gzip+base64), распаковывается лениво; новые разделы на месте."""
    import base64
    import gzip
    import re as _re

    m = _re.search(r'<script type="application/octet-stream" id="lib-3d"[^>]*>([A-Za-z0-9+/=]+)</script>', html)
    assert m, "нет встроенного бандла 3D"
    js = gzip.decompress(base64.b64decode(m.group(1))).decode("utf-8")
    assert "ForceGraph3D" in js
    for marker in ('RENDER.graph', 'renderDoc', 'renderTests', 'renderFixes', 'tests.feature', 'id="hlpop"'):
        assert marker in html, marker


def test_html_highlights_every_finding(rv):
    from datetime import datetime

    from req_review.html_report import build_data
    from req_review.pipeline import build_context

    llm = MockLLM()
    ctx = build_context(rv, llm, Options(), datetime.now().astimezone(), 0.0, str(FIX))
    data = build_data(ctx)
    req_f = [f for f in data["findings"].values() if f["kind"] == "req"]
    assert req_f and all("line" in f for f in req_f)
    # диапазон строк требования — для перехода «таблица → документ»
    assert all(r["line"] <= r["line_end"] for r in data["reqs"] if r["line"])
    for ms in data["marks"].values():
        for a, b in zip(ms, ms[1:]):
            assert a[1] <= b[0]  # метки на строке не пересекаются


def test_tokens_css_has_both_themes():
    from req_review.ui import load_tokens

    css, t = tokens_css(), load_tokens()
    assert f"--brand: {t['color']['light']['brand']}" in css and f"--brand: {t['color']['dark']['brand']}" in css
    assert '[data-theme="dark"]' in css and '[data-theme="light"]' in css and "--grad-hero:" in css


def test_vague_goal_without_mechanism_is_unverifiable():
    # R-017 / SEC-03: «обеспечивать защиту от мошенничества» — цель без механизма и критерия приёмки
    from req_review.reader import read_document
    from req_review.splitter import split_requirements

    hits = check_requirement(_req("Система должна обеспечивать защиту от мошенничества."))
    assert any(h.criterion == "verifiable" and h.severity == "critical" for h in hits)
    s = split_requirements(read_document(FIX))
    sec03 = next(r for r in s.requirements if r.doc_id == "SEC-03")
    assert any(h.criterion == "verifiable" for h in check_requirement(sec03))
    # конкретное требование с числами не должно ловиться этим правилом
    ok = check_requirement(_req("После 5 неверных вводов кода операция должна блокироваться на 30 минут."))
    assert not any(h.criterion == "verifiable" for h in ok)


def test_slides_hide_mock_metrics_and_placeholder_team(tmp_path):
    from req_review.ui.styleguide import bench_metrics, team

    res = tmp_path / "RESULTS.md"
    res.write_text("*Модель:* mock / mock-heuristic · x\n| Recall | **69 %** (9 из 13) |\n| Precision | **100 %** |\n", encoding="utf-8")
    m = bench_metrics(res)
    assert m["recall"] == "—" and "ещё не запускался" in m["model_note"] and "выше" not in m["model_note"]
    real = tmp_path / "REAL.md"
    real.write_text("*Модель:* gemini / gemini-3.8-flash · x\n| Recall | **85 %** (34 из 40) |\n", encoding="utf-8")
    assert bench_metrics(real)["recall"] == "85%"
    y = tmp_path / "team.yaml"
    y.write_text('team:\n  - name: "Имя Фамилия"\n    role: "x"\n  - name: "Айдана С."\n    role: "UI"\n', encoding="utf-8")
    assert [t["name"] for t in team(y)] == ["Айдана С."]


def test_numeric_conflicts_are_precise():
    from req_review.numbers import find_conflicts
    from req_review.reader import read_document
    from req_review.splitter import split_requirements

    s = split_requirements(read_document(FIX))
    pairs = {(c.a.rid, c.b.rid) for c in find_conflicts(s.requirements)}
    assert ("R-015", "R-016") in pairs  # 3 vs 5 неверных вводов
    assert ("R-003", "R-005") in pairs  # 500 000 vs 300 000 тенге за операцию
    assert not any("R-005" in p and "R-011" in p for p in pairs)  # «в сутки» vs «за операцию» — не конфликт
    clean = split_requirements(read_document(Path(__file__).parent.parent / "bench" / "docs" / "payments.md"))
    assert find_conflicts(clean.requirements) == []  # чистый документ — без ложных противоречий


def test_benchmark_has_40_plus_known_defects():
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent / "bench"))
    from inject import build_all

    truth = build_all()
    assert truth["total_defects"] >= 80 and len(truth["documents"]) == 6
    for name in ("deposit_kk", "cards"):  # v5: казахский документ и DOCX с таблицами — по 10–15 дефектов
        assert 10 <= len(truth["documents"][name]["defects"]) <= 15
    import docx

    d = docx.Document(str(Path(__file__).parent.parent / truth["documents"]["cards"]["file"]))
    assert len(d.tables) >= 3 and any(c.text == "CRD-15" for t in d.tables for r in t.rows for c in r.cells)


def test_compare_cli(tmp_path, monkeypatch):
    from req_review.compare import diff_reports
    from req_review.compare import main as cmp_main

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    out = tmp_path / "r.md"
    assert main([str(FIX), str(out), "--env", str(tmp_path / "x.env"), "--quiet", "--no-xlsx", "--no-jira"]) == 0
    data = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == "2.3"
    f = next(f for r in data["requirements"] for f in r["findings"])
    assert "span" in f and 0 < f["confidence_score"] <= 1
    res = diff_reports(data, data)
    assert res["defects_new"] == [] and res["defects_fixed"] == []
    assert cmp_main([str(tmp_path / "r.json"), str(tmp_path / "r.json"), "--md", str(tmp_path / "c.md")]) == 0
    assert (tmp_path / "r_tests.feature").read_text(encoding="utf-8").startswith("# language: ru")
