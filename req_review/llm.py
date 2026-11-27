"""Клиенты LLM: Gemini (Google AI Studio, по умолчанию), любой OpenAI-совместимый API, mock.

Все провайдеры возвращают JSON (dict). Есть ограничение частоты запросов под бесплатный
тариф, повторы при 429/5xx с учётом retryDelay и повтор при невалидном JSON.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
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
    switches: list = field(default_factory=list)  # переключения на резервную модель: ["A → B (HTTP 503)"]
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
        self.fallback_models: list[str] = []
        # v12: параллельные вызовы — общий ограничитель частоты и числа одновременных запросов (LLM_CONCURRENCY)
        from .parallel import concurrency

        self._lock = threading.Lock()
        self._inflight = threading.BoundedSemaphore(concurrency())

    # --- публичный метод ---
    def generate_json(self, system: str, prompt: str, *, task: str = "", context: dict | None = None) -> dict:
        cache = self._cache_path(system, prompt)
        # LLM_CACHE=refresh (--no-cache): свежие ответы модели, кэш только пополняется — следующий прогон
        # (например, --answers по тому же документу) не тратит квоту повторно
        if cache and cache.exists() and os.getenv("LLM_CACHE", "1").strip().lower() != "refresh":
            try:
                data = parse_json(cache.read_text(encoding="utf-8"))
                with self._lock:
                    self.stats.cached += 1
                return data
            except (ValueError, OSError):
                pass
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with self._inflight:
                    self._throttle()
                    text = self._call(system, prompt if attempt == 0 or not isinstance(last_err, json.JSONDecodeError)
                                      else prompt + "\n\nВНИМАНИЕ: предыдущий ответ был невалидным JSON. Верни ТОЛЬКО валидный JSON.",
                                      task=task, context=context or {})
                with self._lock:
                    self.stats.calls += 1
                data = parse_json(text)
                if cache:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(text, encoding="utf-8")
                return data
            except json.JSONDecodeError as e:
                last_err = e
                with self._lock:
                    self.stats.retries += 1
                continue
            except RetryableError as e:
                last_err = e
                with self._lock:
                    self.stats.retries += 1
                # модель перегружена (503) или не отвечает — после LLM_FALLBACK_AFTER повторов переходим на резервную
                if attempt >= int(os.getenv("LLM_FALLBACK_AFTER", "3")) and self.fallback_models and ("503" in str(e) or "сетев" in str(e)):
                    if self._switch(f"{e}"):
                        print(f"  [llm] модель перегружена — переключаюсь на резервную {self.model}", flush=True)
                    continue
                wait = e.retry_after if e.retry_after else min(60.0, 2.0 * (2 ** attempt))
                max_wait = float(os.getenv("LLM_MAX_WAIT", "180"))
                # квота модели исчерпана (429 с долгой задержкой или 429 подряд) — сразу на резервную модель
                if self.fallback_models and "429" in str(e) and (wait > max_wait or attempt >= 2):
                    if self._switch(f"квота: {e}"):
                        print(f"  [llm] квота исчерпана — переключаюсь на резервную модель {self.model}", flush=True)
                    continue
                if attempt >= self.max_retries:
                    break
                if wait > max_wait:
                    # 429 с задержкой в часы = исчерпана дневная квота: ждать бессмысленно
                    hours = wait / 3600
                    msg = (f"Квота модели {self.model} исчерпана (API просит подождать ≈{hours:.1f} ч). "
                           "Уже полученные ответы сохранены в кэше — повторный запуск продолжит с того же места. "
                           "Варианты: дождаться сброса квоты, сменить модель (GEMINI_MODEL) или ключ, "
                           "увеличить LLM_BATCH_SIZE, чтобы тратить меньше запросов.")
                    self.stats.errors.append(msg)
                    raise LLMFatalError(msg)
                print(f"  [llm] {e} — повтор через {wait:.0f} с (попытка {attempt + 1}/{self.max_retries})", flush=True)
                time.sleep(wait)
        msg = f"LLM не ответил после {self.max_retries} повторов: {last_err}"
        self.stats.errors.append(msg)
        raise LLMError(msg)

    def _switch(self, why: str) -> bool:
        """Переход на резервную модель (один раз на событие, даже если упали несколько параллельных запросов)."""
        with self._lock:
            if not self.fallback_models:
                return False
            old, self.model = self.model, self.fallback_models.pop(0)
            self.stats.switches.append(f"{old} → {self.model} ({why})")
            return True

    def _cache_path(self, system: str, prompt: str) -> Path | None:
        """Кэш ответов по хэшу (провайдер + модель + температура + промпт): повторный прогон не тратит квоту."""
        if self.provider in ("mock", "rules") or os.getenv("LLM_CACHE", "1").strip() in ("0", "false", "no", ""):
            return None
        h = hashlib.sha256(f"{self.provider}|{self.model}|{getattr(self, 'temperature', '')}|{system}|{prompt}".encode()).hexdigest()
        base = Path(os.getenv("LLM_CACHE_DIR", Path(__file__).resolve().parent.parent / ".cache" / "llm"))
        return base / f"{h}.json"

    def _throttle(self):
        """Старты запросов разносятся на min_interval — общий слот для всех потоков (LLM_RPM соблюдается и параллельно)."""
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            start = max(now, self._last_call + self.min_interval)
            self._last_call = start
        if start > now:
            time.sleep(start - now)

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
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        data = json.loads(repair_json(t))  # если и ремонт не помог — исключение уйдёт в повтор запроса
    if isinstance(data, list):
        data = {"items": data}
    return data


def repair_json(t: str) -> str:
    """Авто-ремонт типичных дефектов JSON от модели: висячие запятые и обрезанный хвост (незакрытые строки/скобки)."""
    t = re.sub(r",\s*([}\]])", r"\1", t.strip())
    stack, in_str, esc = [], False, False
    for ch in t:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    if in_str:
        t += '"'
    t = re.sub(r",\s*$", "", t)
    t = re.sub(r':\s*$', ': null', t)
    return t + "".join(reversed(stack))


def _retry_delay_from_body(body: str) -> float | None:
    m = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', body)
    if m:
        return float(m.group(1)) + 1
    return None


class GeminiLLM(BaseLLM):
    provider = "gemini"

    def __init__(self, api_key: str, model: str, base_url: str | None = None, temperature: float = 0.0,
                 fallback: list[str] | None = None, **kw):
        super().__init__(**kw)
        if not api_key:
            raise LLMError("Не задан GEMINI_API_KEY. Получите ключ на https://aistudio.google.com/apikey и положите в .env")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.base_url = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self.fallback_models = [m for m in (fallback or []) if m and m != model]
        self.schema_off: dict[str, bool] = {}  # модели, не принявшие responseSchema
        # GEMINI_API=openai — OpenAI-совместимый эндпоинт Gemini (ключ в Authorization: Bearer): нужен, когда ключ
        # подставляет прокси облачной среды, а заголовок x-goog-api-key недоступен. Модели и резервы — те же.
        self.api_style = os.getenv("GEMINI_API", "native").strip().lower()

    def _call_openai(self, system, prompt):
        body = {"model": self.model, "temperature": self.temperature, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        try:
            r = requests.post(f"{self.base_url}/openai/chat/completions", json=body,
                              headers={"Authorization": f"Bearer {self.api_key}"}, timeout=self.timeout)
        except requests.RequestException as e:
            raise RetryableError(f"сетевая ошибка: {e}")
        if r.status_code in (429, 500, 502, 503, 504):
            raise RetryableError(f"HTTP {r.status_code}", _retry_delay_from_body(r.text))
        if r.status_code != 200:
            raise LLMFatalError(f"Gemini HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        u = data.get("usage", {})
        self.stats.prompt_tokens += u.get("prompt_tokens", 0)
        self.stats.output_tokens += u.get("completion_tokens", 0)
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        if not text.strip():
            raise RetryableError("пустой текст ответа")
        return text

    def _call(self, system, prompt, *, task, context):
        if self.api_style == "openai":
            return self._call_openai(system, prompt)
        url = f"{self.base_url}/models/{self.model}:generateContent"
        gen = {"temperature": self.temperature, "responseMimeType": "application/json"}
        from .schemas import SCHEMAS

        use_schema = task in SCHEMAS and os.getenv("GEMINI_RESPONSE_SCHEMA", "1") != "0" and not self.schema_off.get(self.model)
        if use_schema:
            gen["responseSchema"] = SCHEMAS[task]  # официальная схема ответа (R3)
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen,
        }
        try:
            r = requests.post(url, json=body, headers={"x-goog-api-key": self.api_key}, timeout=self.timeout)
        except requests.RequestException as e:
            raise RetryableError(f"сетевая ошибка: {e}")
        if r.status_code in (429, 500, 502, 503, 504):
            raise RetryableError(f"HTTP {r.status_code}", _retry_delay_from_body(r.text))
        if r.status_code == 400 and use_schema and "schema" in r.text.lower():
            # модель не принимает схему — откат на обычный JSON-режим (+ ремонт), повтор без задержки
            self.schema_off[self.model] = True
            raise RetryableError("схема ответа не поддерживается моделью — повтор в JSON-режиме", 0.01)
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


class AnthropicLLM(BaseLLM):
    """Claude через Anthropic Messages API (ANTHROPIC_API_KEY или CLAUDE_API_KEY). Ответ — JSON по промпту этапа."""
    provider = "anthropic"

    def __init__(self, api_key: str, model: str, temperature: float = 0.0, max_tokens: int = 16000,
                 base_url: str = "https://api.anthropic.com", **kw):
        super().__init__(**kw)
        if not api_key:
            raise LLMError("Не задан ANTHROPIC_API_KEY (или CLAUDE_API_KEY). Ключ: https://platform.claude.com/settings/keys")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.base_url = base_url.rstrip("/")

    def _call(self, system, prompt, *, task, context):
        body = {"model": self.model, "max_tokens": self.max_tokens, "temperature": self.temperature,
                "system": system + "\n\nОтвечай только валидным JSON без пояснений и без Markdown-блоков.",
                "messages": [{"role": "user", "content": prompt}]}
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        try:
            r = requests.post(f"{self.base_url}/v1/messages", json=body, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise RetryableError(f"сетевая ошибка: {e}")
        if r.status_code in (429, 500, 502, 503, 504, 529):
            ra = r.headers.get("retry-after")
            raise RetryableError(f"Anthropic HTTP {r.status_code}", float(ra) if ra and ra.replace(".", "", 1).isdigit() else None)
        if r.status_code != 200:
            raise LLMFatalError(f"Anthropic HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        u = data.get("usage", {})
        self.stats.prompt_tokens += u.get("input_tokens", 0)
        self.stats.output_tokens += u.get("output_tokens", 0)
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        if data.get("stop_reason") == "max_tokens":
            raise json.JSONDecodeError("ответ обрезан по max_tokens", text, len(text))
        return text


def _env_key(name: str) -> str:
    """Ключ из .env: проверяем, что это не заглушка вида «ваш_ключ» (HTTP-заголовки допускают только ASCII)."""
    v = os.getenv(name, "").strip().strip('"').strip("'")
    if v and not v.isascii():
        raise LLMError(f"{name} в .env содержит не-латинские символы — похоже, там осталась заглушка вместо ключа. "
                       f"Вставьте настоящий ключ (например, GEMINI_API_KEY=AIza...).")
    return v


def _min_interval() -> float:
    """Пауза между запросами: LLM_MIN_INTERVAL (с) или лимит LLM_RPM (запросов в минуту) — берётся более строгое."""
    iv = float(os.getenv("LLM_MIN_INTERVAL", "6"))
    rpm = os.getenv("LLM_RPM", "").strip()
    if rpm:
        try:
            iv = max(iv, 60.0 / max(1.0, float(rpm)))
        except ValueError:
            pass
    return iv


def default_provider() -> str:
    """LLM_PROVIDER из .env; если не задан — по найденному ключу (Gemini, затем Claude, OpenRouter, OpenAI)."""
    v = os.getenv("LLM_PROVIDER", "").strip().lower()
    if v:
        return v
    for name, prov in (("GEMINI_API_KEY", "gemini"), ("ANTHROPIC_API_KEY", "anthropic"), ("CLAUDE_API_KEY", "anthropic"),
                       ("OPENROUTER_API_KEY", "openrouter"), ("OPENAI_API_KEY", "openai")):
        if os.getenv(name, "").strip():
            return prov
    return "gemini"


def build_llm_from_env() -> BaseLLM:
    provider = default_provider()
    common = dict(
        min_interval=_min_interval(),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "6")),
        timeout=float(os.getenv("LLM_TIMEOUT", "180")),
    )
    temperature = float(os.getenv("LLM_TEMPERATURE", "0"))
    if provider == "gemini":
        return GeminiLLM(
            api_key=_env_key("GEMINI_API_KEY"),
            model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip(),
            base_url=os.getenv("GEMINI_BASE_URL") or None,
            fallback=[m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite").split(",")],
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
    if provider in ("anthropic", "claude"):
        return AnthropicLLM(
            api_key=_env_key("ANTHROPIC_API_KEY") or _env_key("CLAUDE_API_KEY"),
            model=os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5").strip(),
            base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").strip(),
            max_tokens=int(os.getenv("ANTHROPIC_MAX_TOKENS", "16000")),
            temperature=temperature,
            **{**common, "min_interval": float(os.getenv("LLM_MIN_INTERVAL", "0"))},
        )
    if provider == "openrouter":  # один ключ к Claude, Gemini, DeepSeek, GPT (OpenAI-совместимый API)
        llm = OpenAICompatLLM(
            api_key=_env_key("OPENROUTER_API_KEY"),
            model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-opus-5.5").strip(),
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip(),
            temperature=temperature,
            **common,
        )
        llm.provider = "openrouter"
        return llm
    if provider == "ollama":  # локально, без ключа и без интернета
        llm = OpenAICompatLLM(
            api_key="", model=os.getenv("OLLAMA_MODEL", os.getenv("OFFLINE_MODEL", "qwen2.5:14b")).strip(),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").strip(),
            temperature=temperature, **{**common, "min_interval": 0.0},
        )
        llm.provider = "ollama"
        return llm
    if provider == "mock":
        from .mock_llm import MockLLM

        return MockLLM()
    if provider == "rules":  # без модели: только детерминированные проверки (квота исчерпана / нет сети)
        from .rules_llm import RulesOnlyLLM

        return RulesOnlyLLM()
    raise LLMError(f"Неизвестный LLM_PROVIDER={provider!r}. Допустимо: gemini, anthropic, openrouter, openai, ollama, rules, mock")
