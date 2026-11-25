"""ReqLens Studio: загрузка → события прогона → артефакты (mock, без сети)."""
import json
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from req_review.web.app import JOBS, app  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "sample_requirements.md"


def test_studio_flow(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    c = TestClient(app)
    assert "ReqLens" in c.get("/").text
    r = c.post("/api/review", files={"file": ("req.md", FIX.read_bytes(), "text/markdown")},
               data={"profile": "fast", "domain": "fintech"})
    assert r.status_code == 200
    job = r.json()["job"]
    for _ in range(100):
        if JOBS[job].done:
            break
        time.sleep(0.1)
    assert JOBS[job].done and not JOBS[job].error
    events = [json.loads(line[6:]) for line in c.get(f"/api/jobs/{job}/events").text.splitlines() if line.startswith("data: ")]
    assert events[-1]["kind"] == "done"
    html_name = next(v for v in JOBS[job].artifacts.values() if v.endswith(".html"))
    assert c.get(f"/jobs/{job}/{html_name}").status_code == 200
    assert c.get(f"/jobs/{job}/../../etc/passwd").status_code == 404


def test_studio_rejects_bad_format():
    r = TestClient(app).post("/api/review", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400
