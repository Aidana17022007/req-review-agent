"""Критик-агент: второй проход модели по найденным замечаниям и расчёт уверенности.

Модель получает пакет замечаний (с цитатами и текстом требований) и для каждого решает:
keep — подтвердить, drop — отклонить (ложное срабатывание), downgrade — понизить серьёзность,
merge — объединить с другим замечанием о той же проблеме (правило + LLM + проход полноты нашли одно и то же).
При проверке всех замечаний (профили full/deep) критик также калибрует серьёзность по единой шкале.
Отклонённые и объединённые замечания не удаляются бесследно: они уходят в приложение отчёта («дубль S-xx»).

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
Тебе дают замечания, которые нашли другие проходы (правила, модель, проход полноты), вместе с текстом требования и
дословной цитатой. Для КАЖДОГО замечания реши:
- "keep" — замечание верное и важное;
- "downgrade" — замечание верное, но серьёзность завышена;
- "drop" — замечание ошибочное: проблемы в цитате нет, термин определён в документе, придирка без пользы;
- "merge" — замечание к НАБОРУ требований (cross-requirement) повторяет другое замечание к набору из списка (та же
  проблема, пусть другими словами или с другими цитатами): укажи "into" — номер n замечания, которое остаётся (более
  полное и точное). Не объединяй разные проблемы и не объединяй замечания к отдельным требованиям.
Калибровка серьёзности ("severity", для keep и merge-цели): critical — функцию нельзя реализовать или проверить
однозначно (противоречие правил, нет метода или контракта интеграции, ошибка под успешным кодом); major — нужно
исправить до написания тест-кейсов (пропуск сценария, неизмеримость, неопределённый термин); minor — оформление.
Не добавляй новых замечаний. Будь объективен: отклоняй только явно ложные.
Пиши на русском. Верни ТОЛЬКО JSON: {"verdicts":[{"n":1,"verdict":"keep|downgrade|drop|merge","into":null,
"severity":"critical|major|minor","reason":"кратко, почему"}]}"""

ORDER = {"critical": 0, "major": 1, "minor": 2}


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
            if not isinstance(v, dict):  # ответ модели не по схеме — пропускаем элемент
                continue
            try:
                verdicts[int(v.get("n"))] = v
            except (TypeError, ValueError):
                continue

    rv.critic_used = True
    calibrate = not only_critical
    sent = {id(it[1]): n for n, it in enumerate(items, start=1)}
    by_n = {n: it for n, it in enumerate(items, start=1)}
    # дубли: n → into (цель должна существовать, сама не объединяться и не отклоняться; объективные факты не поглощаются)
    merges: dict[int, int] = {}
    for n, v in verdicts.items():
        if str(v.get("verdict", "")).lower() != "merge":
            continue
        try:
            into = int(v.get("into"))
        except (TypeError, ValueError):
            continue
        tv = str((verdicts.get(into) or {}).get("verdict", "")).lower()
        # только «набор → набор»: дубли одной проблемы из разных проходов (правило, модель, проход полноты).
        # Замечания к требованиям не объединяются — у каждого своё требование и свой критерий (иначе теряется
        # трассировка «требование × критерий»)
        if (n in by_n and into in by_n and into != n and tv not in ("merge", "drop") and not _protected(by_n[n][1])
                and by_n[n][0] == "set" and by_n[into][0] == "set"):
            merges[n] = into
    keep_req: dict[int, list] = {}
    keep_set = []
    merged: list[tuple[object, object, str]] = []  # (поглощённое замечание, цель, причина)
    for kind, f, rr in all_items:
        if id(f) not in sent:  # не отправлялось критику (only_critical) — оставляем как есть
            (keep_req.setdefault(id(rr), []) if kind == "req" else keep_set).append(f)
            continue
        n = sent[id(f)]
        v = verdicts.get(n)
        verdict = str((v or {}).get("verdict", "")).lower()
        reason = str((v or {}).get("reason", "") or "").strip()
        if n in merges:
            tk, tf, trr = by_n[merges[n]]
            if ORDER[f.severity] < ORDER[tf.severity]:
                tf.severity = f.severity  # у объединённого — наибольшая серьёзность
            if f.source not in tf.source:
                tf.source = f"{tf.source}+{f.source}"  # независимые проходы подтвердили — уверенность выше
            merged.append((kind, f, rr, tf, reason))
            continue
        if verdict == "merge":  # некорректная ссылка «into» — оставляем как keep
            verdict = "keep"
        if verdict == "drop" and not _protected(f):
            where = rr.req.rid if kind == "req" else "набор"
            quote = f.quote if kind == "req" else " / ".join(r.quote for r in f.refs)
            rv.rejected.append({"where": where, "quote": quote, "problem": f.problem, "reason": reason or "отклонено критиком"})
            continue
        if verdict == "downgrade":
            f.severity = DOWN[f.severity]
        elif calibrate and verdict == "keep":
            sev = str((v or {}).get("severity", "")).lower()
            # правила выверены бенчмарком: калибровка может их повысить, но не понизить (понижение — только downgrade)
            if sev in ORDER and not _protected(f) and (f.source != "правило" or ORDER[sev] < ORDER[f.severity]):
                f.severity = sev
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
    for rr in rv.req_results:
        rr.findings = sorted(keep_req.get(id(rr), []), key=lambda f: ORDER[f.severity])
    rv.set_findings = sorted(keep_set, key=lambda f: ORDER[f.severity])
    # подписи целей — по итоговой нумерации (S-01… как в отчёте; у замечаний к требованию — R-xxx)
    sid = {id(f): f"S-{i:02d}" for i, f in enumerate(rv.set_findings, 1)}
    rid = {id(f): rr.req.rid for rr in rv.req_results for f in rr.findings}
    for kind, f, rr, tf, reason in merged:
        if "+" in tf.source:
            tf.confidence = "high"
        label = sid.get(id(tf)) or rid.get(id(tf)) or "?"
        where = rr.req.rid if kind == "req" else "набор"
        quote = f.quote if kind == "req" else " / ".join(r.quote for r in f.refs)
        rv.rejected.append({"where": where, "quote": quote, "problem": f.problem,
                            "reason": f"дубль {label}" + (f": {reason}" if reason else ""), "duplicate_of": label})
    rv.critic_merged = len(merged)


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
