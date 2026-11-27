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
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..pipeline import PROFILES, ROOT, STEPS, Options, run
from ..reader import SUPPORTED
from .live import ObservedLLM, classify_error, demo_delay, provider_status

MAX_BYTES = 10 * 1024 * 1024  # лимит загрузки: 10 МБ
STATIC = Path(__file__).parent / "static"
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
    mode: str = "llm"  # llm — модель из .env; rules — только детерминированные правила, без модели
    base: Path | None = None  # папка прогона ReqLens App (история в data/); None — временная папка Studio
    cancelled: bool = False
    status: str = "queued"  # queued | running | done | error | cancelled
    on_finish: Callable | None = field(default=None, repr=False)
    answers: Path | None = None  # v9: файл ответов аналитика — перепроверка (--answers)

    def push(self, kind: str, **data):
        self.events.append({"kind": kind, "t": time.time(), **data})

    @property
    def dir(self) -> Path:
        return (self.base or JOBS_DIR) / self.id

    @property
    def json_path(self) -> Path:
        return self.dir / "report.json"


JOBS: dict[str, Job] = {}


class JobCancelled(Exception):
    pass


_SLOTS: threading.BoundedSemaphore | None = None
_SLOTS_N = 0
_SLOTS_LOCK = threading.Lock()


def _slots() -> threading.BoundedSemaphore:
    """Очередь прогонов: одновременно не больше MAX_JOBS (по умолчанию 2), остальные ждут «в очереди»."""
    global _SLOTS, _SLOTS_N
    n = max(1, int(os.getenv("MAX_JOBS", "2") or 2))
    with _SLOTS_LOCK:
        if _SLOTS is None or n != _SLOTS_N:
            _SLOTS, _SLOTS_N = threading.BoundedSemaphore(n), n
        return _SLOTS


def queue_position(job: Job) -> int:
    waiting = [j for j in JOBS.values() if j.status == "queued" and not j.done]
    return next((i for i, j in enumerate(waiting, 1) if j.id == job.id), 0)
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


app = FastAPI(title="ReqLens App", version="1.0", lifespan=lifespan, docs_url="/docs", redoc_url=None,
              description="ИИ-ревью требований по ISO/IEC/IEEE 29148 и IEEE 830: проекты, история проверок, "
                          "сравнение версий документа, ассистент с источниками. Контракт — docs/API.md.")


def _v1(request: Request) -> bool:
    return request.url.path.startswith("/api/v1/")


