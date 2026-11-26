"""Критик-агент: второй проход модели по найденным замечаниям и расчёт уверенности.

Модель получает пакет замечаний (с цитатами и текстом требований) и для каждого решает:
keep — подтвердить, drop — отклонить (ложное срабатывание), downgrade — понизить серьёзность.
Отклонённые замечания не удаляются бесследно: они уходят в приложение отчёта.

Уверенность:
- high   — замечание подтверждено критиком и при этом найдено и моделью, и правилом (или тест-пробой);
- medium — подтверждено критиком;
- low    — критик не запускался или не вернул вердикт.
"""
from __future__ import annotations

import json

from .checker import ReviewResult
from .criteria import criterion_name
from .llm import BaseLLM, LLMError, LLMFatalError

CRITIC_BATCH = 40
DOWN = {"critical": "major", "major": "minor", "minor": "minor"}

SYSTEM_CRITIC = """Ты — независимый строгий рецензент (критик) результатов ревью требований.
Тебе дают замечания, которые нашёл другой ревьюер, вместе с текстом требования и дословной цитатой.
Для КАЖДОГО замечания реши:
- "keep" — замечание верное и важное;
- "downgrade" — замечание верное, но серьёзность завышена;
- "drop" — замечание ошибочное: проблемы в цитате нет, термин определён в документе, придирка без пользы.
Не добавляй новых замечаний. Будь объективен: отклоняй только явно ложные.
Пиши на русском. Верни ТОЛЬКО JSON: {"verdicts":[{"n":1,"verdict":"keep|downgrade|drop","reason":"кратко, почему"}]}"""


def _collect(rv: ReviewResult) -> list[tuple[str, object, object]]:
    items = []
    for rr in rv.req_results:
        for f in rr.findings:
            items.append(("req", f, rr))
    for f in rv.set_findings:
        items.append(("set", f, None))
    return items


def _protected(f) -> bool:
    """Объективные факты критик не отклоняет: невозможность теста и числовые противоречия, найденные правилом."""
    return f.source == "тест-проба" or (getattr(f, "values", None) and "правило" in f.source)


def run_critic(rv: ReviewResult, llm: BaseLLM, log=print, only_critical: bool = False) -> None:
    """only_critical=True — self-consistency для профиля fast: второй проход только по критичным замечаниям (1 запрос)."""
    all_items = _collect(rv)
    items = [it for it in all_items if not only_critical or it[1].severity == "critical"]
    rv.critic_scope = "critical" if only_critical else "all"
    if not items:
        rv.critic_used = True
        return
    by_rid = {r.rid: r for r in rv.split.requirements}
    verdicts: dict[int, dict] = {}
    batches = [items[i:i + CRITIC_BATCH] for i in range(0, len(items), CRITIC_BATCH)]
    for bi, batch in enumerate(batches):
        log(f"  критик: пакет {bi + 1}/{len(batches)} ({len(batch)} замечаний)")
        payload = []
        for k, (kind, f, rr) in enumerate(batch):
            n = bi * CRITIC_BATCH + k + 1
            if kind == "req":
                ctx = rr.req.text
                quote = f.quote
            else:
                ctx = " | ".join(f"{ref.req_id}: {by_rid[ref.req_id].text if ref.req_id in by_rid else ref.quote}" for ref in f.refs)
                quote = " / ".join(ref.quote for ref in f.refs)
            payload.append({"n": n, "criterion": criterion_name(f.criterion), "severity": f.severity,
                            "requirement_text": ctx, "quote": quote, "problem": f.problem})
        try:
            data = llm.generate_json(SYSTEM_CRITIC, "ЗАМЕЧАНИЯ (JSON):\n" + json.dumps(payload, ensure_ascii=False, indent=1),
                                     task="critic", context={"items": payload})
        except LLMFatalError:
            raise
        except LLMError as e:
            rv.notes.append(f"Критик не ответил ({e}); уверенность части замечаний не оценена.")
            continue
        for v in data.get("verdicts", []) or []:
            try:
                verdicts[int(v.get("n"))] = v
            except (TypeError, ValueError):
                continue

    rv.critic_used = True
    keep_req: dict[int, list] = {}
    keep_set = []
    sent = {id(it[1]): n for n, it in enumerate(items, start=1)}
    for kind, f, rr in all_items:
        if id(f) not in sent:  # не отправлялось критику (only_critical) — оставляем как есть
            (keep_req.setdefault(id(rr), []) if kind == "req" else keep_set).append(f)
            continue
        v = verdicts.get(sent[id(f)])
        verdict = str((v or {}).get("verdict", "")).lower()
        reason = str((v or {}).get("reason", "") or "").strip()
        if verdict == "drop" and not _protected(f):
            where = rr.req.rid if kind == "req" else "набор"
            quote = f.quote if kind == "req" else " / ".join(r.quote for r in f.refs)
            rv.rejected.append({"where": where, "quote": quote, "problem": f.problem, "reason": reason or "отклонено критиком"})
            continue
        if verdict == "downgrade":
            f.severity = DOWN[f.severity]
        f.critic_note = reason
        if not v:
            f.confidence = "low"
        elif "+" in f.source or _protected(f):
            f.confidence = "high"
        else:
            f.confidence = "medium"
        if kind == "req":
            keep_req.setdefault(id(rr), []).append(f)
        else:
            keep_set.append(f)
    order = {"critical": 0, "major": 1, "minor": 2}
    for rr in rv.req_results:
        rr.findings = sorted(keep_req.get(id(rr), []), key=lambda f: order[f.severity])
    rv.set_findings = sorted(keep_set, key=lambda f: order[f.severity])


def default_confidence(rv: ReviewResult) -> None:
    """Без критика: уверенность по числу независимых источников."""
    for rr in rv.req_results:
        for f in rr.findings:
            if not f.confidence:
                f.confidence = "medium" if ("+" in f.source or f.source == "тест-проба") else "low"
    for f in rv.set_findings:
        if not f.confidence:
            f.confidence = "high" if _protected(f) else "medium" if "правило" in f.source else "low"


# Числовая уверенность 0–1 (для JSON/UI): источник + вердикт критика
def confidence_score(f) -> float:
    if f.source == "тест-проба":
        return 0.95
    if getattr(f, "values", None) and "правило" in f.source:
        return 0.95 if "LLM" in f.source else 0.9
    base = {"high": 0.9, "medium": 0.75, "low": 0.55}.get(f.confidence, 0.55)
    if f.source in ("правило", "домен") and f.confidence != "high":
        base = 0.6
    return base
