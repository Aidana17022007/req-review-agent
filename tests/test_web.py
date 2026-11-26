"""ReqLens Studio: загрузка → живые события → артефакты, ассистент, сравнение версий (mock, без сети)."""
import json
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from req_review.web.app import JOBS, app  # noqa: E402
from req_review.web.assistant import Assistant  # noqa: E402
from req_review.web.live import classify_error  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "sample_requirements.md"


def _wait(job):
    for _ in range(200):
        if JOBS[job].done:
            return
        time.sleep(0.05)


def _events(c, job):
    return [json.loads(line[6:]) for line in c.get(f"/api/jobs/{job}/events").text.splitlines() if line.startswith("data: ")]


@pytest.fixture(scope="module")
def studio():
    mp = pytest.MonkeyPatch()
    mp.setenv("LLM_PROVIDER", "mock")
    mp.setenv("STUDIO_DEMO_DELAY", "0")
    c = TestClient(app)
    r = c.post("/api/review", files={"file": ("req.md", FIX.read_bytes(), "text/markdown")}, data={"profile": "fast", "domain": "fintech"})
    assert r.status_code == 200
    job = r.json()["job"]
    _wait(job)
    yield c, job
    mp.undo()


def test_studio_flow(studio):
    c, job = studio
    assert "ReqLens" in c.get("/").text
    assert JOBS[job].done and not JOBS[job].error
    events = _events(c, job)
    kinds = [e["kind"] for e in events]
    assert kinds[-1] == "done"
    # живой прогон: число требований после нарезки и пакеты по мере проверки
    assert "split" in kinds and "batch_start" in kinds and "batch_done" in kinds
    started = {r["rid"] for e in events if e["kind"] == "batch_start" for r in e["reqs"]}
    assert started == {r["rid"] for r in events[-1]["summary"]["rows"]}
    html_name = next(v for v in JOBS[job].artifacts.values() if v.endswith(".html"))
    assert c.get(f"/jobs/{job}/{html_name}").status_code == 200
    assert c.get(f"/jobs/{job}/../../etc/passwd").status_code == 404


def test_studio_health_and_sample(studio):
    c, _ = studio
    h = c.get("/api/health").json()
    assert h["provider"] == "mock" and h["key_ok"] and "key" not in {k for k in h if "secret" in k}
    assert "FR-01" in c.get("/api/sample").text


def test_health_reports_missing_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    h = TestClient(app).get("/api/health").json()
    assert h["key_ok"] is False and h["key_name"] == "GEMINI_API_KEY"


def test_assistant_answers_with_links(studio):
    c, job = studio
    r = c.post(f"/api/jobs/{job}/ask", json={"q": "Почему R-006 критичное?"}).json()
    assert "[[R-006]]" in r["answer"] and "R-006" in r["refs"] and r["source"] == "отчёт"
    first = c.post(f"/api/jobs/{job}/ask", json={"q": "Что исправить первым?"}).json()
    assert first["refs"] and first["answer"].startswith("Исправить в первую очередь")
    by_doc_id = c.post(f"/api/jobs/{job}/ask", json={"q": "что не так с FR-02"}).json()
    assert "R-002" in by_doc_id["refs"]
    assert c.post("/api/jobs/nope/ask", json={"q": "x"}).status_code == 404


def test_assistant_unknown_refs_are_not_links():
    data = {"requirements": [{"rid": "R-001", "doc_id": None, "text": "t", "score": 100, "findings": [], "test": {}}],
            "set_findings": [], "scores": {"document": 100, "set": 100, "readiness": 100, "tests": {"ok": 0, "total": 1}}}
    a = Assistant(data)
    assert a._reply("см. [[R-999]] и [[R-001]]")["answer"] == "см. R-999 и [[R-001]]"


def test_assistant_quota_error_is_fast_and_friendly(monkeypatch):
    """Свободный вопрос при исчерпанной квоте: без многоминутных ретраев, с понятным ответом."""
    import req_review.llm as llm_mod
    from req_review.llm import GeminiLLM

    calls = []

    class R:
        status_code, headers, text = 429, {}, '{"error":{"details":[{"retryDelay":"5s"}]}}'

    def fake_post(*a, **k):
        calls.append(1)
        return R()

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    data = {"requirements": [{"rid": "R-001", "doc_id": None, "text": "t", "score": 100, "findings": [], "test": {}}],
            "set_findings": [], "scores": {"document": 100, "set": 100, "readiness": 100, "tests": {"ok": 0, "total": 1}}}
    out = Assistant(data).ask_llm("расскажи что-нибудь необычное", lambda: GeminiLLM(api_key="k", model="m"))
    assert out and out["source"] == "подсказка" and "типовые вопросы" in out["answer"]
    assert len(calls) <= 2  # одна попытка + один повтор, а не 7


def test_compare_fixed_version(studio):
    c, job = studio
    r = c.post(f"/api/jobs/{job}/compare", data={"use_fixed": "true"})
    assert r.status_code == 200, r.text
    new = r.json()["job"]
    _wait(new)
    assert not JOBS[new].error
    cmp = _events(c, new)[-1]["summary"]["compare"]
    assert cmp["before"]["score"] <= cmp["after"]["score"]
    assert cmp["fixed"] and isinstance(cmp["new"], list)
    assert {r["status"] for r in cmp["rows"]} <= {"fixed", "improved", "new", "worse", "same"}