ERROR_CODES = {400: "bad_request", 404: "not_found", 409: "conflict", 413: "too_large", 415: "unsupported", 422: "invalid"}


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    """API v1 — единый формат ошибок {"error": {"code", "message"}}; старые /api/… — как раньше ({"detail"})."""
    if not _v1(request):
        if isinstance(exc.detail, dict) and "message" in exc.detail:  # старый формат: detail — строка
            exc = StarletteHTTPException(exc.status_code, exc.detail["message"])
        return await http_exception_handler(request, exc)
    detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail or "Ошибка")}
    body = {"code": detail.get("code") or ERROR_CODES.get(exc.status_code, "error"), "message": detail.get("message", "")}
    body.update({k: v for k, v in detail.items() if k not in body})
    return JSONResponse({"error": body}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    if not _v1(request):
        return await request_validation_exception_handler(request, exc)
    fields = [".".join(str(x) for x in e.get("loc", [])[1:]) for e in exc.errors()]
    return JSONResponse({"error": {"code": "invalid", "message": "Неверные параметры запроса: " + ", ".join(fields)}},
                        status_code=422)


def _page() -> str:
    from ..ui import env

    html = env().get_template("studio.html.j2").render(steps=STEPS, profiles=list(PROFILES),
                                                     formats=", ".join(sorted(SUPPORTED)))
    # PWA: манифест и service worker подключаются здесь, чтобы не трогать шаблон дизайна (зона человека 2);
    # когда теги появятся в studio.html.j2, вставка не повторится
    if 'rel="manifest"' not in html:
        html = html.replace("</head>", PWA_HEAD + "</head>", 1)
    return html


PWA_HEAD = ('<link rel="manifest" href="/manifest.webmanifest"><meta name="theme-color" content="#1F6B45">'
            '<link rel="icon" href="/static/icon.svg" type="image/svg+xml">'
            '<script>if("serviceWorker"in navigator)addEventListener("load",()=>navigator.serviceWorker.register("/sw.js")'
            '.catch(()=>{}));</script>')


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # service worker отдаётся из корня, чтобы его область действия охватывала всё приложение
    return FileResponse(STATIC / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/static/{name}", include_in_schema=False)
def static(name: str):
    allowed = {p.name for p in STATIC.iterdir() if p.is_file()} if STATIC.exists() else set()
    if name not in allowed:
        raise HTTPException(404)
    return FileResponse(STATIC / name)


@app.get("/offline", response_class=HTMLResponse, include_in_schema=False)
def offline_page():
    return (STATIC / "offline.html").read_text(encoding="utf-8")


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
            if job.cancelled:
                raise JobCancelled()
            if "o" in observer:
                observer["o"].phase = i
            job.push("step", i=i, name=STEPS[i] if 0 <= i < len(STEPS) else label,
                     pct=round(100 * i / len(STEPS)))

        def log(m):
            if job.cancelled:
                raise JobCancelled()
            job.push("log", msg=m)
            mm = re.search(r"выделено требований: (\d+)", m)
            if mm:
                job.push("split", total=int(mm.group(1)))

        slots = _slots()
        acquired = False
        try:
            if not slots.acquire(blocking=False):
                job.push("queued", position=queue_position(job))
                while not slots.acquire(timeout=0.2):
                    if job.cancelled:
                        raise JobCancelled()
            acquired = True
            if job.cancelled:
                raise JobCancelled()
            job.status = "running"
            job.push("started")
            make_llm = None
            if job.mode == "rules":
                from ..rules_llm import RulesOnlyLLM

                make_llm = RulesOnlyLLM
            batch = 4 if provider_status()["mock"] or job.mode == "rules" else int(os.getenv("LLM_BATCH_SIZE", "20"))
            ctx = run(str(src), str(job.dir / "report.md"),
                      Options(profile=job.profile, domain=job.domain, batch_size=batch,
                              compare=str(compare_with) if compare_with else None,
                              answers=str(job.answers) if job.answers else ""),
                      log=log, step=step, llm_wrap=wrap, make_llm=make_llm)
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
            job.status = "done"
            if job.on_finish:
                _finish(job)
            job.push("done", artifacts=job.artifacts, summary=job.summary, pct=100)
        except JobCancelled:
            job.status, job.error = "cancelled", "Прогон отменён"
            _finish(job)
            job.push("cancelled", msg=job.error)
        except Exception as e:  # ошибка показывается пользователю, ключ в сообщения не попадает
            from ..errors import DocumentError

            job.status, job.error = "error", str(e)[:500]
            _finish(job)
            if isinstance(e, DocumentError):  # v9: «сломанный» файл — сообщение и что сделать (OCR, сохранить как PDF…)
                job.push("error", msg=e.message, code=e.kind, hint=e.hint[:1].upper() + e.hint[1:])
                return
            code = classify_error(job.error)
            extra = {"fallback": "rules", "hint": "Квота модели исчерпана — можно запустить проверку без модели "
                     "(только правила): размытые формулировки, плейсхолдеры, числа, правила API."} if code == "quota" else {}
            job.push("error", msg=job.error, code=code, **extra)
        finally:
            if acquired:
                slots.release()
            job.done = True

    threading.Thread(target=work, daemon=True).start()


def _finish(job: Job) -> None:
    """Сохранить итог прогона в историю (ReqLens App) до события done/error — клиент сразу видит запись."""
    if not job.on_finish:
        return
    try:
        job.on_finish(job)
    except Exception as e:  # история не должна ронять прогон
        job.push("log", msg=f"история: не удалось сохранить результат ({e})")


def sniff(ext: str, data: bytes) -> str | None:
    """Проверка содержимого, а не только расширения: None — файл похож на заявленный формат, иначе причина отказа."""
    if ext == ".pdf":
        return None if data[:5] == b"%PDF-" else "Файл с расширением .pdf не является PDF"
    if ext == ".docx":
        import io
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                ok = "word/document.xml" in z.namelist()
        except zipfile.BadZipFile:
            ok = False
        return None if ok else "Файл с расширением .docx не является документом Word"
    # .md / .markdown / .txt — текст: без нулевых байтов, не исполняемый файл, архив или PDF под другим именем
    if data.startswith((b"MZ", b"PK\x03\x04", b"%PDF", b"\x7fELF")) or b"\x00" in data[:65536]:
        return "Файл не похож на текстовый документ"
    chunk = data[:65536]
    try:
        chunk.decode("utf-8")
        return None
    except UnicodeDecodeError as e:
        if e.start >= len(chunk) - 3:  # обрезали посреди символа UTF-8
            return None
    try:
        chunk.decode("cp1251")
        return None
    except UnicodeDecodeError:
        return "Не удалось прочитать текст: кодировка не UTF-8 и не Windows-1251"


async def read_upload(file: UploadFile) -> tuple[str, bytes]:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED:
        raise HTTPException(400, {"code": "unsupported", "message": f"Формат {ext or '?'} не поддерживается. "
                                  f"Допустимо: {', '.join(sorted(SUPPORTED))}"})
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, {"code": "too_large", "message": f"Файл больше {MAX_BYTES // (1024 * 1024)} МБ"})
    if not data.strip():
        raise HTTPException(400, {"code": "empty", "message": "Файл пустой"})
    if why := sniff(ext, data):
        raise HTTPException(415, {"code": "unsupported", "message": why})
    return ext, data


async def _save_upload(file: UploadFile, d: Path) -> Path:
    ext, data = await read_upload(file)
    d.mkdir(parents=True, exist_ok=True)
    src = d / ("input" + ext)
    src.write_bytes(data)
    return src


def _legacy_limit(request: Request) -> None:
    """v9: лимит демо-сервера и для старых эндпоинтов Studio (формат ошибки — {"detail"})."""
    from .limits import check_and_count, client_ip, message

    hit = check_and_count(client_ip(request))
    if hit:
        raise HTTPException(429, message(hit), headers={"Retry-After": str(hit["retry_after"])})


@app.post("/api/review")
async def start(request: Request, file: UploadFile = File(...), profile: str = Form("fast"), domain: str = Form("fintech")):
    if profile not in PROFILES:
        raise HTTPException(400, "Неизвестный профиль")
    if domain not in ("fintech", "none"):
        raise HTTPException(400, "Неизвестный домен")
    _legacy_limit(request)
    job = Job(uuid.uuid4().hex[:12], Path(file.filename or "документ").name, profile=profile, domain=domain)
    src = await _save_upload(file, job.dir)
    _start(job, src)
    return {"job": job.id}


@app.post("/api/jobs/{job_id}/compare")
async def compare_version(job_id: str, request: Request, file: UploadFile | None = File(None), use_fixed: bool = Form(False)):
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
    _legacy_limit(request)
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
        # Пока модель думает над одним этапом (30–60 с), новых событий нет. Прокси хостинга (Render) закрывает
        # «молчащее» соединение, и страница показывала «поток недоступен», хотя прогон шёл. Комментарий SSE
        # «: ping» раз в SSE_HEARTBEAT секунд держит соединение; EventSource его игнорирует.
        i, last = 0, time.monotonic()
        beat = float(os.getenv("SSE_HEARTBEAT", "15"))
        yield ": open\n\n"
        while True:
            while i < len(job.events):
                yield f"data: {json.dumps(job.events[i], ensure_ascii=False)}\n\n"
                i += 1
                last = time.monotonic()
            if job.done and i >= len(job.events):
                break
            if time.monotonic() - last >= beat:
                yield ": ping\n\n"
                last = time.monotonic()
            await asyncio.sleep(0.2)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str):
    """Отменить прогон: в очереди — сразу, в работе — на ближайшей границе шага (запрос к модели не прерывается)."""
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, {"code": "not_found", "message": "Прогон не найден"})
    if job.done:
        raise HTTPException(409, {"code": "finished", "message": "Прогон уже завершён"})
    job.cancelled = True
    return {"job": job.id, "cancelling": True}


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
    # хостинг (Render, Railway, Fly) задаёт PORT и ждёт сервер на 0.0.0.0; локально — 127.0.0.1:8000
    host = os.getenv("STUDIO_HOST") or ("0.0.0.0" if os.getenv("PORT") else "127.0.0.1")
    port = int(os.getenv("STUDIO_PORT") or os.getenv("PORT") or "8000")
    print(f"ReqLens Studio: http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


from .api_v1 import router as _v1_router  # noqa: E402 — API v1 использует Job и _start из этого модуля

app.include_router(_v1_router)
