"""v6: узкие проходы модели (один класс дефектов на запрос) и self-consistency проверки требований.

Маленькие модели внимательнее, когда в запросе один вопрос. Каждый узкий проход — отдельная задача (task) со своей
JSON-схемой; запускается, только если в документе есть к чему его применить (числа, API, приёмка, НФТ). Цитаты
проверяются так же, как у прохода полноты (verify.quote_in), повторы уже найденного не добавляются.

Self-consistency: проверка требований повторяется с другой температурой; замечание модели к требованию остаётся,
только если его подтвердил второй проход (тот же или родственный критерий) или правило. Неподтверждённые
уходят в rejected с причиной — так снижается доля случайных замечаний.
"""
from __future__ import annotations

import os
import re

from .depth import _api_lines, llm_set_pass

_COMMON = """Верни только то, чего в документе НЕТ или что определено неоднозначно, и только если это мешает
реализовать или протестировать функцию. Не повторяй уже найденное (список «УЖЕ НАЙДЕНО»). Не более 8 замечаний,
самые важные. В refs — 1–2 ДОСЛОВНЫЕ цитаты (3–15 слов, символ в символ): id требования из нарезки или "DOC" для
текста вне нарезки. problem — что именно не определено и к чему это приведёт; fix — конкретно, что дописать, с
примером формулировки. severity: critical — функцию нельзя реализовать однозначно; major — нужно до тест-кейсов;
minor — оформление. Пиши по-русски. Верни ТОЛЬКО JSON:
{"findings":[{"check":"<класс>","type":"gap","criterion":"set_complete|set_validatable|set_consistent|set_comprehensible",
"refs":[{"id":"R-001","quote":"..."}],"problem":"...","severity":"major","fix":"..."}]}"""

PASSES = {
    "focus_bounds": ("граничные значения", """Ты — тест-дизайнер. Пройди КАЖДОЕ правило с числом, диапазоном, сроком или
периодом и проверь граничные значения: включена ли граница (≤ или <), что при значении ровно на границе, на 1 меньше и
на 1 больше, при нуле и отрицательном значении, дробном значении для целого поля, округление, стык периодов (полночь,
конец месяца, часовой пояс). Замечание — только если поведение на границе не определено.
""" + _COMMON),
    "focus_api_negative": ("отрицательные сценарии API", """Ты — тест-дизайнер API. Для КАЖДОГО метода API проверь
отрицательные сценарии: отсутствует обязательный параметр, неверный тип или формат, значение вне диапазона, чужой или
несуществующий объект, истёкшая сессия, повторный запрос (идемпотентность), одновременное изменение, недоступность
зависимости, таймаут. Замечание — если не описан код ответа, тело ошибки или состояние данных после ошибки.
""" + _COMMON),
    "focus_acceptance": ("предусловия приёмки", """Ты — тест-аналитик. Для КАЖДОЙ строки критериев приёмки проверь:
задано ли полное начальное состояние (включена ли функция, текущие значения, что уже произошло в этом периоде), однозначен
ли ожидаемый результат, есть ли для каждого правила хотя бы один отрицательный и один граничный пример. Замечание — на
строку без предусловий или на правило без примеров.
""" + _COMMON),
    "focus_nfr": ("метрики НФТ", """Ты — инженер по производительности и надёжности. Для КАЖДОГО нефункционального
требования (скорость, доступность, нагрузка, хранение, безопасность) проверь: есть ли метрика и единицы, перцентиль
(95 %/99 %), нагрузка (запросов или событий в секунду), точка начала и конца измерения, период и окно, поведение при
недоступности зависимостей. Также отметь важные НФТ, которых нет совсем (доступность, журналирование, хранение данных).
""" + _COMMON),
}

_NUM_RULE = re.compile(r"\d[\d\s ]*(?:₸|тенге|тиын|%|сек|мин|час|дн|месяц|раз)|\bот\s+\d|\bдо\s+\d|не более|не менее|максимум|минимум", re.I)
_ACC = re.compile(r"критери\w* при[её]мк|исходн\w* услови|acceptance|given", re.I)
_NFR = re.compile(r"нефункциональн|производительн|доступност|non-?functional|\bнфт\b|\bnfr\b", re.I)


