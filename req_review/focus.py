"""v6: узкие проходы модели (один класс дефектов на запрос) и self-consistency проверки требований.

Маленькие модели внимательнее, когда в запросе один вопрос. Каждый узкий проход — отдельная задача (task) со своей
JSON-схемой; запускается, только если в документе есть к чему его применить (числа, API, приёмка, НФТ). Цитаты
проверяются так же, как у прохода полноты (verify.quote_in), повторы уже найденного не добавляются.

Классы: граничные значения, отрицательные сценарии API, предусловия приёмки, метрики НФТ, ошибки и состояния
интерфейса, модель данных, интеграция и события.

Self-consistency: проверка требований повторяется с другой температурой; замечание модели к требованию остаётся,
только если его подтвердил второй проход (тот же или родственный критерий) или правило. Неподтверждённые
уходят в rejected с причиной — так снижается доля случайных замечаний.
"""
from __future__ import annotations

import os
import re

from .depth import _api_lines, llm_set_pass

_COMMON = """Пройди ПО ОЧЕРЕДИ каждый элемент списка ФОКУС.targets (это требования из нарезки) и для каждого, где есть
пробел, дай отдельное замечание (до 12 замечаний). Замечание — только о том, чего в документе НЕТ или что определено
неоднозначно, и только если это мешает реализовать или протестировать функцию. Список «УЖЕ НАЙДЕНО» — для контекста:
повторы (тот же критерий и та же цитата) код отфильтрует сам, поэтому похожая проблема в ДРУГОМ требовании — не повтор. В refs — 1–2 ОБЪЕКТА {"id": ..., "quote": ...}: id требования из нарезки (R-001…) или "DOC" для
текста вне нарезки, quote — ДОСЛОВНАЯ цитата из него (3–15 слов, символ в символ). Не пиши в refs просто "R-001" или
"DOC" — нужна цитата. problem — что именно не определено и к чему это приведёт; fix — конкретно, что дописать, с
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
    "focus_errors_ui": ("ошибки и состояния интерфейса", """Ты — UX-аналитик и тест-дизайнер. Для КАЖДОГО экрана, действия
пользователя и кода ошибки проверь: что видит пользователь при каждой ошибке (текст сообщения и место показа), какое
состояние экрана после ошибки и после успеха (что сохранено, что сброшено), что при пустых данных, при загрузке и при
недоступности сервиса, можно ли повторить действие. Замечание — если поведение или текст не определены.
""" + _COMMON),
    "focus_data": ("модель данных", """Ты — архитектор данных. Для КАЖДОГО требования к данным и КАЖДОГО поля API проверь:
тип и формат, единицы и точность, обязательность, допустимые значения, срок хранения и удаление, кто владелец и кто
меняет, ключ уникальности, связь с другими сущностями, требования к персональным данным. Замечание — если чего-то из
этого не хватает для реализации или проверки.
""" + _COMMON),
    "focus_integration": ("интеграция и события", """Ты — интеграционный архитектор. Для КАЖДОГО взаимодействия с внешней
системой (события, вызовы, очереди) проверь: состав сообщения и типы полей, кто инициатор, гарантия доставки, порядок,
дубли и идемпотентность, опоздавшие и пропущенные события, повторы и таймауты, что при недоступности второй стороны,
мониторинг. Замечание — если что-то не определено.
""" + _COMMON),
}

_UI = re.compile(r"\bui\b|ux|дизайн|экран|интерфейс", re.I)
_DATA = re.compile(r"данн|модел\w* данн|хранени", re.I)
_INTEG = re.compile(r"интеграц|sequence|архитектур|событи|процессинг|очеред|kafka|webhook", re.I)
_STATUS = re.compile(r"\b[45]\d\d\b")

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
    if task in ("focus_errors_ui", "focus_data", "focus_integration"):
        return bool(targets(task, split, doc))
    return True


def targets(task: str, split, doc) -> list[dict]:
    """Элементы, которые узкий проход обходит по очереди (требования из нарезки)."""
    from .depth import _ACC_SECTION

    reqs = split.requirements
    if task == "focus_bounds":
        sel = [r for r in reqs if _NUM_RULE.search(r.text)]
    elif task == "focus_api_negative":
        api = _api_lines(doc)
        start = min(ln.lineno for ln in api) if api else 10 ** 9
        sel = [r for r in reqs if r.line_start >= start - 15]
    elif task == "focus_acceptance":
        sel = [r for r in reqs if _ACC_SECTION.search(r.section or "") or "|" in r.text and _ACC.search(r.section or "")]
    elif task == "focus_errors_ui":
        sel = [r for r in reqs if _UI.search(r.section or "") or _STATUS.search(r.text[:12])]
    elif task == "focus_data":
        sel = [r for r in reqs if _DATA.search(r.section or "") or re.search(r"параметр|ответ", r.section or "", re.I)]
    elif task == "focus_integration":
        sel = [r for r in reqs if _INTEG.search(r.section or "") or re.search(r"процессинг|событи", r.text, re.I)]
    else:
        sel = [r for r in reqs if _NFR.search(r.section or "") or getattr(r, "category", "") in ("performance", "availability")]
    return [{"id": r.rid, "doc_id": r.doc_id, "text": r.text[:240]} for r in sel[:30]]


def focused_passes(split, doc, llm, dropped: list, found: list, log=print) -> dict:
    """Узкие проходы (по одному классу на запрос). Возвращает {task: добавлено замечаний}."""
    if os.getenv("REQLENS_FOCUSED", "1") == "0" or getattr(llm, "provider", "") == "rules":
        return {}
    import json as _json

    from .checker import LLMError, LLMFatalError, _doc_context

    stats = {}
    jobs = [(task, label, system) for task, (label, system) in PASSES.items() if applicable(task, split, doc)]
    # v12: запросы узких проходов независимы — параллельно; «уже найдено» — общий снимок до проходов,
    # слияние (проверка цитат, отсев повторов) — последовательно в фиксированном порядке PASSES
    known = [f.problem[:160] for f in found][:40]
    reqs = split.requirements
    base = {"ДОКУМЕНТ": _doc_context(doc)[:40000],
            "НАРЕЗКА": [{"id": r.rid, "doc_id": r.doc_id, "text": r.text[:300]} for r in reqs], "УЖЕ НАЙДЕНО": known}

    def call(job):
        task, label, system = job
        log(f"  узкий проход: {label}")
        payload = {**base, "ФОКУС": {"class": label, "targets": targets(task, split, doc)}}
        try:
            return llm.generate_json(system, _json.dumps(payload, ensure_ascii=False, indent=1), task=task,
                                     context={"reqs": reqs, "doc": doc})
        except LLMFatalError:
            raise
        except LLMError as e:
            log(f"  узкий проход «{label}» пропущен ({e})")
            return None

    from .parallel import pmap

    for (task, label, system), data in zip(jobs, pmap(call, jobs)):
        if data is None:
            stats[task] = 0
            continue
        stats[task] = llm_set_pass(split, doc, llm, dropped, found, log, system=system, task=task,
                                   label=f"узкий проход «{label}»", source=f"LLM (узкий проход: {label})", prefetched=data)
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