def test_error_classification():
    assert classify_error("Не задан GEMINI_API_KEY. Получите ключ") == "key"
    assert classify_error("Gemini HTTP 403: PERMISSION_DENIED") == "key"
    assert classify_error("Квота модели gemini исчерпана (API просит подождать ≈5.0 ч)") == "quota"
    assert classify_error("Файл повреждён") == "error"
    assert classify_error("В документе не найдено ни одного требования.") == "noreqs"


def test_studio_rejects_bad_format():
    r = TestClient(app).post("/api/review", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400


# ---------------------------------------------------------------- v6: поля схемы 2.2 в отчёте, ассистент с источниками, режим «Демо»

FIX22 = Path(__file__).parent / "fixtures" / "report_v22.json"


def test_report_renders_v22_fields_from_fixture():
    from req_review.html_report import build_data, render_html
    from req_review.ui.preview import build_ctx

    ctx = build_ctx(fixture=FIX22)
    d = build_data(ctx)
    basis = [b for f in d["findings"].values() for b in f["basis"]]
    assert basis and all(b["quote"] and b["source"] for b in basis)
    assert any(b["kind"] == "law" and b["url"].startswith("https://adilet.zan.kz/") for b in basis)
    assert d["coverage"]["steps"] and any(not s["rids"] and s["question"] for s in d["coverage"]["steps"])
    assert all(r["category"] for r in d["reqs"]) and any(r["rewrite_pattern"] for r in d["reqs"])
    assert d["passport"]["context_mode"] == "rag"
    html = render_html(ctx)
    for marker in ("renderKB", "renderCoverage", "basisHTML", "patternHTML", 'id="btn-lang"', "reqlens-lang", "ensureLine"):
        assert marker in html, marker


def test_report_without_v22_fields_hides_new_blocks():
    from req_review.html_report import build_data
    from req_review.ui.preview import build_ctx

    # backend 2.2 заполняет категории и карту покрытия всегда (RAG или нет) — эмулируем отчёт без этих полей
    ctx = build_ctx(fixture=None)
    ctx.rv.coverage = []
    for rr in ctx.rv.req_results:
        rr.category, rr.rewrite_pattern = "", None
        for f in rr.findings:
            f.basis = []
    for f in ctx.rv.set_findings:
        f.basis = []
    d = build_data(ctx)
    assert d["coverage"] is None
    assert all(f["basis"] == [] for f in d["findings"].values())
    assert all(r["category"] == "" and r["rewrite_pattern"] is None for r in d["reqs"])


def test_basis_without_quote_or_https_is_not_shown():
    from types import SimpleNamespace

    from req_review.html_report import _basis

    f = SimpleNamespace(basis=[{"kind": "law", "source": "Закон", "clause": "ст. 1", "quote": "", "url": "https://x"},
                               {"kind": "weird", "source": "Стандарт", "quote": "текст", "url": "http://insecure"}])
    out = _basis(f)
    assert len(out) == 1 and out[0]["kind"] == "standard" and out[0]["url"] == ""


def test_assistant_cites_kb_and_document_lines():
    a = Assistant(json.loads(FIX22.read_text(encoding="utf-8")))
    r = a.answer("На какую норму опирается замечание к R-006?")
    types = {s["type"] for s in r["sources"]}
    assert {"req", "line", "kb"} <= types and "29148" in r["answer"]
    law = a.answer("Какие требования нарушают закон о персональных данных?")
    assert "R-013" in law["refs"] and any(s["type"] == "kb" and s["url"].startswith("https://") for s in law["sources"])
    assert any("норму" in q for q in r["suggest"])


def test_demo_mode_replays_saved_run(tmp_path, monkeypatch):
    from req_review.cli import main as cli_main
    from req_review.web import app as webapp
    from req_review.web import demo

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setattr(demo, "TARGET_S", 0.2)
    monkeypatch.setattr(demo, "MIN_STEP", 0.01)
    out = tmp_path / "report.md"
    assert cli_main([str(FIX), str(out), "--env", str(tmp_path / "none.env"), "--quiet", "--no-xlsx", "--no-jira"]) == 0
    c = TestClient(app)
    try:
        assert c.get("/api/demo").json() == {"available": False}
        webapp.set_demo(tmp_path / "report.json")
        info = c.get("/api/demo").json()
        assert info["available"] and info["reqs"] == 17 and not info["has_after"]
        job = c.post("/api/demo/start").json()["job"]
        _wait(job)
        ev = _events(c, job)
        kinds = [e["kind"] for e in ev]
        assert kinds[-1] == "done" and "split" in kinds and kinds.count("batch_start") >= 4
        s = ev[-1]["summary"]
        assert s["demo"] and len(s["rows"]) == 17
        html = next(v for v in JOBS[job].artifacts.values() if v.endswith(".html"))
        assert c.get(f"/jobs/{job}/{html}").status_code == 200
        assert c.post(f"/api/jobs/{job}/ask", json={"q": "Что исправить первым?"}).status_code == 200
        assert c.post(f"/api/jobs/{job}/compare", data={"use_fixed": "true"}).status_code == 400  # без --demo-after
        webapp.set_demo(tmp_path / "report.json", after=tmp_path / "report.json")
        new = c.post(f"/api/jobs/{job}/compare", data={"use_fixed": "true"}).json()["job"]
        _wait(new)
        assert "compare" in _events(c, new)[-1]["summary"]
    finally:
        webapp.set_demo(None)
