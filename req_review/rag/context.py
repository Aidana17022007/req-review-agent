"""RAG для длинных документов (R1): вместо всего текста — глоссарий, оглавление и ближайшие фрагменты.

RAG_CONTEXT=auto (по умолчанию): включается, если документ длиннее RAG_CONTEXT_THRESHOLD символов (15 000).
RAG_CONTEXT=off — всегда полный текст (как раньше). RAG_CONTEXT=on — всегда выборка (для отладки).
"""
from __future__ import annotations

import os
import re

from .embed import embedder_from_env
from .index import Index, build_index

GLOSSARY_RE = re.compile(r"термин|определени|глоссари|сокращени|glossary", re.IGNORECASE)


def mode_for(doc) -> str:
    m = os.getenv("RAG_CONTEXT", "auto").strip().lower()
    if os.getenv("RAG", "on").strip().lower() in ("off", "0", "false", "no") or m == "off":
        return "full"
    if m == "on":
        return "rag"
    return "rag" if len(doc.text) > int(os.getenv("RAG_CONTEXT_THRESHOLD", "15000")) else "full"


def _doc_index(doc) -> Index:
    idx = getattr(doc, "_rag_index", None)
    if idx is None:
        idx = build_index([(doc.path.name, doc.text, {"kind": "document"})], embedder_from_env(), "document")
        doc._rag_index = idx
    return idx


def outline(doc, limit: int = 4000) -> str:
    """Оглавление + раздел терминов: то, что нужно модели в любом запросе."""
    heads, gloss, in_g = [], [], False
    for line in doc.lines:
        t = line.text.strip()
        if t.startswith("#"):
            heads.append(t)
            in_g = bool(GLOSSARY_RE.search(t))
        elif in_g and t:
            gloss.append(t)
    out = "ОГЛАВЛЕНИЕ:\n" + "\n".join(heads)
    if gloss:
        out += "\n\nТЕРМИНЫ:\n" + "\n".join(gloss)
    return out[:limit]


def context_for(doc, queries: list[str], k: int = 8) -> str:
    """Контекст для пакета требований: оглавление, термины и top-k фрагментов документа по каждому требованию."""
    idx = _doc_index(doc)
    seen, frags = set(), []
    for q in queries:
        for c, _ in idx.search(q, k=3):
            if c.id not in seen:
                seen.add(c.id)
                frags.append(c)
        if len(frags) >= k * 2:
            break
    body = "\n\n".join(f"[{c.section}] {c.text}" for c in frags[: k * 2])
    return f"{outline(doc)}\n\nРЕЛЕВАНТНЫЕ ФРАГМЕНТЫ ДОКУМЕНТА (RAG):\n{body}"


def record(doc, mode: str, prompt_chars: int) -> None:
    st = getattr(doc, "_ctx_stats", None) or {"mode": mode, "prompt_chars": []}
    st["mode"] = mode
    st["prompt_chars"].append(prompt_chars)
    doc._ctx_stats = st
