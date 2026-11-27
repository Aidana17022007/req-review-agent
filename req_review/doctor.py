"""v13+: `python review.py doctor [--live]` — что выбрано и работает ли модель (ключ не печатается).

Без --live: провайдер, модель, резервные модели, задан ли ключ (да/нет), кэш, параллельность и лимиты.
С --live: один короткий запрос к модели (таймаут 10 с) и время ответа.
Код выхода: 0 — всё в порядке, 2 — ошибка настройки (нет ключа, неизвестный провайдер), 4 — модель не ответила.
"""
from __future__ import annotations

import os
import time

KEY_ENV = {"gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"], "anthropic": ["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"],
           "claude": ["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"], "openrouter": ["OPENROUTER_API_KEY"],
           "openai": ["OPENAI_API_KEY"], "ollama": [], "rules": [], "mock": []}


def run(live: bool = False, out=print) -> int:
    from .llm import LLMError, build_llm_from_env, default_provider
    from .parallel import concurrency

    provider = default_provider()
    keys = KEY_ENV.get(provider, [])
    has_key = any(os.getenv(k, "").strip() for k in keys) if keys else True
    out(f"провайдер: {provider}")
    try:
        llm = build_llm_from_env()
    except LLMError as e:
        out(f"❌ настройка модели: {str(e)[:300]}")
        return 2
    out(f"модель: {llm.label}" + (f" · резервные: {', '.join(llm.fallback_models)}" if getattr(llm, "fallback_models", None) else ""))
    out("ключ: не нужен" if not keys else f"ключ: {'задан' if has_key else 'НЕ задан'} ({' / '.join(keys)})")
    out(f"кэш ответов: {os.getenv('LLM_CACHE', '1')} · параллельно запросов: {concurrency()} · пауза между стартами: "
        f"{getattr(llm, 'min_interval', 0)} с")
    if keys and not has_key:
        return 2
    if not live:
        out("живой запрос не выполнялся (добавьте --live)")
        return 0
    llm.max_retries = 0
    llm.timeout = 10
    if hasattr(llm, "fallback_models"):
        llm.fallback_models = []
    old = os.environ.get("LLM_CACHE")
    os.environ["LLM_CACHE"] = "0"
    t = time.monotonic()
    try:
        llm.generate_json('Верни JSON {"ok": true}.', "проверка связи", task="ping")
        out(f"✅ модель ответила за {time.monotonic() - t:.1f} с")
        return 0
    except Exception as e:  # noqa: BLE001
        out(f"❌ модель не ответила за {time.monotonic() - t:.1f} с: {str(e)[:200]}")
        return 4
    finally:
        if old is None:
            os.environ.pop("LLM_CACHE", None)
        else:
            os.environ["LLM_CACHE"] = old
