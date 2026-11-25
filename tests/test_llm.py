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
