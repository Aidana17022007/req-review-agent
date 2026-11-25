"""ReqLens Studio — веб-интерфейс поверх того же пайплайна, что и CLI.

Ключ модели берётся только из .env сервера: браузер его не видит и не передаёт.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from ..pipeline import PROFILES, ROOT, STEPS, Options, run
from ..reader import SUPPORTED

MAX_BYTES = 20 * 1024 * 1024
JOBS_DIR = Path(tempfile.gettempdir()) / "reqlens-studio"


@dataclass
class Job:
    id: str
    name: str
    events: list = field(default_factory=list)
    done: bool = False
    error: str = ""
    artifacts: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)

    def push(self, kind: str, **data):
        self.events.append({"kind": kind, "t": time.time(), **data})


JOBS: dict[str, Job] = {}


@asynccontextmanager
async def lifespan(_app):
    yield
    shutil.rmtree(JOBS_DIR, ignore_errors=True)  # загруженные документы не остаются на диске


app = FastAPI(title="ReqLens Studio", docs_url=None, redoc_url=None, lifespan=lifespan)


def _page() -> str:
    from ..ui import env

    return env().get_template("studio.html.j2").render(steps=STEPS, profiles=list(PROFILES),
                                                     formats=", ".join(sorted(SUPPORTED)))


@app.get("/", response_class=HTMLResponse)
def index():
    return _page()


@app.post("/api/review")
async def start(file: UploadFile = File(...), profile: str = Form("fast"), domain: str = Form("fintech")):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED:
        raise HTTPException(400, f"Формат {ext or '?'} не поддерживается. Допустимо: {', '.join(sorted(SUPPORTED))}")
    if profile not in PROFILES:
        raise HTTPException(400, "Неизвестный профиль")
    if domain not in ("fintech", "none"):
        raise HTTPException(400, "Неизвестный домен")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Файл больше 20 МБ")
    job = Job(uuid.uuid4().hex[:12], Path(file.filename).name)
    d = JOBS_DIR / job.id
    d.mkdir(parents=True, exist_ok=True)
    src = d / ("input" + ext)
    src.write_bytes(data)
    JOBS[job.id] = job

    def work():
        try:
            ctx = run(str(src), str(d / "report.md"), Options(profile=profile, domain=domain),
                      log=lambda m: job.push("log", msg=m), step=lambda i, label="": job.push("step", i=i))
            job.artifacts = {name: p.name for name, p in ctx.artifacts.items()}
            sc = ctx.scores
            job.summary = {"score": sc.doc_score, "readiness": sc.readiness, "reqs": len(ctx.rv.req_results),
                           "calls": ctx.llm_stats.calls}
            job.push("done", artifacts=job.artifacts, summary=job.summary)
        except Exception as e:  # ошибка показывается пользователю, ключ в сообщения не попадает
            job.error = str(e)[:500]
            job.push("error", msg=job.error)
        finally:
            job.done = True

    threading.Thread(target=work, daemon=True).start()
    return {"job": job.id}


@app.get("/api/jobs/{job_id}/events")
async def events(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404)

    async def gen():
        i = 0
        while True:
            while i < len(job.events):
                yield f"data: {json.dumps(job.events[i], ensure_ascii=False)}\n\n"
                i += 1
            if job.done and i >= len(job.events):
                break
            await asyncio.sleep(0.25)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/jobs/{job_id}/{name}")
def artifact(job_id: str, name: str):
    job = JOBS.get(job_id)
    if not job or name not in job.artifacts.values():
        raise HTTPException(404)
    return FileResponse(JOBS_DIR / job_id / name, filename=name if not name.endswith(".html") else None)


def main():
    import os

    import uvicorn
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    host = os.getenv("STUDIO_HOST", "127.0.0.1")
    port = int(os.getenv("STUDIO_PORT", "8000"))
    print(f"ReqLens Studio: http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
