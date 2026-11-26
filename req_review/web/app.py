"""ReqLens Studio — веб-интерфейс поверх того же пайплайна, что и CLI.

Ключ модели берётся только из .env сервера: браузер его не видит и не передаёт.
Живой прогон: события шагов, пакетов требований и логов идут в браузер через SSE.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse

from ..pipeline import PROFILES, ROOT, STEPS, Options, run
from ..reader import SUPPORTED
from .live import ObservedLLM, classify_error, demo_delay, provider_status

MAX_BYTES = 20 * 1024 * 1024
JOBS_DIR = Path(tempfile.gettempdir()) / "reqlens-studio"
SAMPLE = ROOT / "tests" / "fixtures" / "sample_requirements.md"
ORDER = {"critical": 0, "major": 1, "minor": 2}


@dataclass
class Job:
    id: str
    name: str
    kind: str = "review"  # review | compare
    parent: str = ""
    profile: str = "fast"
    domain: str = "fintech"
    events: list = field(default_factory=list)
    done: bool = False
    error: str = ""
    artifacts: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)

    def push(self, kind: str, **data):
        self.events.append({"kind": kind, "t": time.time(), **data})

    @property
    def dir(self) -> Path:
        return JOBS_DIR / self.id

    @property
    def json_path(self) -> Path:
        return self.dir / "report.json"


JOBS: dict[str, Job] = {}
DEMO = None  # DemoRun — режим «Демо» (python -m req_review.web --demo reports/report.json)


def set_demo(json_path: str | Path | None, after: str | Path | None = None):
    """Включить режим «Демо»: проигрывание сохранённого прогона без сети и без модели."""
    global DEMO
    from .demo import DemoRun

    if not json_path:
        DEMO = None
        return None
    p = Path(json_path)
    if not p.exists():
        raise FileNotFoundError(f"Нет файла отчёта для режима «Демо»: {p}")
    a = Path(after) if after else None
    if a and not a.exists():
        raise FileNotFoundError(f"Нет файла отчёта исправленной версии: {a}")
    DEMO = DemoRun(p, a)
    return DEMO


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


@app.get("/api/health")
def health():
    """Состояние модели для экрана загрузки: провайдер и признак «ключ задан» (без самого ключа)."""
    return provider_status()


@app.get("/api/demo")
def demo_info():
    """Есть ли сохранённый прогон для режима «Демо» (кнопка на стартовом экране)."""
    return DEMO.describe() if DEMO else {"available": False}


@app.post("/api/demo/start")
def demo_start():
    if not DEMO:
        raise HTTPException(404, "Режим «Демо» не включён: запустите python -m req_review.web --demo reports/report.json")
    from .demo import replay

    d = DEMO.describe()
    job = Job(uuid.uuid4().hex[:12], d["document"] or "Сохранённый прогон")
    JOBS[job.id] = job
    replay(job, DEMO)
    return {"job": job.id, "demo": d}


@app.get("/api/sample", response_class=PlainTextResponse)
def sample():
    """Демо-документ (вымышленный, из тестов) — чтобы показать живой прогон без своего файла."""
    if not SAMPLE.exists():
        raise HTTPException(404)
    return PlainTextResponse(SAMPLE.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")


def _req_rows(ctx) -> list[dict]:
    rows = []
    for rr in ctx.rv.req_results:
        worst = min((f.severity for f in rr.findings), key=ORDER.get, default="ok")
        rows.append({"rid": rr.req.rid, "doc_id": rr.req.doc_id, "text": rr.req.short[:200], "score": ctx.scores.req[rr.req.rid],
                     "worst": worst, "n": len(rr.findings), "test": rr.test_possible})
    return rows


def _start(job: Job, src: Path, compare_with: Path | None = None) -> None:
    JOBS[job.id] = job

    def work():
        observer: dict = {}

        def wrap(llm):
            observer["o"] = ObservedLLM(llm, job.push, demo_delay(getattr(llm, "provider", "")))
            return observer["o"]

        def step(i, label=""):
            if "o" in observer:
                observer["o"].phase = i
            job.push("step", i=i)

        def log(m):
            job.push("log", msg=m)
            mm = re.search(r"выделено требований: (\d+)", m)
            if mm:
                job.push("split", total=int(mm.group(1)))

        try:
            batch = 4 if provider_status()["mock"] else int(os.getenv("LLM_BATCH_SIZE", "20"))
            ctx = run(str(src), str(job.dir / "report.md"),
                      Options(profile=job.profile, domain=job.domain, batch_size=batch,
                              compare=str(compare_with) if compare_with else None),
                      log=log, step=step, llm_wrap=wrap)
            job.artifacts = {name: p.name for name, p in ctx.artifacts.items()}
            sc = ctx.scores
            crit = sum(1 for rr in ctx.rv.req_results for f in rr.findings if f.severity == "critical") + \
                sum(1 for f in ctx.rv.set_findings if f.severity == "critical")
            job.summary = {"score": sc.doc_score, "readiness": sc.readiness, "reqs": len(ctx.rv.req_results),
                           "calls": ctx.llm_stats.calls, "critical": crit, "tests_ok": sc.tests_ok, "tests_total": sc.tests_total,
                           "rows": _req_rows(ctx), "has_fixed": bool(ctx.changes), "document": ctx.rv.doc.title}
            if compare_with and job.json_path.exists():
                from .compare import diff_reports

                job.summary["compare"] = diff_reports(json.loads(compare_with.read_text(encoding="utf-8")),
                                                      json.loads(job.json_path.read_text(encoding="utf-8")))
            job.push("done", artifacts=job.artifacts, summary=job.summary)
        except Exception as e:  # ошибка показывается пользователю, ключ в сообщения не попадает
            job.error = str(e)[:500]
            job.push("error", msg=job.error, code=classify_error(job.error))
        finally:
            job.done = True

    threading.Thread(target=work, daemon=True).start()


async def _save_upload(file: UploadFile, d: Path) -> Path:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED:
        raise HTTPException(400, f"Формат {ext or '?'} не поддерживается. Допустимо: {', '.join(sorted(SUPPORTED))}")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Файл больше 20 МБ")
    if not data.strip():
        raise HTTPException(400, "Файл пустой")
    d.mkdir(parents=True, exist_ok=True)
    src = d / ("input" + ext)
    src.write_bytes(data)
    return src


@app.post("/api/review")
async def start(file: UploadFile = File(...), profile: str = Form("fast"), domain: str = Form("fintech")):
    if profile not in PROFILES:
        raise HTTPException(400, "Неизвестный профиль")
    if domain not in ("fintech", "none"):
        raise HTTPException(400, "Неизвестный домен")
    job = Job(uuid.uuid4().hex[:12], Path(file.filename or "документ").name, profile=profile, domain=domain)
    src = await _save_upload(file, job.dir)
    _start(job, src)
    return {"job": job.id}


@app.post("/api/jobs/{job_id}/compare")
async def compare_version(job_id: str, file: UploadFile | None = File(None), use_fixed: bool = Form(False)):
    """Проверить новую версию документа и сравнить с отчётом задачи job_id (экран «До / После»)."""
    parent = JOBS.get(job_id)
    if not parent or not parent.done or parent.error or not parent.json_path.exists():
        raise HTTPException(404, "Исходный отчёт не найден")
    job = Job(uuid.uuid4().hex[:12], "", kind="compare", parent=job_id, profile=parent.profile, domain=parent.domain)
    if parent.summary.get("demo"):
        # в «Демо» сравнение тоже офлайн: проигрываем сохранённый отчёт исправленной версии (--demo-after)
        if not (DEMO and DEMO.after):
            raise HTTPException(400, "В режиме «Демо» «До / После» доступно, если Studio запущена с --demo-after <report.json исправленной версии>")
        from .demo import replay

        job.name = "Исправленная версия (сохранённый прогон)"
        JOBS[job.id] = job
        replay(job, DEMO, source=DEMO.after, compare_with=parent.json_path)
        return {"job": job.id}
    if use_fixed:
        fixed = next((parent.dir / v for v in parent.artifacts.values() if v.endswith("_requirements_fixed.md")), None)
        if not fixed or not fixed.exists():
            raise HTTPException(400, "Исправленного документа нет — загрузите файл новой версии")
        job.dir.mkdir(parents=True, exist_ok=True)
        src = job.dir / "input.md"
        shutil.copyfile(fixed, src)
        job.name = f"{Path(parent.name).stem} (исправленный).md"
    elif file is not None and file.filename:
        src = await _save_upload(file, job.dir)
        job.name = Path(file.filename).name
    else:
        raise HTTPException(400, "Загрузите файл новой версии документа")
    _start(job, src, compare_with=parent.json_path)
    return {"job": job.id}


@app.post("/api/jobs/{job_id}/ask")
def ask(job_id: str, payload: dict = Body(...)):
    """AI-ассистент по отчёту задачи: типовые вопросы — по данным отчёта, остальные — моделью (если доступна)."""
    job = JOBS.get(job_id)
    if not job or not job.json_path.exists():
        raise HTTPException(404, "Отчёт не найден")
    q = str(payload.get("q", ""))[:500]
    from ..llm import build_llm_from_env
    from .assistant import Assistant

    a = Assistant(json.loads(job.json_path.read_text(encoding="utf-8")))
    return a.answer(q, llm_factory=build_llm_from_env)


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
            await asyncio.sleep(0.2)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/jobs/{job_id}/{name}")
def artifact(job_id: str, name: str):
    job = JOBS.get(job_id)
    if not job or name not in job.artifacts.values():
        raise HTTPException(404)
    return FileResponse(job.dir / name, filename=name if not name.endswith(".html") else None)


def main(argv: list[str] | None = None):
    import argparse

    import uvicorn
    from dotenv import load_dotenv

    ap = argparse.ArgumentParser(prog="python -m req_review.web", description="ReqLens Studio")
    ap.add_argument("--demo", metavar="REPORT_JSON", help="режим «Демо»: проиграть сохранённый прогон без сети и модели")
    ap.add_argument("--demo-after", metavar="REPORT_JSON", help="отчёт исправленной версии для «До / После» в режиме «Демо»")
    args = ap.parse_args(argv)
    load_dotenv(ROOT / ".env")
    if args.demo:
        d = set_demo(args.demo, args.demo_after).describe()
        print(f"Режим «Демо»: {d['document']} · {d['model']} · {d['started']} — модель не вызывается")
    host = os.getenv("STUDIO_HOST", "127.0.0.1")
    port = int(os.getenv("STUDIO_PORT", "8000"))
    print(f"ReqLens Studio: http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
