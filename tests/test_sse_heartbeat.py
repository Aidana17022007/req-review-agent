"""Поток событий прогона не молчит: пока модель думает над этапом, сервер шлёт «: ping» — прокси хостинга не рвёт
соединение, и Studio не показывает «поток недоступен» посреди живого прогона."""
import asyncio
import threading
import time


def test_events_stream_sends_heartbeat_while_job_is_silent(monkeypatch):
    from req_review.web import app as webapp

    monkeypatch.setenv("SSE_HEARTBEAT", "0.3")
    job = webapp.Job("hb000test001", "doc.md")
    job.push("step", i=3, name="Проверка набора")
    webapp.JOBS[job.id] = job

    def finish_later():  # «модель думает» 1 с без событий, затем прогон завершается
        time.sleep(1.0)
        job.push("done", ok=True)
        job.done = True

    threading.Thread(target=finish_later, daemon=True).start()

    async def collect():
        resp = await webapp.events(job.id)
        chunks = []
        async for c in resp.body_iterator:
            chunks.append(c if isinstance(c, str) else c.decode())
        return "".join(chunks)

    try:
        body = asyncio.run(collect())
    finally:
        webapp.JOBS.pop(job.id, None)
    assert body.startswith(": open")
    assert body.count(": ping") >= 2  # молчание ~1 с при интервале 0,3 с
    assert '"kind": "step"' in body and '"kind": "done"' in body
    assert body.index('"kind": "step"') < body.index(": ping") < body.index('"kind": "done"')
