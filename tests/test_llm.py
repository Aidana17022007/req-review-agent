"""Проверка клиента Gemini без сети: подменяем requests.post."""
import json

import pytest

from req_review import llm as llm_mod
from req_review.llm import GeminiLLM, LLMFatalError


class Resp:
    def __init__(self, code, payload):
        self.status_code = code
        self._p = payload
        self.text = json.dumps(payload)
        self.headers = {}

    def json(self):
        return self._p


def test_gemini_parses_json_and_retries_429(monkeypatch):
    calls = []
    ok = {"candidates": [{"content": {"parts": [{"text": '```json\n{"results": []}\n```'}]}}],
          "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3}}
    busy = {"error": {"code": 429, "details": [{"retryDelay": "0s"}]}}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, json, headers))
        return Resp(429, busy) if len(calls) == 1 else Resp(200, ok)

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    g = GeminiLLM(api_key="k", model="gemini-2.5-flash")
    assert g.generate_json("sys", "prompt") == {"results": []}
    url, body, headers = calls[-1]
    assert url.endswith("/models/gemini-2.5-flash:generateContent")
    assert headers["x-goog-api-key"] == "k"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert g.stats.calls == 1 and g.stats.retries == 1 and g.stats.prompt_tokens == 10


def test_gemini_bad_key_is_fatal(monkeypatch):
    monkeypatch.setattr(llm_mod.requests, "post", lambda *a, **k: Resp(400, {"error": {"message": "API key not valid"}}))
    with pytest.raises(LLMFatalError):
        GeminiLLM(api_key="bad", model="m").generate_json("s", "p")


def test_daily_quota_fails_fast(monkeypatch):
    busy = {"error": {"code": 429, "details": [{"retryDelay": "47158s"}]}}
    monkeypatch.setattr(llm_mod.requests, "post", lambda *a, **k: Resp(429, busy))
    slept = []
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: slept.append(s))
    with pytest.raises(LLMFatalError, match="Квота"):
        GeminiLLM(api_key="k", model="m").generate_json("s", "p")
    assert not slept


def test_json_repair_trailing_commas_and_truncation():
    from req_review.llm import parse_json

    assert parse_json('{"results": [{"id": "R-001", "findings": [],},],}') == {"results": [{"id": "R-001", "findings": []}]}
    cut = parse_json('```json\n{"results": [{"id": "R-001", "findings": [{"quote": "быстро')
    assert cut["results"][0]["id"] == "R-001"


def test_rpm_limit_sets_interval(monkeypatch):
    from req_review.llm import _min_interval

    monkeypatch.setenv("LLM_MIN_INTERVAL", "0")
    monkeypatch.setenv("LLM_RPM", "5")
    assert _min_interval() == 12.0


def test_overloaded_model_falls_back(monkeypatch):
    """503 «high demand» у основной модели → переключение на резервную, ответ получен, переключение записано."""
    used = []

    def fake_post(url, json=None, headers=None, timeout=None):
        used.append(url.split("/models/")[1].split(":")[0])
        if "main-model" in url:
            return Resp(503, {"error": {"message": "high demand"}})
        return Resp(200, {"candidates": [{"content": {"parts": [{"text": '{"ok": 1}'}]}}]})

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    g = GeminiLLM(api_key="k", model="main-model", fallback=["lite-model"])
    assert g.generate_json("s", "p") == {"ok": 1}
    assert used[-1] == "lite-model" and g.model == "lite-model"
    assert g.stats.switches and "main-model → lite-model" in g.stats.switches[0]


def test_response_schema_sent_and_fallback_on_rejection(monkeypatch):
    """responseSchema уходит для известных задач; если модель её отвергает (400 …schema…) — повтор в JSON-режиме."""
    bodies = []

    def fake_post(url, json=None, headers=None, timeout=None):
        bodies.append(json)
        if "responseSchema" in json["generationConfig"]:
            return Resp(400, {"error": {"message": "Invalid JSON payload: responseSchema not supported"}})
        return Resp(200, {"candidates": [{"content": {"parts": [{"text": '{"verdicts": []}'}]}}]})

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    g = GeminiLLM(api_key="k", model="m")
    assert g.generate_json("s", "p", task="critic") == {"verdicts": []}
    assert "responseSchema" in bodies[0]["generationConfig"] and "responseSchema" not in bodies[-1]["generationConfig"]
    assert g.schema_off.get("m") is True


def test_gemini_openai_style_uses_bearer(monkeypatch):
    """GEMINI_API=openai: OpenAI-совместимый эндпоинт Gemini, ключ в Authorization: Bearer, без x-goog-api-key."""
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, headers=headers, body=json)
        return Resp(200, {"choices": [{"message": {"content": '{"ok": 2}'}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}})

    monkeypatch.setenv("GEMINI_API", "openai")
    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    g = GeminiLLM(api_key="k", model="gemini-x")
    assert g.generate_json("s", "p") == {"ok": 2}
    assert seen["url"].endswith("/v1beta/openai/chat/completions")
    assert seen["headers"] == {"Authorization": "Bearer k"} and seen["body"]["model"] == "gemini-x"
    assert g.stats.prompt_tokens == 3


def test_quota_exhausted_switches_to_fallback(monkeypatch):
    """429 с задержкой в часы (дневная квота) — не фатальная ошибка, если есть резервная модель: переход на неё."""
    used = []

    def fake_post(url, json=None, headers=None, timeout=None):
        used.append(url.split("/models/")[1].split(":")[0])
        if "main-model" in url:
            return Resp(429, {"error": {"details": [{"retryDelay": "40000s"}]}})
        return Resp(200, {"candidates": [{"content": {"parts": [{"text": '{"ok": 3}'}]}}]})

    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    g = GeminiLLM(api_key="k", model="main-model", fallback=["lite-model"])
    assert g.generate_json("s", "p") == {"ok": 3}
    assert used == ["main-model", "lite-model"] and "квота" in g.stats.switches[0]


def test_overload_fallback_waits_for_retries(monkeypatch):
    """503 переключает на резервную модель не сразу, а после LLM_FALLBACK_AFTER повторов."""
    used = []

    def fake_post(url, json=None, headers=None, timeout=None):
        used.append(url.split("/models/")[1].split(":")[0])
        if "main-model" in url:
            return Resp(503, {"error": {"message": "high demand"}})
        return Resp(200, {"candidates": [{"content": {"parts": [{"text": '{"ok": 4}'}]}}]})

    monkeypatch.setenv("LLM_FALLBACK_AFTER", "3")
    monkeypatch.setattr(llm_mod.requests, "post", fake_post)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    g = GeminiLLM(api_key="k", model="main-model", fallback=["lite-model"])
    assert g.generate_json("s", "p") == {"ok": 4}
    assert used.count("main-model") == 4 and used[-1] == "lite-model"
