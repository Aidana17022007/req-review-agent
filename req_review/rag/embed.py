"""Эмбеддинги для RAG: Gemini (batchEmbedContents) с кэшем по хэшу текста; mock — детерминированный хэш-вектор.

Если эмбеддинги недоступны (нет ключа, нет сети, лимит) — возвращается None, и поиск работает только по BM25.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path

from .lexical import tokens

ROOT = Path(__file__).resolve().parent.parent.parent
MOCK_DIM = 256


def _cache_dir(model: str) -> Path:
    return Path(os.getenv("RAG_CACHE_DIR", ROOT / ".cache" / "emb")) / model.replace("/", "_")


def mock_embed(text: str) -> list[float]:
    """Хэширующий вектор по токенам: похожие тексты → близкие векторы; без сети, детерминированно (для тестов)."""
    v = [0.0] * MOCK_DIM
    for t in tokens(text):
        h = int(hashlib.md5(t.encode()).hexdigest(), 16)
        v[h % MOCK_DIM] += 1.0 if (h >> 8) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class Embedder:
    def __init__(self, provider: str, model: str = "", api_key: str = ""):
        self.provider, self.model, self.api_key = provider, model, api_key
        self.calls = 0

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}" if self.model else self.provider

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        if self.provider == "mock":
            return [mock_embed(t) for t in texts]
        if self.provider != "gemini":
            return None
        out: list[list[float] | None] = [None] * len(texts)
        todo = []
        cdir = _cache_dir(self.model)
        for i, t in enumerate(texts):
            p = cdir / (hashlib.sha256(t.encode()).hexdigest() + ".json")
            if p.exists():
                out[i] = json.loads(p.read_text(encoding="utf-8"))
            else:
                todo.append(i)
        for b in range(0, len(todo), 64):
            idx = todo[b:b + 64]
            vecs = self._gemini([texts[i] for i in idx])
            if vecs is None:
                return None  # нет сети / лимит — работаем на BM25
            cdir.mkdir(parents=True, exist_ok=True)
            for i, v in zip(idx, vecs):
                out[i] = v
                (cdir / (hashlib.sha256(texts[i].encode()).hexdigest() + ".json")).write_text(json.dumps(v), encoding="utf-8")
        return out  # type: ignore[return-value]

    def _gemini(self, batch: list[str]) -> list[list[float]] | None:
        import requests

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:batchEmbedContents"
        body = {"requests": [{"model": f"models/{self.model}", "content": {"parts": [{"text": t[:8000]}]}} for t in batch]}
        for attempt in range(3):
            try:
                r = requests.post(url, json=body, headers={"x-goog-api-key": self.api_key}, timeout=60)
            except requests.RequestException:
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 200:
                self.calls += 1
                return [e["values"] for e in r.json().get("embeddings", [])]
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 * (attempt + 1))
                continue
            return None
        return None


def embedder_from_env() -> Embedder:
    """RAG_EMBED: gemini | mock | none. По умолчанию — как LLM_PROVIDER (gemini с ключом, mock в тестах), иначе none."""
    choice = os.getenv("RAG_EMBED", "").strip().lower()
    llm = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not choice:
        choice = "mock" if llm == "mock" else ("gemini" if llm == "gemini" and key else "none")
    if choice == "gemini" and key:
        return Embedder("gemini", os.getenv("RAG_EMBED_MODEL", "gemini-embedding-001").strip(), key)
    if choice == "mock":
        return Embedder("mock", "hash-256")
    return Embedder("none")
