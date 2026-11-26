"""Индекс RAG: фрагменты + (необязательно) векторы. Гибридный поиск: косинус + BM25, дедупликация, top-k.

Хранение — JSON в .cache/rag/<имя>.json (без numpy: базы знаний небольшие, лишняя зависимость не нужна).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict
from pathlib import Path

from .chunk import Chunk, chunk_text
from .embed import Embedder, embedder_from_env
from .lexical import BM25

ROOT = Path(__file__).resolve().parent.parent.parent
KB_DIR = ROOT / "kb"


def _cos(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da, db = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return num / (da * db) if da and db else 0.0


class Index:
    def __init__(self, chunks: list[Chunk], vectors: list[list[float]] | None = None, embedder: Embedder | None = None,
                 name: str = ""):
        self.chunks, self.vectors, self.embedder, self.name = chunks, vectors, embedder, name
        self.bm25 = BM25([f"{c.section} {c.text}" for c in chunks])

    @property
    def mode(self) -> str:
        return "гибрид (векторы + BM25)" if self.vectors else "BM25"

    def search(self, query: str, k: int = 5, kind: str | None = None, alpha: float = 0.55) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        bm = self.bm25.scores(query)
        mx = max(bm) or 1.0
        bm = [s / mx for s in bm]
        vec = [0.0] * len(self.chunks)
        if self.vectors and self.embedder:
            q = self.embedder.embed([query])
            if q and q[0]:
                vec = [max(0.0, _cos(q[0], v)) for v in self.vectors]
        score = [alpha * v + (1 - alpha) * b if self.vectors else b for v, b in zip(vec, bm)]
        order = sorted(range(len(self.chunks)), key=lambda i: -score[i])
        out, seen = [], set()
        for i in order:
            c = self.chunks[i]
            if score[i] <= 0 or (kind and c.meta.get("kind") != kind):
                continue
            key = c.text[:80]
            if key in seen:
                continue
            seen.add(key)
            out.append((c, round(score[i], 4)))
            if len(out) >= k:
                break
        return out

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"name": self.name, "embedder": self.embedder.label if self.embedder else "none",
                                    "chunks": [asdict(c) for c in self.chunks], "vectors": self.vectors},
                                   ensure_ascii=False), encoding="utf-8")


def build_index(texts: list[tuple[str, str, dict]], embedder: Embedder | None = None, name: str = "") -> Index:
    """texts: [(source, text, extra_meta)] → Index."""
    chunks: list[Chunk] = []
    for source, text, extra in texts:
        for c in chunk_text(text, source):
            c.meta.update(extra)
            chunks.append(c)
    vectors = None
    if embedder is not None and embedder.provider != "none" and chunks:
        vectors = embedder.embed([f"{c.section}. {c.text}" for c in chunks])
    return Index(chunks, vectors, embedder, name)


def kb_files(kb_dir: Path = KB_DIR) -> list[Path]:
    return sorted(p for p in kb_dir.rglob("*.md") if p.name.lower() != "readme.md")


def build_kb(kb_dir: Path = KB_DIR, embedder: Embedder | None = None) -> Index:
    texts = []
    for p in kb_files(kb_dir):
        kind = p.parent.name  # standards | law_kz | patterns
        texts.append((str(p.relative_to(kb_dir)).replace("\\", "/"), p.read_text(encoding="utf-8"), {"kind": kind}))
    return build_index(texts, embedder, "kb")


_KB: dict[str, Index | None] = {}


def rag_enabled() -> bool:
    return os.getenv("RAG", "on").strip().lower() not in ("off", "0", "false", "no")


def get_kb(kb_dir: Path = KB_DIR) -> Index | None:
    """База знаний (кэш в памяти и на диске по хэшу содержимого kb/). None — если RAG выключен или kb/ нет."""
    if not rag_enabled() or not kb_dir.exists():
        return None
    files = kb_files(kb_dir)
    if not files:
        return None
    emb = embedder_from_env()
    h = hashlib.sha256((emb.label + "".join(p.read_text(encoding="utf-8") for p in files)).encode()).hexdigest()[:16]
    if h in _KB:
        return _KB[h]
    cache = Path(os.getenv("RAG_CACHE_DIR", ROOT / ".cache")) / "rag" / f"kb-{h}.json"
    if cache.exists():
        d = json.loads(cache.read_text(encoding="utf-8"))
        idx = Index([Chunk(**c) for c in d["chunks"]], d.get("vectors"), emb, "kb")
    else:
        idx = build_kb(kb_dir, emb)
        try:
            idx.save(cache)
        except OSError:
            pass
    _KB[h] = idx
    return idx
