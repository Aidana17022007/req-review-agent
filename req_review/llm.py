"""Клиенты LLM: Gemini (Google AI Studio, по умолчанию), любой OpenAI-совместимый API, mock.

Все провайдеры возвращают JSON (dict). Есть ограничение частоты запросов под бесплатный
тариф, повторы при 429/5xx с учётом retryDelay и повтор при невалидном JSON.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests


class LLMError(RuntimeError):
    pass


class LLMFatalError(LLMError):
    """Ошибка, при которой продолжать бессмысленно (неверный ключ, модель не найдена)."""


@dataclass
class LLMStats:
    calls: int = 0
    cached: int = 0
    retries: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    errors: list[str] = field(default_factory=list)


class BaseLLM:
    provider = "base"
    model = ""

    def __init__(self, min_interval: float = 0.0, max_retries: int = 6, timeout: float = 180.0):
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self.stats = LLMStats()
        self._last_call = 0.0

    # --- публичный метод ---
    def generate_json(self, system: str, prompt: str, *, task: str = "", context: dict | None = None) -> dict:
        cache = self._cache_path(system, prompt)
        if cache and cache.exists():
            try:
                data = parse_json(cache.read_text(encoding="utf-8"))
                self.stats.cached += 1
                return data
            except (ValueError, OSError):
                pass
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                text = self._call(system, prompt if attempt == 0 or not isinstance(last_err, json.JSONDecodeError)
                                  else prompt + "\n\nВНИМАНИЕ: предыдущий ответ был невалидным JSON. Верни ТОЛЬКО валидный JSON.",
                                  task=task, context=context or {})
                self.stats.calls += 1
                data = parse_json(text)
                if cache:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(text, encoding="utf-8")
                return data
            except json.JSONDecodeError as e:
                last_err = e
                self.stats.retries += 1
                continue
            except RetryableError as e:
                last_err = e
                self.stats.retries += 1
                wait = e.retry_after if e.retry_after else min(60.0, 2.0 * (2 ** attempt))
                print(f"  [llm] {e} — повтор через {wait:.0f} с (попытка {attempt + 1}/{self.max_retries})", flush=True)
                time.sleep(wait)
        msg = f"LLM не ответил после {self.max_retries} повторов: {last_err}"
        self.stats.errors.append(msg)
        raise LLMError(msg)

    def _cache_path(self, system: str, prompt: str) -> Path | None:
        """Кэш ответов по хэшу (провайдер + модель + температура + промпт): повторный прогон не тратит квоту."""
        if self.provider == "mock" or os.getenv("LLM_CACHE", "1").strip() in ("0", "false", "no", ""):
            return None
        h = hashlib.sha256(f"{self.provider}|{self.model}|{getattr(self, 'temperature', '')}|{system}|{prompt}".encode()).hexdigest()
        base = Path(os.getenv("LLM_CACHE_DIR", Path(__file__).resolve().parent.parent / ".cache" / "llm"))
        return base / f"{h}.json"

    def _throttle(self):
        if self.min_interval <= 0:
            return
        wait = self._last_call + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _call(self, system: str, prompt: str, *, task: str, context: dict) -> str:  # pragma: no cover
        raise NotImplementedError

    @property
    def label(self) -> str:
        return f"{self.provider} / {self.model}"


class RetryableError(Exception):
    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


def parse_json(text: str) -> dict:
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
    if m:
        t = m.group(1).strip()
    if not t.startswith(("{", "[")):
        i = min([p for p in (t.find("{"), t.find("[")) if p >= 0], default=-1)
        if i >= 0:
            t = t[i:]
    data = json.loads(t)
    if isinstance(data, list):
        data = {"items": data}
    return data


def _retry_delay_from_body(body: str) -> float | None:
    m = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', body)
    if m:
        return float(m.group(1)) + 1
    return None


class GeminiLLM(BaseLLM):
    provider = "gemini"

    def __init__(self, api_key: str, model: str, base_url: str | None = None, temperature: float = 0.0, **kw):
        super().__init__(**kw)
        if not api_key:
            raise LLMError("Не задан GEMINI_API_KEY. Получите ключ на https://aistudio.google.com/apikey и положите в .env")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.base_url = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")

    def _call(self, system, prompt, *, task, context):
        url = f"{self.base_url}/models/{self.model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": self.temperature, "responseMimeType": "application/json"},
        }
        try:
            r = requests.post(url, json=body, headers={"x-goog-api-key": self.api_key}, timeout=self.timeout)
        except requests.RequestException as e:
            raise RetryableError(f"сетевая ошибка: {e}")
        if r.status_code in (429, 500, 502, 503, 504):
            raise RetryableError(f"HTTP {r.status_code}", _retry_delay_from_body(r.text))
        if r.status_code != 200:
            raise LLMFatalError(f"Gemini HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        um = data.get("usageMetadata", {})
        self.stats.prompt_tokens += um.get("promptTokenCount", 0)
        self.stats.output_tokens += um.get("candidatesTokenCount", 0)
        cands = data.get("candidates") or []
        if not cands:
            raise RetryableError(f"пустой ответ: {str(data.get('promptFeedback', ''))[:200]}")
        parts = cands[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            raise RetryableError(f"пустой текст ответа (finishReason={cands[0].get('finishReason')})")
        return text


class OpenAICompatLLM(BaseLLM):
    provider = "openai-compatible"

    def __init__(self, api_key: str, model: str, base_url: str, temperature: float = 0.0, **kw):
        super().__init__(**kw)
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature

    def _call(self, system, prompt, *, task, context):
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            r = requests.post(f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise RetryableError(f"сетевая ошибка: {e}")
        if r.status_code in (429, 500, 502, 503, 504):
            ra = r.headers.get("retry-after")
            raise RetryableError(f"HTTP {r.status_code}", float(ra) if ra and ra.isdigit() else None)
        if r.status_code != 200:
            raise LLMFatalError(f"LLM HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        u = data.get("usage", {})
        self.stats.prompt_tokens += u.get("prompt_tokens", 0)
        self.stats.output_tokens += u.get("completion_tokens", 0)
        return data["choices"][0]["message"]["content"]


def _env_key(name: str) -> str:
    """Ключ из .env: проверяем, что это не заглушка вида «ваш_ключ» (HTTP-заголовки допускают только ASCII)."""
    v = os.getenv(name, "").strip().strip('"').strip("'")
    if v and not v.isascii():
        raise LLMError(f"{name} в .env содержит не-латинские символы — похоже, там осталась заглушка вместо ключа. "
                       f"Вставьте настоящий ключ (например, GEMINI_API_KEY=AIza...).")
    return v


def build_llm_from_env() -> BaseLLM:
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    common = dict(
        min_interval=float(os.getenv("LLM_MIN_INTERVAL", "6")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "6")),
        timeout=float(os.getenv("LLM_TIMEOUT", "180")),
    )
    temperature = float(os.getenv("LLM_TEMPERATURE", "0"))
    if provider == "gemini":
        return GeminiLLM(
            api_key=_env_key("GEMINI_API_KEY"),
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
            base_url=os.getenv("GEMINI_BASE_URL") or None,
            temperature=temperature,
            **common,
        )
    if provider in ("openai", "openai-compatible"):
        return OpenAICompatLLM(
            api_key=_env_key("OPENAI_API_KEY"),
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip(),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip(),
            temperature=temperature,
            **common,
        )
    if provider == "mock":
        from .mock_llm import MockLLM

        return MockLLM()
    raise LLMError(f"Неизвестный LLM_PROVIDER={provider!r}. Допустимо: gemini, openai, mock")
