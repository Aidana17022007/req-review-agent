"""Резервный провайдер (LLM_BACKUP_PROVIDER): DeepSeek отказал — тот же запрос уходит в Gemini, без сети."""
import json

import pytest

from req_review import llm as llm_mod
from req_review.llm import LLMFatalError, build_llm_from_env

GEMINI_OK = {"candidates": [{"content": {"parts": [{"text": '{"ok": "gemini"}'}]}}]}


class Resp:
    def __init__(self, code, payload):
        self.status_code = code
        self._p = payload
        self.text = json.dumps(payload)
        self.headers = {}

    def json(self):
        return self._p


@pytest.fixture
def env(monkeypatch):
    for k, v in {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-test", "OPENAI_BASE_URL": "https://api.deepseek.com/v1",
                 "OPENAI_MODEL": "deepseek-chat", "GEMINI_API_KEY": "g-test", "GEMINI_MODEL": "gemini-main",
                 "GEMINI_FALLBACK_MODELS": "gemini-lite", "LLM_BACKUP_PROVIDER": "gemini", "LLM_CACHE": "0",
                 "LLM_MIN_INTERVAL": "0"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("GEMINI_API", raising=False)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    return monkeypatch


def _post(deepseek_code, seen):
    def fake_post(url, json=None, headers=None, timeout=None):
        seen.append("deepseek" if "deepseek" in url else "gemini")
        if "deepseek" in url:
            if deepseek_code == 200:
                return Resp(200, {"choices": [{"message": {"content": '{"ok": "deepseek"}'}}]})
            return Resp(deepseek_code, {"error": {"message": "Insufficient Balance" if deepseek_code == 402 else "busy"}})
        return Resp(200, GEMINI_OK)
    return fake_post


@pytest.mark.parametrize("code", [402, 401, 429, 503])
def test_deepseek_failure_goes_to_gemini(env, code):
    """Баланс (402), ключ (401), квота (429), перегрузка (503) у DeepSeek — ответ всё равно получен, от Gemini."""
    seen = []
    env.setattr(llm_mod.requests, "post", _post(code, seen))
    llm = build_llm_from_env()
    assert llm.backup is not None and llm.backup.stats is llm.stats
    assert llm.generate_json("s", "p") == {"ok": "gemini"}
    assert seen[0] == "deepseek" and seen[-1] == "gemini"
    assert len(llm.stats.switches) == 1 and "deepseek-chat → gemini / gemini-main" in llm.stats.switches[0]
    assert llm.label == "gemini / gemini-main"  # паспорт отчёта называет модель, которая отвечала
    seen.clear()
    assert llm.generate_json("s", "p2") == {"ok": "gemini"} and seen == ["gemini"]  # дальше — сразу резерв
    assert len(llm.stats.switches) == 1


def test_deepseek_ok_backup_untouched(env):
    seen = []
    env.setattr(llm_mod.requests, "post", _post(200, seen))
    llm = build_llm_from_env()
    assert llm.generate_json("s", "p") == {"ok": "deepseek"} and seen == ["deepseek"]
    assert not llm.stats.switches and llm.label == "openai-compatible / deepseek-chat"


def test_no_backup_variable_keeps_old_behaviour(env):
    """Без LLM_BACKUP_PROVIDER — как раньше: ошибка DeepSeek видна, Gemini не вызывается."""
    env.delenv("LLM_BACKUP_PROVIDER")
    seen = []
    env.setattr(llm_mod.requests, "post", _post(402, seen))
    llm = build_llm_from_env()
    assert llm.backup is None
    with pytest.raises(LLMFatalError):
        llm.generate_json("s", "p")
    assert seen == ["deepseek"]


def test_backup_without_key_is_skipped(env):
    """Резерв указан, но ключа Gemini нет — сервис стартует как раньше, без резерва."""
    env.delenv("GEMINI_API_KEY")
    llm = build_llm_from_env()
    assert llm.backup is None and llm.label == "openai-compatible / deepseek-chat"
