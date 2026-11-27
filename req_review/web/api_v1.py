"""ReqLens App — API v1: проекты, история проверок, версии документа, очередь, ассистент с источниками.

Контракт описан в docs/API.md. Ошибки — {"error": {"code", "message"}} (обработчик в app.py).
Старые эндпоинты Studio (/api/review, /api/jobs/…) продолжают работать без изменений.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from fastapi import APIRouter, Body, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from ..pipeline import PROFILES, STEPS

router = APIRouter(prefix="/api/v1", tags=["ReqLens App v1"])

FILE_RE = re.compile(r"^[\w.-]{1,120}$")


def err(status: int, code: str, message: str, headers: dict | None = None, **extra) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message, **extra}, headers=headers)


def enforce_limit(request) -> dict | None:
    """v9: лимит загрузок демо-сервера (DEMO_UPLOADS_PER_IP / DEMO_UPLOADS_TOTAL, v13: DEMO_UPLOADS_PER_IP_HOUR) →
    429 со ссылкой на готовый пример. v13: при DEMO_LIMIT_FALLBACK=rules вместо отказа возвращает
    {"code": "limit", "message", "scope", "retry_after", "fallback": "rules"} — прогон идёт только правилами."""
    from .limits import check_and_count, client_ip, fallback, message

    hit = check_and_count(client_ip(request))
    if not hit:
        return None
    if fallback() == "rules":
        return {"code": "limit", "message": message(hit) + " Этот файл проверен только правилами — без модели и без квоты.",
                "scope": hit["scope"], "retry_after": hit["retry_after"], "fallback": "rules", "example": "/?example=1"}
    raise err(429, "limit", message(hit), headers={"Retry-After": str(hit["retry_after"])}, scope=hit["scope"],
              retry_after=hit["retry_after"], example="/?example=1")


def _app():
    from . import app as webapp  # отложенный импорт: app.py подключает этот роутер в конце модуля

    return webapp


def _store():
    from .store import get_store

    return get_store()


def _project_or_404(pid: str) -> dict:
    p = _store().project(pid)
    if not p:
        raise err(404, "not_found", "Проект не найден")
    return p


def _run_or_404(rid: str) -> dict:
    r = _store().run(rid)
    if not r:
        raise err(404, "not_found", "Прогон не найден")
    return r


def _verdict(counts: dict) -> str:
    if counts.get("critical"):
        return "нельзя"
    if counts.get("major"):
        return "условно"
    return "можно"


def _live(run: dict) -> dict:
    """Запись истории + живое состояние задачи (очередь, процент), если прогон ещё идёт."""
    webapp = _app()
    job = webapp.JOBS.get(run["id"])
    if job and not job.done:
        run["status"] = job.status
        steps = [e for e in job.events if e["kind"] == "step"]
        run["pct"] = steps[-1]["pct"] if steps else 0
        run["stage"] = steps[-1]["name"] if steps else ""
        if job.status == "queued":
            run["queue_position"] = webapp.queue_position(job)
    return run


# ----------------------------------------------------------------------------------- служебное

@router.get("/health", summary="Состояние модели (без ключа)")
def health():
    """Провайдер, модель и признак «ключ задан» — сам ключ никогда не возвращается."""
    from .limits import fallback, hour_limit, limits
    from .live import provider_status

    per_ip, total = limits()
    return {**provider_status(), "steps": STEPS, "profiles": list(PROFILES), "max_upload_mb": _app().MAX_BYTES // 2**20,
            "limits": {"per_hour": hour_limit(), "per_day": per_ip, "total": total, "fallback": fallback()},
            "purge_minutes": purge_minutes()}


@router.get("/sample", summary="Демо-документ")
def sample():
    return _app().sample()


# ----------------------------------------------------------------------------------- проекты

@router.get("/projects", summary="Список проектов с последним прогоном")
def projects():
    return {"projects": _store().projects()}


@router.post("/projects", status_code=201, summary="Создать проект")
def create_project(payload: dict = Body(..., examples=[{"name": "Уведомления о расходах"}])):
    name = str(payload.get("name", "")).strip()[:120]
    if not name:
        raise err(400, "bad_request", "Укажите название проекта")
    return _store().create_project(name)


@router.get("/projects/{pid}", summary="Проект")
def project(pid: str):
    return _project_or_404(pid)


@router.delete("/projects/{pid}", summary="Удалить проект вместе с историей")
def delete_project(pid: str):
    _project_or_404(pid)
    if any(r["status"] in ("queued", "running") for r in _store().runs(pid)):
        raise err(409, "busy", "В проекте идёт прогон — отмените его или дождитесь окончания")
    _store().delete_project(pid)
    return {"deleted": pid}


@router.get("/projects/{pid}/runs", summary="История версий документа и динамика")
def project_runs(pid: str):
    p = _project_or_404(pid)
    runs = [_live(r) for r in _store().runs(pid)]
    trend = [{"version": r["version"], "run": r["id"], "score": r["score"], "critical": r["critical"],
              "readiness": r["readiness"], "created": r["created"]} for r in runs if r["status"] == "done"]
    return {"project": p, "runs": runs, "trend": trend}


@router.post("/projects/{pid}/runs", summary="Проверить новую версию документа")
async def create_run(pid: str, request: Request, file: UploadFile | None = File(None), profile: str = Form("fast"),
                     domain: str = Form("fintech"), mode: str = Form("llm"), force: bool = Form(False),
                     file_b64: UploadFile | None = File(None), filename: str = Form("")):
    """Загрузить документ в проект. Тот же файл (SHA-256) уже проверен — вернётся прошлый результат
    (`duplicate: true`), квота модели не тратится; `force=true` — проверить заново.
    Если в проекте есть прошлый готовый прогон, новый автоматически сравнивается с ним."""
    webapp = _app()
    _project_or_404(pid)
    if profile not in PROFILES:
        raise err(400, "bad_request", "Неизвестный профиль", allowed=list(PROFILES))
    if domain not in ("fintech", "none"):
        raise err(400, "bad_request", "Неизвестный домен", allowed=["fintech", "none"])
    if mode not in ("llm", "rules"):
        raise err(400, "bad_request", "Режим: llm (модель) или rules (только правила)")
    file = await webapp.pick_upload(file, file_b64, filename)  # файл или его base64-копия (Studio, обход фильтра хостинга)
    ext, data = await webapp.read_upload(file)
    sha = hashlib.sha256(data).hexdigest()
    st = _store()
    if not force and (same := st.find_same(pid, sha)):
        return {"duplicate": True, "run": same,
                "message": "Этот файл уже проверялся — открыт прошлый результат. Чтобы проверить заново, передайте force=true."}
    limited = enforce_limit(request) if mode == "llm" else None  # «Только правила» модель не тратит и в лимит не входит
    if limited:
        mode = "rules"
    name = Path(file.filename or "документ").name[:200]
    prev = st.previous_done(pid)
    doc_id = st.document(pid, name, sha, len(data))
    import uuid

    rid = uuid.uuid4().hex[:12]
    run = st.create_run(rid, pid, doc_id, name, sha, mode)
    job = webapp.Job(rid, name, kind="review", profile=profile, domain=domain, mode=mode, base=st.root / "runs")
    job.dir.mkdir(parents=True, exist_ok=True)
    src = job.dir / ("input" + ext)
    src.write_bytes(data)
    compare_with = None
    if prev and (p := st.run_dir(prev["id"]) / "report.json").exists():
        compare_with = p
        job.parent = prev["id"]
    job.on_finish = _on_finish
    webapp._start(job, src, compare_with=compare_with)
    return {"duplicate": False, "run": _live(run), "job": rid, "compare_with": prev["id"] if compare_with else None,
            "events": f"/api/v1/jobs/{rid}/events", **({"limited": limited} if limited else {})}


# ----------------------------------------------------------------------------------- готовый пример (v9)

EXAMPLE_FILES = {"report.json": "Данные (JSON)", "report.md": "Отчёт (Markdown)", "report.html": "Интерактивный отчёт (HTML)"}


def _example_dir() -> Path:
    from ..pipeline import ROOT

    return ROOT / "reports"


def _example_bytes(name: str) -> bytes | None:
    import gzip

    d = _example_dir()
    p = {"report.json": d / "requirements-report.json", "report.md": d / "requirements-report.md"}.get(name)
    if p is not None:
        return p.read_bytes() if p.exists() else None
    if name == "report.html":
        if (d / "requirements-report.html").exists():
            return (d / "requirements-report.html").read_bytes()
        gz = d / "requirements-report.html.gz"
        return gzip.decompress(gz.read_bytes()) if gz.exists() else None
    return None


@router.get("/example", summary="Готовый отчёт по документу организаторов — без прогона и без квоты")
def example():
    raw = _example_bytes("report.json")
    if raw is None:
        raise err(404, "not_found", "Готового примера на сервере нет")
    data = json.loads(raw.decode("utf-8"))
    pp = data.get("passport", {})
    fs = [f for r in data.get("requirements", []) for f in r.get("findings", [])] + list(data.get("set_findings", []))
    counts = {s: sum(1 for f in fs if f.get("severity") == s) for s in ("critical", "major", "minor")}
    sc = data.get("scores", {})
    return {"document": pp.get("document", ""), "model": pp.get("model", ""), "started": pp.get("started", ""),
            "agent_version": pp.get("agent_version", ""),
            "summary": {"score": sc.get("document"), "readiness": sc.get("readiness"), "critical": counts["critical"],
                        "major": counts["major"],
                        "reqs": sum(1 for r in data.get("requirements", []) if r.get("kind", "requirement") == "requirement"),
                        "verdict": data.get("verdict") or {}},
            "report": data,
            "files": {label: f"/api/v1/example/files/{n}" for n, label in EXAMPLE_FILES.items() if _example_bytes(n) is not None}}


@router.get("/example/files/{name}", summary="Файл готового примера")
def example_file(name: str):
    from fastapi.responses import Response

    raw = _example_bytes(name) if name in EXAMPLE_FILES else None
    if raw is None:
        raise err(404, "not_found", "Файл не найден")
    media = {"report.json": "application/json", "report.md": "text/markdown; charset=utf-8",
             "report.html": "text/html; charset=utf-8"}[name]
    headers = {} if name == "report.html" else {"Content-Disposition": f'attachment; filename="{name}"'}
    return Response(raw, media_type=media, headers=headers)


ANSWERS_MAX = 1024 * 1024


@router.post("/runs/{rid}/answers", status_code=202, summary="Ответы аналитика → новый прогон с учётом ответов")
async def run_answers(rid: str, request: Request):
    """Тело: multipart с полем `file` (.md/.txt, ≤ 1 МБ) или JSON {"text": "### Q-01\\nответ…"}. Тот же документ
    проверяется заново с учётом ответов; новый прогон сравнивается с исходным (поле compare)."""
    from ..answers import HEAD_RE, parse_answers

    webapp = _app()
    src_run = _run_or_404(rid)
    if src_run["status"] != "done":
        raise err(409, "not_ready", "Исходный прогон ещё не завершён — ответы можно отправить после отчёта")
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        try:
            body = await request.json()
        except ValueError:
            raise err(422, "invalid", "Тело запроса — не JSON") from None
        text = str((body or {}).get("text", "")) if isinstance(body, dict) else ""
    else:
        form = await request.form()
        up = form.get("file")
        if up is None or not hasattr(up, "read"):
            raise err(400, "bad_request", "Передайте файл ответов (поле file) или JSON {\"text\": …}")
        raw = await up.read()
        if len(raw) > ANSWERS_MAX:
            raise err(413, "too_large", "Файл ответов больше 1 МБ")
        text = raw.decode("utf-8", errors="replace")
    if not HEAD_RE.search(text):
        raise err(400, "bad_request", "Нет заголовков «### Q-xx» — возьмите шаблон ответов из файлов прогона")
    parsed = parse_answers(text)
    if not parsed:
        raise err(400, "empty", "Ни один вопрос не получил ответа")
    st = _store()
    src_dir = st.run_dir(rid)
    src_json = src_dir / "report.json"
    inputs = sorted(src_dir.glob("input.*"))
    if not src_json.exists():
        raise err(404, "not_found", "Файлы исходного прогона не найдены")
    if not inputs:  # v13: на демо-сервере документ удаляется после прогона (DEMO_PURGE_MINUTES)
        raise err(410, "purged", "Документ уже удалён с сервера после проверки — загрузите его снова, чтобы перепроверить с ответами.")
    mode = src_run.get("mode", "llm")
    limited = enforce_limit(request) if mode == "llm" else None
    if limited:
        mode = "rules"
    from types import SimpleNamespace

    from ..answers import _resolve

    qs = [SimpleNamespace(qid=q.get("qid", ""), rid=q.get("rid", ""), ref=q.get("ref", ""), criterion=q.get("criterion", ""),
                          refs=q.get("refs", []) or [])
          for q in json.loads(src_json.read_text(encoding="utf-8")).get("questions", [])]
    _triples, unknown = _resolve(qs, parsed)  # то же сопоставление, что и при перепроверке
    import uuid

    new_id = uuid.uuid4().hex[:12]
    run = st.create_run(new_id, src_run["project_id"], src_run["document_id"], src_run["doc_name"], src_run["doc_hash"], mode)
    job = webapp.Job(new_id, src_run["doc_name"], kind="review", mode=mode, base=st.root / "runs")
    job.dir.mkdir(parents=True, exist_ok=True)
    src = job.dir / inputs[0].name
    src.write_bytes(inputs[0].read_bytes())
    job.answers = job.dir / "answers.md"
    job.answers.write_text(text, encoding="utf-8")
    job.parent = rid
    job.on_finish = _on_finish
    webapp._start(job, src, compare_with=src_json)
    return {"run": _live(run), "job": new_id, "answers_of": rid, "events": f"/api/v1/jobs/{new_id}/events",
            "matched": len(parsed) - len(unknown), "unknown_qids": unknown, **({"limited": limited} if limited else {})}


def purge_minutes() -> int | None:
    """v13: через сколько минут после прогона удалить загруженный документ (input.*); None — не удалять."""
    import os

    raw = os.getenv("DEMO_PURGE_MINUTES", "").strip()
    try:
        return max(0, int(raw)) if raw else None
    except ValueError:
        return None


def _purge_input(job) -> None:
    """Удалить загруженный документ прогона (отчёт остаётся в истории); 0 минут — сразу."""
    m = purge_minutes()
    if m is None:
        return

    def drop():
        for p in job.dir.glob("input.*"):
            try:
                p.unlink()
            except OSError:
                pass
    if m == 0:
        drop()
    else:
        import threading

        t = threading.Timer(m * 60, drop)
        t.daemon = True
        t.start()


def _on_finish(job) -> None:
    _purge_input(job)
    st = _store()
    if job.status != "done":
        st.update_run(job.id, status=job.status, error=job.error, finished=_now())
        return
    data = json.loads(job.json_path.read_text(encoding="utf-8")) if job.json_path.exists() else {}
    fs = [f for r in data.get("requirements", []) for f in r.get("findings", [])] + list(data.get("set_findings", []))
    counts = {s: sum(1 for f in fs if f.get("severity") == s) for s in ("critical", "major", "minor")}
    pp = data.get("passport", {})
    st.update_run(job.id, status="done", finished=_now(), score=job.summary.get("score"),
                  readiness=job.summary.get("readiness"), critical=counts["critical"], major=counts["major"],
                  findings=len(fs), verdict=_verdict(counts), model=pp.get("model", ""),
                  agent_version=str(pp.get("agent_version", "")), artifacts=job.artifacts,
                  compare=job.summary.get("compare"))


def _now() -> float:
    import time

    return time.time()


# ----------------------------------------------------------------------------------- прогоны

@router.get("/runs/{rid}", summary="Прогон: сводка, вердикт, файлы, сравнение с прошлой версией")
def get_run(rid: str):
    run = _live(_run_or_404(rid))
    run["files"] = {k: f"/api/v1/runs/{rid}/files/{v}" for k, v in run["artifacts"].items()}
    return run


@router.delete("/runs/{rid}", summary="Удалить прогон и его файлы")
def delete_run(rid: str):
    run = _run_or_404(rid)
    job = _app().JOBS.get(rid)
    if run["status"] in ("queued", "running") and job and not job.done:
        raise err(409, "busy", "Прогон ещё идёт — сначала отмените его (POST /api/v1/jobs/{id}/cancel)")
    _store().delete_run(rid)
    _app().JOBS.pop(rid, None)
    return {"deleted": rid}


@router.get("/runs/{rid}/files/{name}", summary="Файл отчёта прогона")
def run_file(rid: str, name: str):
    """Только файлы из списка артефактов прогона: report.html/md/json, CSV для Jira, .feature, xlsx, исправленный документ."""
    run = _run_or_404(rid)
    if not FILE_RE.match(name) or name not in run["artifacts"].values():
        raise err(404, "not_found", "Файл не найден")
    path = _store().run_dir(rid) / name
    if not path.is_file():
        raise err(404, "not_found", "Файл не найден")
    return FileResponse(path, filename=None if name.endswith(".html") else name)


@router.post("/runs/{rid}/ask", summary="Ассистент по отчёту с источниками")
def ask(rid: str, payload: dict = Body(..., examples=[{"q": "Что исправить первым?", "stream": False}])):
    """Типовые вопросы — по данным отчёта; остальные — по источникам (требование, строка документа,
    фрагмент базы знаний kb/ с пометкой «пересказ» у норм РК), модель отвечает только по ним.
    `stream: true` — ответ событиями SSE: sources, answer (частями), done."""
    _run_or_404(rid)
    path = _store().run_dir(rid) / "report.json"
    if not path.exists():
        raise err(409, "not_ready", "Отчёт ещё не готов")
    q = str(payload.get("q", "")).strip()[:500]
    if not q:
        raise err(400, "bad_request", "Пустой вопрос")
    res = answer(rid, q)
    if not payload.get("stream"):
        return res

    def gen():
        yield _sse("sources", {"sources": res["sources"]})
        for part in re.split(r"(?<=[.!?\n])\s+", res["answer"]):
            if part:
                yield _sse("answer", {"text": part + " "})
        yield _sse("done", {k: v for k, v in res.items() if k != "sources"})

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


def _sse(kind: str, data: dict) -> str:
    return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def answer(rid: str, q: str) -> dict:
    from .assistant import Assistant

    report = json.loads((_store().run_dir(rid) / "report.json").read_text(encoding="utf-8"))
    base = Assistant(json.loads(json.dumps(report))).answer(q)  # копия: Assistant приводит basis к формату UI
    if base.get("source") != "подсказка":  # вопрос понят по данным отчёта
        by_rid = {r["rid"]: r for r in report.get("requirements", [])}
        return {**base, "sources": [_unify(s, by_rid) for s in base.get("sources", [])], "mode": "по данным отчёта"}
    from ..rag.index import get_kb
    from ..rag.qa import answer_with_sources

    doc_text = _doc_text(rid)
    llm = _llm_or_none()
    res = answer_with_sources(q, report, doc_text, get_kb(), llm)
    for s in res["sources"]:
        if s["kind"] == "kb":
            s["paraphrase"] = s["file"].startswith("kb/law_kz")
            s["note"] = "пересказ нормы, не текст закона" if s["paraphrase"] else s.get("note", "")
    return {"answer": res["answer"], "sources": res["sources"], "mode": res["mode"],
            "refs": [s["ref"] for s in res["sources"] if s["kind"] == "requirement"],
            "source": "источники", "suggest": base.get("suggest", [])}


def _unify(s: dict, by_rid: dict) -> dict:
    """Источник ассистента Studio ({type: req|line|kb}) → единый формат API v1 ({kind: requirement|document|kb})."""
    t = s.get("type")
    if t == "req":
        r = by_rid.get(s["id"], {})
        return {"kind": "requirement", "ref": s["id"], "label": s.get("label") or s["id"], "quote": r.get("text", ""),
                "line": r.get("line_start")}
    if t == "line":
        return {"kind": "document", "ref": f"L{s['line']}", "label": f"строка {s['line']}", "quote": s.get("text", ""),
                "line": s["line"], "rid": s.get("rid")}
    if t == "kb":
        law = s.get("kind") == "law"
        return {"kind": "kb", "ref": s.get("source", ""), "label": s.get("clause") or s.get("source", ""), "source": s.get("source", ""),
                "quote": s.get("quote", ""), "url": s.get("url", ""), "paraphrase": bool(s.get("paraphrase")) or law,
                "note": "пересказ нормы, не текст закона" if law or s.get("paraphrase") else ""}
    return s


def _doc_text(rid: str) -> str:
    from ..reader import read_document

    src = next(iter(sorted(_store().run_dir(rid).glob("input.*"))), None)
    if not src:
        return ""
    try:
        return read_document(src).text
    except Exception:
        return ""


def _llm_or_none():
    from .live import provider_status

    st = provider_status()
    if st["mock"] or not st["key_ok"]:
        return None
    try:
        from ..llm import build_llm_from_env

        llm = build_llm_from_env()
        llm.max_retries = min(llm.max_retries, 1)  # ассистент отвечает быстро; при 429 — ответ по источникам без модели
        return llm
    except Exception:
        return None


# ----------------------------------------------------------------------------------- задачи (живой прогон)

@router.get("/jobs/{jid}/events", summary="События прогона (SSE)")
async def job_events(jid: str):
    """step {i, name, pct} · queued {position} · started · split · batch_start/batch_done · log ·
    done {summary, artifacts} · error {code, msg, fallback?} · cancelled."""
    webapp = _app()
    if jid not in webapp.JOBS:
        raise err(404, "not_found", "Прогон не найден или сервер был перезапущен")
    return await webapp.events(jid)


@router.post("/jobs/{jid}/cancel", summary="Отменить прогон")
def job_cancel(jid: str):
    return _app().cancel(jid)