def applicable(task: str, split, doc) -> bool:
    if task == "focus_bounds":
        return sum(1 for r in split.requirements if _NUM_RULE.search(r.text)) >= 2
    if task == "focus_api_negative":
        return bool(_api_lines(doc))
    if task == "focus_acceptance":
        return any(_ACC.search(ln.text) for ln in doc.lines)
    if task == "focus_nfr":
        return any(_NFR.search(ln.text) for ln in doc.lines)
    return True


def focused_passes(split, doc, llm, dropped: list, found: list, log=print) -> dict:
    """Узкие проходы (по одному классу на запрос). Возвращает {task: добавлено замечаний}."""
    if os.getenv("REQLENS_FOCUSED", "1") == "0" or getattr(llm, "provider", "") == "rules":
        return {}
    stats = {}
    for task, (label, system) in PASSES.items():
        if not applicable(task, split, doc):
            continue
        log(f"  узкий проход: {label}")
        stats[task] = llm_set_pass(split, doc, llm, dropped, found, log, system=system, task=task, label=f"узкий проход «{label}»",
                                   source=f"LLM (узкий проход: {label})")
    return stats


# ---------------------------------------------------------------- self-consistency

def _overlap(a: str, b: str) -> bool:
    wa = {w for w in re.findall(r"[\wёЁ]{4,}", a.lower())}
    wb = {w for w in re.findall(r"[\wёЁ]{4,}", b.lower())}
    return bool(wa and wb) and len(wa & wb) >= max(1, min(len(wa), len(wb)) // 2)


# родственные критерии: одна и та же проблема часто записывается то как «непроверяемо», то как «неоднозначно»
_KIN = [{"verifiable", "unambiguous", "feasible"}, {"complete", "conforming"}, {"correct", "appropriate"}]


def _same_issue(f, g) -> bool:
    if g.criterion == f.criterion:
        return True
    kin = any(f.criterion in k and g.criterion in k for k in _KIN)
    return kin and _overlap(g.quote, f.quote)


def self_consistency(rv, llm, batch_size: int, log=print) -> dict:
    """Второй проход проверки требований с другой температурой (REQLENS_SC_TEMPERATURE, по умолчанию 0.4).
    Замечание модели остаётся, если второй проход нашёл на том же требовании тот же критерий (или родственный —
    с пересекающейся цитатой); замечания правил и тест-пробы не трогаются. Неподтверждённые — в rejected с причиной."""
    from .checker import LLMError, LLMFatalError, check_requirements

    if os.getenv("REQLENS_SELF_CHECK", "1") == "0" or getattr(llm, "provider", "") in ("rules", "mock"):
        return {}
    old = getattr(llm, "temperature", 0.0)
    llm.temperature = float(os.getenv("REQLENS_SC_TEMPERATURE", "0.4"))
    log(f"  самосогласованность: повторная проверка требований (температура {llm.temperature})")
    try:
        second = check_requirements([rr.req for rr in rv.req_results], rv.doc, llm, batch_size, [], log=lambda *a: None)
    except LLMFatalError:
        raise
    except LLMError as e:
        log(f"  самосогласованность пропущена ({e})")
        return {}
    finally:
        llm.temperature = old
    by_rid = {rr.req.rid: rr for rr in second}
    removed = confirmed = 0
    for rr in rv.req_results:
        other = by_rid.get(rr.req.rid)
        if other is None or not other.llm_checked:
            continue  # второй проход не вернул результат — не судим
        keep = []
        for f in rr.findings:
            if f.source != "LLM":  # правило, LLM + правило, тест-проба — уже подтверждены независимо
                keep.append(f)
                continue
            if any(_same_issue(f, g) for g in other.findings):
                f.source = "LLM ×2"
                confirmed += 1
                keep.append(f)
            else:
                rv.rejected.append({"where": rr.req.rid, "quote": f.quote, "problem": f.problem,
                                    "reason": "не подтверждено повторным проходом (самосогласованность)"})
                removed += 1
        rr.findings = keep
    log(f"  самосогласованность: подтверждено {confirmed}, снято {removed}")
    return {"confirmed": confirmed, "removed": removed}
