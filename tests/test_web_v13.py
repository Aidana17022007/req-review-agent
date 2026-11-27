"""v13, «Оценить без установки» (mock, без сети): лимит в час с адреса, при исчерпании — только правила вместо отказа,
загруженный документ удаляется после прогона, лимит размера из окружения, правила демо видны в /api/v1/health."""
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from req_review.web import app as webapp  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "sample_requirements.md"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from req_review.web import limits

    for k in ("DEMO_UPLOADS_PER_IP_HOUR", "DEMO_LIMIT_FALLBACK", "DEMO_PURGE_MINUTES"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("STUDIO_DEMO_DELAY", "0")
    monkeypatch.setenv("REQLENS_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("RAG_EMBED", "off")
    limits.reset()
    yield TestClient(webapp.app)
    limits.reset()


def _wait(job_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        j = webapp.JOBS.get(job_id)
        if j and j.done:
            return j
        time.sleep(0.05)
    raise AssertionError(f"прогон {job_id} не завершился")


def _upload(c, pid, tag, **form):
    return c.post(f"/api/v1/projects/{pid}/runs", files={"file": (f"{tag}.md", FIX.read_bytes() + f"\n<!-- {tag} -->\n".encode(),
                                                                 "text/markdown")}, data=form)


def test_hour_limit_per_ip_and_defaults(monkeypatch):
    from req_review.web import limits

    for k in ("DEMO_UPLOADS_PER_IP_HOUR", "PORT"):
        monkeypatch.delenv(k, raising=False)
    assert limits.hour_limit() == 0, "локально — без лимита"
    monkeypatch.setenv("PORT", "10000")
    assert limits.hour_limit() == 3, "публичный сервер (Render) — 3 в час по умолчанию"
    monkeypatch.delenv("PORT")
    monkeypatch.setenv("DEMO_UPLOADS_PER_IP_HOUR", "2")
    limits.reset()
    assert limits.check_and_count("1.1.1.1") is None and limits.check_and_count("1.1.1.1") is None
    hit = limits.check_and_count("1.1.1.1")
    assert hit["scope"] == "hour" and 0 < hit["retry_after"] <= 3600 and "в час" in limits.message(hit)
    assert limits.check_and_count("2.2.2.2") is None, "другой адрес — свой счётчик"
    limits.reset()


def test_limit_without_fallback_is_still_429(client, monkeypatch):
    monkeypatch.setenv("DEMO_UPLOADS_PER_IP_HOUR", "1")
    pid = client.post("/api/v1/projects", json={"name": "Лимит 429"}).json()["id"]
    r1 = _upload(client, pid, "a")
    assert r1.status_code == 200
    r2 = _upload(client, pid, "b")
    assert r2.status_code == 429 and r2.json()["error"]["scope"] == "hour"
    _wait(r1.json()["job"])


def test_limit_with_fallback_runs_rules_and_marks_response(client, monkeypatch):
    monkeypatch.setenv("DEMO_UPLOADS_PER_IP_HOUR", "1")
    monkeypatch.setenv("DEMO_LIMIT_FALLBACK", "rules")
    pid = client.post("/api/v1/projects", json={"name": "Лимит → правила"}).json()["id"]
    r1 = _upload(client, pid, "a").json()
    assert "limited" not in r1 and r1["run"]["mode"] == "llm"
    r2 = _upload(client, pid, "b")
    assert r2.status_code == 200, "вместо отказа — проверка правилами"
    d = r2.json()
    assert d["limited"]["fallback"] == "rules" and d["limited"]["scope"] == "hour" and d["run"]["mode"] == "rules"
    assert "только правилами" in d["limited"]["message"]
    _wait(r1["job"])
    _wait(d["job"])
    run = client.get(f"/api/v1/runs/{d['job']}").json()
    assert run["status"] == "done" and run["mode"] == "rules"
    h = client.get("/api/v1/health").json()
    assert h["limits"]["per_hour"] == 1 and h["limits"]["fallback"] == "rules"


def test_uploaded_document_is_purged_after_run(client, monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_PURGE_MINUTES", "0")
    pid = client.post("/api/v1/projects", json={"name": "Удаление"}).json()["id"]
    r = _upload(client, pid, "p").json()
    _wait(r["job"])
    d = tmp_path / "data" / "runs" / r["job"]
    deadline = time.time() + 5
    while list(d.glob("input.*")) and time.time() < deadline:
        time.sleep(0.05)
    assert not list(d.glob("input.*")), "загруженный документ удалён"
    assert (d / "report.json").exists(), "отчёт остаётся в истории"
    assert client.get("/api/v1/health").json()["purge_minutes"] == 0
    # перепроверка с ответами без исходного файла — понятная ошибка, а не 500
    e = client.post(f"/api/v1/runs/{r['job']}/answers", json={"text": "### Q-01\nНе дольше 2 секунд."})
    assert e.status_code == 410 and e.json()["error"]["code"] == "purged"


def test_max_upload_from_env():
    """STUDIO_MAX_MB (на Render — 5) — в отдельном процессе, чтобы не перезагружать модуль приложения в общих тестах."""
    import os
    import subprocess
    import sys

    out = subprocess.run([sys.executable, "-c", "from req_review.web import app; print(app.MAX_BYTES)"], capture_output=True,
                         text=True, env={**os.environ, "STUDIO_MAX_MB": "5"}, cwd=Path(__file__).parent.parent, timeout=120)
    assert out.stdout.strip() == str(5 * 1024 * 1024), out.stderr[-500:]
    assert webapp.MAX_BYTES == 10 * 1024 * 1024, "по умолчанию — 10 МБ, как раньше"


def test_studio_shows_demo_policy_and_limited_banner():
    html = (Path(__file__).parent.parent / "req_review" / "ui" / "templates" / "studio.html.j2").read_text(encoding="utf-8")
    for marker in ('id="up-policy"', "h.purge_minutes", "L.fallback===\"rules\"", "state.limited", "собран только правилами", "purged"):
        assert marker in html, marker
