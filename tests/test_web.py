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
