"""Живой прогон в Studio: наблюдатель над моделью, который сообщает о пакетах требований по мере проверки.

Логику проверки не меняет — только смотрит на вход и сырой ответ модели (предварительный статус до проверки цитат)
и пересылает события в SSE-поток задачи. Итоговые данные приходят из отчёта после завершения прогона.
"""
from __future__ import annotations

import os
import time

ORDER = {"critical": 0, "major": 1, "minor": 2}


def demo_delay(provider: str) -> float:
    """Пауза на пакет для демонстрации: у mock-модели ответы мгновенные, и живая таблица пролетела бы за долю секунды."""
    v = os.getenv("STUDIO_DEMO_DELAY")
    if v is not None:
        try:
            return max(0.0, float(v))
        except ValueError:
            return 0.0
    return 0.6 if provider == "mock" else 0.0


class ObservedLLM:
    """Прокси над BaseLLM: generate_json перехватывается, остальные атрибуты (stats, label, provider…) — как у модели."""

    def __init__(self, inner, emit, delay: float = 0.0):
        self._inner = inner
        self._emit = emit
        self._delay = delay
        self.phase = 0  # номер текущего шага пайплайна; события пакетов шлём только на шаге «Проверка требований»

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def generate_json(self, system, prompt, *, task: str = "", context: dict | None = None):
        batch = list((context or {}).get("reqs") or []) if task == "check" else []
        live = bool(batch) and self.phase == 2
        if live:
            self._emit("batch_start", reqs=[{"rid": r.rid, "doc_id": r.doc_id, "text": getattr(r, "short", r.text)[:200],
                                             "section": r.section} for r in batch])
        if self._delay and task in ("check", "set", "extras", "critic") and self.phase < 6:
            time.sleep(self._delay)
        try:
            data = self._inner.generate_json(system, prompt, task=task, context=context)
        except Exception:
            if live:
                self._emit("batch_fail", rids=[r.rid for r in batch])
            raise
        if live:
            got = {}
            for item in (data or {}).get("results", []) or []:
                fs = item.get("findings") or []
                sev = [str(f.get("severity", "")).lower() for f in fs if isinstance(f, dict)]
                worst = min((s for s in sev if s in ORDER), key=ORDER.get, default="ok")
                test = (item.get("test") or {}).get("possible") if isinstance(item.get("test"), dict) else None
                got[str(item.get("id", "")).strip()] = {"n": len(fs), "worst": worst, "test": test}
            self._emit("batch_done", results=[{"rid": r.rid, **got.get(r.rid, {"n": 0, "worst": "unknown", "test": None})} for r in batch])
        return data


def classify_error(msg: str) -> str:
    """Тип ошибки для понятного экрана: нет ключа, исчерпан лимит API или прочее."""
    m = msg.lower()
    if "не найдено ни одного требования" in m:
        return "noreqs"
    if any(k in m for k in ("api_key", "не задан", "не-латинские", "http 401", "http 403", "api key", "permission_denied", "unauthenticated")):
        return "key"
    if any(k in m for k in ("квота", "http 429", "quota", "resource_exhausted", "rate limit", "лимит")):
        return "quota"
    return "error"


def provider_status() -> dict:
    """Что Studio знает о модели до запуска: провайдер, модель, задан ли ключ (сам ключ не возвращается)."""
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    key_name = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "openai-compatible": "OPENAI_API_KEY"}.get(provider)
    model = {"gemini": os.getenv("GEMINI_MODEL", "gemini-3.8-flash"), "mock": "mock-heuristic"}.get(
        provider, os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    if provider == "mock":
        key_ok = True
    elif key_name:
        v = os.getenv(key_name, "").strip().strip('"').strip("'")
        local = provider.startswith("openai") and any(h in os.getenv("OPENAI_BASE_URL", "") for h in ("localhost", "127.0.0.1"))
        key_ok = (bool(v) and v.isascii()) or local
    else:
        key_ok = False
    return {"provider": provider, "model": model.strip(), "key_ok": key_ok, "key_name": key_name or "", "mock": provider == "mock"}
