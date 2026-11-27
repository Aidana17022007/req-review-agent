"""v14: скорость — 4 запроса одновременно, без пауз на коротком прогоне, сразу резервная модель при исчерпанной квоте."""
import threading
import time

import req_review.llm as llm_mod
from req_review.llm import BaseLLM, GeminiLLM


class Resp:
    def __init__(self, status, body):
        import json

        self.status_code = status
        self._body = body
        self.text = json.dumps(body)
        self.headers = {}

    def json(self):
        return self._body


def test_defaults_concurrency_interval_and_fast_batch(monkeypatch):
    from req_review.llm import _min_interval, _rpm_window
    from req_review.parallel import concurrency
    from req_review.pipeline import PROFILES

    for k in ("LLM_CONCURRENCY", "LLM_MIN_INTERVAL", "LLM_RPM", "LLM_RPM_WINDOW"):
        monkeypatch.delenv(k, raising=False)
    assert concurrency() == 4 and _min_interval() == 0.0 and _rpm_window(15) == 15
    assert PROFILES["fast"]["batch_size"] == 10 and PROFILES["deep"]["batch_size"] == 6


def test_first_429_with_quota_switches_at_once_without_waiting(monkeypatch):
    """429 «Quota exceeded» с короткой задержкой: не ждём и не повторяем на той же модели — сразу резервная."""
    used, slept = [], []

    def fake_post(url, json=None, headers=None, timeout=None):
        used.append(url.split("/models/")[1].split(":")[0])
        if "main-model" in url:
            return Resp(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded for metric: requests",
                                        "details": [{"retryDelay": "20s"}]}})
        return Resp(200, {"candidates": [{"content": {"parts": [{"text": '{"ok": 5}'}]}}]})

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: slept.append(s))
    g = GeminiLLM(api_key="k", model="main-model", fallback=["lite-model"])
    assert g.generate_json("s", "p") == {"ok": 5}
    assert used == ["main-model", "lite-model"] and not slept and "квота" in g.stats.switches[0]


def test_429_without_quota_still_waits_once(monkeypatch):
    """Обычный 429 (без «quota») — короткое ожидание и повтор на той же модели, как раньше."""
    used, slept = [], []

    def fake_post(url, json=None, headers=None, timeout=None):
        used.append(url.split("/models/")[1].split(":")[0])
        if len(used) == 1:
            return Resp(429, {"error": {"message": "Too many requests", "details": [{"retryDelay": "2s"}]}})
        return Resp(200, {"candidates": [{"content": {"parts": [{"text": '{"ok": 6}'}]}}]})

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: slept.append(s))
    g = GeminiLLM(api_key="k", model="main-model", fallback=["lite-model"])
    assert g.generate_json("s", "p") == {"ok": 6}
    assert used == ["main-model", "main-model"] and slept == [3.0] and not g.stats.switches


def test_rpm_window_lets_short_burst_go_and_holds_the_rest():
    """Окно N стартов / 60 с: первые N запросов стартуют сразу, (N+1)-й ждёт, пока самый ранний не выйдет из окна."""

    class Fake(BaseLLM):
        provider, model = "fake", "m"

        def __init__(self):
            super().__init__(min_interval=0.0, max_retries=0, rpm_window=3)
            self.starts = []
            self.lk = threading.Lock()

        def _call(self, system, prompt, *, task, context):
            with self.lk:
                self.starts.append(time.perf_counter())
            return "{}"

        def _cache_path(self, system, prompt):
            return None

    f = Fake()
    t0 = time.perf_counter()
    for i in range(3):
        f.generate_json("s", str(i))
    assert max(f.starts) - t0 < 0.5, "короткая серия — без пауз"
    # четвёртый старт по расписанию окна: не раньше, чем через 60 с после первого (проверяем расчёт, не ждём минуту)
    with f._lock:
        nxt = f._starts[-f.rpm_window] + 60.0
    assert nxt - t0 >= 59.5
