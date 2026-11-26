"""ReqLens App (API v1): проекты, история, повтор того же файла, версии и сравнение, очередь, отмена, ограничения
загрузки, безопасная раздача файлов, ассистент с источниками, PWA. Модель — mock, сеть не нужна."""
import io
import json
import threading
import time
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from req_review.web import app as webapp  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "sample_requirements.md"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("STUDIO_DEMO_DELAY", "0")
    monkeypatch.setenv("REQLENS_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("RAG_EMBED", "off")
    return TestClient(webapp.app)


def _wait(job_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        j = webapp.JOBS.get(job_id)
        if j and j.done:
            return j
        time.sleep(0.05)
    raise AssertionError(f"прогон {job_id} не завершился")


def _upload(c, pid, data=None, name="req.md", **form):
    return c.post(f"/api/v1/projects/{pid}/runs", files={"file": (name, data if data is not None else FIX.read_bytes(), "text/markdown")},
                  data=form)


def test_project_history_duplicate_versions_and_delete(client, tmp_path):
    c = client
    assert c.post("/api/v1/projects", json={"name": "  "}).json()["error"]["code"] == "bad_request"
    p = c.post("/api/v1/projects", json={"name": "Переводы P2P"})
    assert p.status_code == 201
    pid = p.json()["id"]

    r1 = _upload(c, pid).json()
    assert r1["duplicate"] is False and r1["compare_with"] is None
    _wait(r1["job"])
    run1 = c.get(f"/api/v1/runs/{r1['job']}").json()
    assert run1["status"] == "done" and run1["version"] == 1 and run1["verdict"] in ("нельзя", "условно", "можно")
    assert run1["score"] is not None and run1["critical"] >= 0 and any(u.endswith(".html") for u in run1["files"].values())
    assert (tmp_path / "data" / "runs" / r1["job"] / "report.json").exists()  # история — на диске, не во временной папке

    # тот же файл ещё раз: прошлый результат, без нового прогона
    jobs_before = len(webapp.JOBS)
    dup = _upload(c, pid).json()
    assert dup["duplicate"] is True and dup["run"]["id"] == r1["job"] and len(webapp.JOBS) == jobs_before

    # исправленная версия документа → новая версия и автоматическое сравнение с прошлой
    fixed = next(v for v in run1["artifacts"].values() if v.endswith("_requirements_fixed.md"))
    v2_bytes = c.get(f"/api/v1/runs/{r1['job']}/files/{fixed}").content
    r2 = _upload(c, pid, v2_bytes, name="req_v2.md").json()
    assert r2["compare_with"] == r1["job"]
    _wait(r2["job"])
    run2 = c.get(f"/api/v1/runs/{r2['job']}").json()
    assert run2["version"] == 2 and run2["compare"]["before"]["score"] <= run2["compare"]["after"]["score"]
    assert {"fixed", "new", "rows"} <= set(run2["compare"])

    hist = c.get(f"/api/v1/projects/{pid}/runs").json()
    assert [t["version"] for t in hist["trend"]] == [1, 2] and all("critical" in t for t in hist["trend"])
    assert c.get("/api/v1/projects").json()["projects"][0]["last_run"]["id"] == r2["job"]

    assert c.delete(f"/api/v1/runs/{r1['job']}").json() == {"deleted": r1["job"]}
    assert c.get(f"/api/v1/runs/{r1['job']}").json()["error"]["code"] == "not_found"
    assert not (tmp_path / "data" / "runs" / r1["job"]).exists()
    assert c.delete(f"/api/v1/projects/{pid}").status_code == 200


def test_force_rerun_and_rules_only_mode(client):
    c = client
    pid = c.post("/api/v1/projects", json={"name": "Правила"}).json()["id"]
    r = _upload(c, pid, mode="rules").json()
    _wait(r["job"])
    run = c.get(f"/api/v1/runs/{r['job']}").json()
    assert run["status"] == "done" and run["mode"] == "rules" and "правил" in run["model"]
    report = json.loads(c.get(f"/api/v1/runs/{r['job']}/files/report.json").text)
    assert report["passport"]["calls"] == 0 and "только правила" in report["passport"]["mode"]
    fs = [f for q in report["requirements"] for f in q["findings"]]
    assert fs and not any("[mock]" in f["problem"] for f in fs)
    again = _upload(c, pid, force="true").json()
    assert again["duplicate"] is False and again["compare_with"] == r["job"]
    _wait(again["job"])
    assert _upload(c, pid, mode="magic").json()["error"]["code"] == "bad_request"


def test_upload_limits_and_content_check(client, monkeypatch):
    c = client
    pid = c.post("/api/v1/projects", json={"name": "Загрузка"}).json()["id"]
    big = _upload(c, pid, b"a" * (10 * 1024 * 1024 + 1))
    assert big.status_code == 413 and big.json()["error"]["code"] == "too_large"
    exe = c.post(f"/api/v1/projects/{pid}/runs", files={"file": ("virus.exe", b"MZ\x90\x00", "application/octet-stream")})
    assert exe.status_code == 400 and exe.json()["error"]["code"] == "unsupported"
    fake_pdf = _upload(c, pid, b"MZ\x90\x00 not a pdf", name="doc.pdf")
    assert fake_pdf.status_code == 415
    exe_as_md = _upload(c, pid, b"MZ\x90\x00\x03\x00\x00\x00", name="doc.md")
    assert exe_as_md.status_code == 415
    zip_as_docx = io.BytesIO()
    with zipfile.ZipFile(zip_as_docx, "w") as z:
        z.writestr("readme.txt", "не Word")
    assert _upload(c, pid, zip_as_docx.getvalue(), name="doc.docx").status_code == 415
    assert _upload(c, pid, b"   \n", name="doc.txt").json()["error"]["code"] == "empty"
    assert c.post("/api/v1/projects/nope/runs", files={"file": ("a.md", b"x", "text/markdown")}).status_code == 404
    # старый эндпоинт Studio: тот же лимит, прежний формат ошибки
    old = c.post("/api/review", files={"file": ("x.pdf", b"not a pdf", "application/pdf")})
    assert old.status_code == 415 and "detail" in old.json()


def test_files_whitelist_blocks_path_traversal(client):
    c = client
    pid = c.post("/api/v1/projects", json={"name": "Файлы"}).json()["id"]
    r = _upload(c, pid).json()
    _wait(r["job"])
    rid = r["job"]
    assert c.get(f"/api/v1/runs/{rid}/files/report.md").status_code == 200
    for bad in ("..%2F..%2Freqlens.sqlite3", "input.md", "%2e%2e%2f%2e%2e%2fetc%2fpasswd", "report.md%00.html"):
        assert c.get(f"/api/v1/runs/{rid}/files/{bad}").status_code == 404, bad
    assert c.get(f"/api/v1/runs/{rid}/files/../../reqlens.sqlite3").status_code == 404


def test_queue_limit_and_cancel(client, monkeypatch):
    c = client
    monkeypatch.setenv("MAX_JOBS", "1")
    gate = threading.Event()
    real_run = webapp.run

    def slow_run(*a, **k):  # первый прогон держит единственный слот, пока тест не отпустит
        gate.wait(10)
        return real_run(*a, **k)

    monkeypatch.setattr(webapp, "run", slow_run)
    pid = c.post("/api/v1/projects", json={"name": "Очередь"}).json()["id"]
    first = _upload(c, pid).json()["job"]
    second = _upload(c, pid, FIX.read_bytes() + b"\n<!-- v2 -->\n", name="v2.md").json()["job"]
    for _ in range(100):
        if any(e["kind"] == "queued" for e in webapp.JOBS[second].events):
            break
        time.sleep(0.05)
    assert webapp.JOBS[second].status == "queued"
    st = c.get(f"/api/v1/runs/{second}").json()
    assert st["status"] == "queued" and st["queue_position"] == 1
    assert c.post(f"/api/v1/jobs/{second}/cancel").json()["cancelling"] is True
    j2 = _wait(second)
    assert j2.status == "cancelled" and c.get(f"/api/v1/runs/{second}").json()["status"] == "cancelled"
    gate.set()
    j1 = _wait(first)
    assert j1.status == "done"
    assert c.post(f"/api/v1/jobs/{first}/cancel").json()["error"]["code"] == "finished"
    assert c.post("/api/v1/jobs/nope/cancel").status_code == 404
    events = [e for e in j1.events if e["kind"] == "step"]
    assert events and all("pct" in e and e["name"] for e in events)


def test_cancel_running_job_at_step_boundary(client, monkeypatch):
    c = client
    pid = c.post("/api/v1/projects", json={"name": "Отмена"}).json()["id"]
    real_run = webapp.run

    def run_and_cancel(path, out, opts, log, step, **k):
        def step2(i, label=""):
            if i == 2:
                webapp.JOBS[next(iter(j for j in webapp.JOBS if not webapp.JOBS[j].done and webapp.JOBS[j].base))].cancelled = True
            step(i, label)
        return real_run(path, out, opts, log=log, step=step2, **k)

    monkeypatch.setattr(webapp, "run", run_and_cancel)
    r = _upload(c, pid).json()
    j = _wait(r["job"])
    assert j.status == "cancelled" and j.events[-1]["kind"] == "cancelled"
    assert c.get(f"/api/v1/runs/{r['job']}").json()["status"] == "cancelled"


def test_quota_error_offers_rules_mode(client, monkeypatch):
    c = client

    def quota(*a, **k):
        raise RuntimeError("Квота модели gemini исчерпана (API просит подождать ≈5.0 ч)")

    monkeypatch.setattr(webapp, "run", quota)
    pid = c.post("/api/v1/projects", json={"name": "Квота"}).json()["id"]
    r = _upload(c, pid).json()
    j = _wait(r["job"])
    err = j.events[-1]
    assert err["kind"] == "error" and err["code"] == "quota" and err["fallback"] == "rules"
    assert c.get(f"/api/v1/runs/{r['job']}").json()["status"] == "error"


def test_ask_uses_report_then_sources(client):
    c = client
    pid = c.post("/api/v1/projects", json={"name": "Ассистент"}).json()["id"]
    r = _upload(c, pid).json()
    _wait(r["job"])
    rid = r["job"]
    known = c.post(f"/api/v1/runs/{rid}/ask", json={"q": "Что исправить первым?"}).json()
    assert known["mode"] == "по данным отчёта" and known["refs"]
    law = c.post(f"/api/v1/runs/{rid}/ask", json={"q": "Почему R-006 критичное?"}).json()
    for res in (known, law):  # единый формат источников для интерфейса, в обоих режимах
        assert all(s["kind"] in ("requirement", "document", "kb") and "type" not in s for s in res["sources"])
    free = c.post(f"/api/v1/runs/{rid}/ask", json={"q": "как хранить номер телефона получателя перевода"}).json()
    kinds = {s["kind"] for s in free["sources"]}
    assert free["source"] == "источники" and kinds & {"document", "kb", "requirement"}
    assert all(s["quote"] for s in free["sources"])
    assert all("paraphrase" in s for s in free["sources"] if s["kind"] == "kb")
    stream = c.post(f"/api/v1/runs/{rid}/ask", json={"q": "как хранить номер телефона", "stream": True})
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "event: sources" in stream.text and "event: done" in stream.text
    assert c.post(f"/api/v1/runs/{rid}/ask", json={"q": ""}).json()["error"]["code"] == "bad_request"


def test_health_docs_and_pwa(client):
    c = client
    h = c.get("/api/v1/health").json()
    assert h["provider"] == "mock" and h["max_upload_mb"] == 10 and not any("secret" in k or k == "key" for k in h)
    assert c.get("/docs").status_code == 200 and "/api/v1/projects" in c.get("/openapi.json").text
    html = c.get("/").text
    assert 'rel="manifest"' in html and "serviceWorker" in html
    m = c.get("/manifest.webmanifest")
    assert m.headers["content-type"].startswith("application/manifest+json")
    sizes = {i["sizes"] for i in m.json()["icons"]}
    assert {"192x192", "512x512"} <= sizes and m.json()["display"] == "standalone"
    for i in m.json()["icons"]:
        assert c.get(i["src"]).status_code == 200
    sw = c.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"] and "offline" in sw.text
    assert c.get("/offline").status_code == 200
    assert c.get("/static/..%2Fapp.py").status_code == 404 and c.get("/static/nope.js").status_code == 404
    assert c.get("/api/v1/runs/nope").json() == {"error": {"code": "not_found", "message": "Прогон не найден"}}
    assert c.post("/api/v1/projects", content=b"not json", headers={"content-type": "application/json"}).json()["error"]["code"] == "invalid"
