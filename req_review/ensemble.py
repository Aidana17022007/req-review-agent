"""Ансамбль двух моделей (v7): два независимых прогона проверки, объединение подтверждённых замечаний.

Каждая модель проходит весь конвейер (свои цитаты сверяются с документом, критик, проходы набора). Объединение:
- к требованию — одно и то же, если совпадают требование (тот же текст), критерий и цитаты перекрываются;
- к набору — одно и то же, если совпадают вид замечания и множество требований в ссылках (или цитаты перекрываются).
Совпавшее помечается «обе» (две модели независимо нашли одно и то же — уверенность высокая), остальное — «модель A» /
«модель B»; замечания детерминированных правил — «правило» (одинаковы в обоих прогонах). Новых обращений к модели
объединение не делает: оно работает только с уже подтверждёнными замечаниями.
"""
from __future__ import annotations

import os
import re
from contextlib import contextmanager

from .verify import norm

MODEL_ENV = {"gemini": "GEMINI_MODEL", "anthropic": "ANTHROPIC_MODEL", "claude": "ANTHROPIC_MODEL",
             "openrouter": "OPENROUTER_MODEL", "openai": "OPENAI_MODEL", "openai-compatible": "OPENAI_MODEL",
             "ollama": "OLLAMA_MODEL"}


def parse(spec: str | None) -> list[str]:
    models = [m.strip() for m in (spec or "").split(",") if m.strip()]
    return models if len(models) >= 2 else []


@contextmanager
def model_env(model: str):
    """Временно подставить модель в переменную окружения провайдера (CLI работает в одном потоке).
    v13: «провайдер:модель» (например «openai:deepseek-chat») — ансамбль моделей РАЗНЫХ провайдеров: на время прогона
    меняется и LLM_PROVIDER (ключи и адреса берутся из .env этого провайдера)."""
    from .llm import default_provider

    provider = None
    if ":" in model and model.split(":", 1)[0] in MODEL_ENV:
        provider, model = model.split(":", 1)
    key = MODEL_ENV.get(provider or default_provider(), "GEMINI_MODEL")
    saved = {k: os.environ.get(k) for k in (key, "LLM_PROVIDER")}
    os.environ[key] = model
    if provider:
        os.environ["LLM_PROVIDER"] = provider
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _words(s: str) -> set[str]:
    return set(re.findall(r"\w{3,}", norm(s or "")))


def _overlap(a: str, b: str) -> bool:
    na, nb = norm(a or ""), norm(b or "")
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.6


def _is_rule(src: str) -> bool:
    return "LLM" not in src and "модел" not in src


def merge(rv_a, rv_b, label_a: str = "модель A", label_b: str = "модель B") -> dict:
    """Добавляет в rv_a замечания rv_b, которых там нет; проставляет f.ensemble. Возвращает статистику."""
    st = {"a": 0, "b_added": 0, "both": 0, "rules": 0}
    by_text_b = {rr.req.text: rr for rr in rv_b.req_results}
    for rr in rv_a.req_results:
        rb = by_text_b.get(rr.req.text)
        b_list = list(rb.findings) if rb else []
        for f in rr.findings:
            if _is_rule(f.source):
                f.ensemble = "правило"
                st["rules"] += 1
                continue
            twin = next((g for g in b_list if g.criterion == f.criterion and _overlap(f.quote, g.quote)), None)
            if twin:
                b_list.remove(twin)
                f.ensemble = "обе"
                f.confidence = "high"
                st["both"] += 1
            else:
                f.ensemble = label_a
                st["a"] += 1
        for g in b_list:
            if _is_rule(g.source):
                continue
            if any(x.criterion == g.criterion and _overlap(x.quote, g.quote) for x in rr.findings):
                continue
            g.ensemble = label_b
            g.req_id = rr.req.rid
            rr.findings.append(g)
            st["b_added"] += 1
    # замечания к набору: rid в ссылках сопоставляем по тексту требования
    rid_b2a = {}
    by_text_a = {rr.req.text: rr.req.rid for rr in rv_a.req_results}
    for rr in rv_b.req_results:
        if rr.req.text in by_text_a:
            rid_b2a[rr.req.rid] = by_text_a[rr.req.text]

    def key(f, remap=None):
        ids = frozenset((remap or {}).get(r.req_id, r.req_id) for r in f.refs)
        return f.kind, ids

    b_set = list(rv_b.set_findings)
    for f in rv_a.set_findings:
        if _is_rule(f.source):
            f.ensemble = "правило"
            st["rules"] += 1
            continue
        kf = key(f)
        twin = next((g for g in b_set if not _is_rule(g.source) and
                     (key(g, rid_b2a) == kf or any(_overlap(x.quote, y.quote) for x in f.refs for y in g.refs))), None)
        if twin:
            b_set.remove(twin)
            f.ensemble = "обе"
            f.confidence = "high"
            st["both"] += 1
        else:
            f.ensemble = label_a
            st["a"] += 1
    for g in b_set:
        if _is_rule(g.source) or any(r.req_id != "DOC" and r.req_id not in rid_b2a for r in g.refs):
            continue  # правила уже есть в прогоне A; ссылки на требования, которых нет в A, не переносим
        for r in g.refs:
            r.req_id = rid_b2a.get(r.req_id, r.req_id)
        if any(key(x) == key(g) and x.kind == g.kind for x in rv_a.set_findings):
            continue
        g.ensemble = label_b
        rv_a.set_findings.append(g)
        st["b_added"] += 1
    rv_a.set_findings.sort(key=lambda f: {"critical": 0, "major": 1, "minor": 2}[f.severity])
    rv_a.dropped.extend(rv_b.dropped)
    return st


def refresh_depth(rv) -> None:
    """Пересчитать сводные поля глубины после объединения (без новых обращений к модели)."""
    from .depth import citation_audit, criteria_matrix, fix_plan, verdicts

    d = rv.depth or {}
    confirmed = sum(len(rr.findings) for rr in rv.req_results) + len(rv.set_findings)
    rs = d.get("review_stats") or {}
    rs.update({"confirmed": confirmed, "proposed": confirmed + len(rv.rejected) + len(rv.dropped),
               "unconfirmed_quotes": len(rv.dropped)})
    d.update({"review_stats": rs, "criteria_matrix": criteria_matrix(rv), "verdict": verdicts(rv),
              "fix_plan": fix_plan(rv), "citation_audit": citation_audit(rv)})
    rv.depth = d
