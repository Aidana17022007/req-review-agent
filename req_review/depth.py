"""Глубина анализа (v5): проверки, которые не зависят от силы модели и закрывают типовые пропуски спецификаций.

- missing_read_method: в API описано только изменение данных, а документ опирается на их чтение (экран, интеграция);
  плюс противоречивое назначение метода («сохранение» и «чтение» в одном описании).
- integration_contract: документ строится на событиях внешней системы, но нигде не описан контракт события
  (состав полей, типы операций, гарантии доставки и порядок).
- line_coverage: каждая содержательная строка документа учтена — вошла в требование или исключена с причиной.
- criteria_matrix: матрица «требование × критерий» по подтверждённым замечаниям.
- acceptance_coverage: какие требования-правила имеют хотя бы один критерий приёмки (оценка по общим терминам
  и по связям, найденным перекрёстной проверкой).
- verdicts / fix_plan: два вердикта (разработка, тестирование) по правилам и план «что исправить первым».

Все замечания — с дословными цитатами строк документа (проверяются verify.quote_in в тестах).
"""
from __future__ import annotations

import re

from .checker import SetFinding, SetRef, _ctx
from .criteria import INDIVIDUAL, criterion_name
from .reader import Document
from .splitter import EXCLUDED_SECTION_RE, MODAL_RE, Requirement

ORDER = {"critical": 0, "major": 1, "minor": 2}

# ---------------------------------------------------------------- API: чтение vs изменение

_API_MARK = re.compile(r"\b(?:rest type|http[- ]?метод|request url|endpoint|эндпоинт)\b", re.I)
_MUTATE = re.compile(r"(?:save|update|create|delete|remove|set|put|post|change)[A-Z_]?\w*|сохран\w*|изменени\w*|замен\w*|удален\w*|создани\w*",
                     re.I)
_READ_URL = re.compile(r"/(?:get|read|list|fetch|load|show|find|search)\w*|/\w*(?:info|status|settings|limits?)\b(?!/save)", re.I)
_READ_NEED = re.compile(r"\bчита\w*|\bчтени\w*|получ\w+ (?:настро|порог|сумм|данн)\w*|отобража\w*|показыва\w*|"
                        r"(?:на экране|экран\w*)[^.]{0,60}(?:видн|сумм|текущ)\w*|видны\b", re.I)


def _api_lines(doc: Document) -> list:
    return [ln for ln in doc.lines if _API_MARK.search(ln.text)]


def missing_read_method(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    api = _api_lines(doc)
    if not api:
        return []
    urls = [ln for ln in doc.lines if re.search(r"\b(?:request url|url|endpoint|эндпоинт)\b", ln.text, re.I) and "/" in ln.text]
    paths = [m.group(0) for ln in urls for m in re.finditer(r"/[\w/{}.-]+", ln.text)]
    if not paths:
        return []
    mutating = [p for p in paths if _MUTATE.search(p)]
    reading = [p for p in paths if _READ_URL.search(p) and not _MUTATE.search(p)]
    out: list[SetFinding] = []
    api_start = min(ln.lineno for ln in api)
    # места вне описания API, которые опираются на чтение данных (экран, интеграция)
    needs = [ln for ln in doc.lines if ln.lineno < api_start and _READ_NEED.search(ln.text)]
    by_line = {r.line_start: r for r in reqs}
    if mutating and not reading and needs:
        url_ln = next(ln for ln in urls if any(p in ln.text for p in mutating))
        refs = [_ref(by_line, url_ln, mutating[0])]
        for ln in needs[:2]:
            refs.append(_ref(by_line, ln, _READ_NEED.search(ln.text).group(0)))
        out.append(SetFinding(
            "gap", "set_complete", refs,
            f"В спецификации API описан только метод изменения данных ({', '.join(dict.fromkeys(mutating))}), а метода чтения "
            "нет. При этом документ на чтение опирается: экран показывает текущие значения, интеграция «читает» настройки. "
            "Приложение не сможет показать сохранённый порог и сумму за месяц — функцию нельзя реализовать целиком.",
            "critical", "Добавить метод чтения (например, GET /alerts/limit?cardId=…): ответ — порог, признак включения, "
            "сумма расходов за текущий месяц; коды ответа и пример тела — как у метода сохранения.", "правило"))
    # одно описание метода говорит и о сохранении, и о чтении
    for ln in api + [ln for ln in doc.lines if re.search(r"\|\s*\**description\**\s*\|", ln.text, re.I)]:
        t = ln.text
        if re.search(r"description|описани|назначени", t, re.I) and _MUTATE.search(t) and re.search(r"чтени\w*|read\b|получени\w*", t, re.I):
            frag = re.search(r"[^|]*(?:сохран|save)[^|]*(?:чтени|read|получени)[^|]*", t, re.I)
            q = (frag.group(0) if frag else t).strip()
            out.append(SetFinding(
                "contradiction", "set_consistent", [_ref(by_line, ln, q)],
                f"Назначение метода противоречиво: в одном описании и изменение, и чтение («{q[:80]}»). Непонятно, что метод "
                "делает и какие данные возвращает — разработчик и тестировщик поймут его по-разному.",
                "major", "Разделить на два метода: чтение настроек (GET, без изменения данных) и сохранение (PUT/POST с телом); "
                "у каждого — своё описание, параметры и ответы.", "правило"))
            break
    return out


# ---------------------------------------------------------------- интеграция: контракт события

_EVENT = re.compile(r"\bсобыти\w*|\bevent\w*|\bсообщени\w* (?:от|из) |\bвебхук\w*|\bwebhook\w*", re.I)
_EXT_SYSTEM = re.compile(r"процессинг\w*|внешн\w+ систем\w*|шин\w* данных|kafka|очеред\w*|брокер\w*|абс\b|core banking", re.I)
# контракт описан, если рядом со словом «событие» есть описание его структуры (UI-«сообщения» не в счёт)
_CONTRACT = re.compile(r"(?:формат|схем|структур|состав|пол[яе]\b|атрибут|payload|json|avro|protobuf)\w*[^.\n]{0,40}(?:событи|event)|"
                       r"(?:событи|event)\w*[^.\n]{0,40}(?:формат|схем|структур|состав|пол[яе]\b|атрибут|payload|json|содерж)",
                       re.I)
_DELIVERY = re.compile(r"at[- ]least[- ]once|exactly[- ]once|порядок (?:доставки|событий|обработки)|ключ\w* (?:идемпотент|дедуплик)|"
                       r"дедупликац\w*|гаранти\w* доставк\w*", re.I)


def integration_contract(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    ev = [ln for ln in doc.lines if _EVENT.search(ln.text)]
    ext = [ln for ln in doc.lines if _EXT_SYSTEM.search(ln.text)]
    if len(ev) < 2 or not ext:
        return []
    if any(_CONTRACT.search(ln.text) for ln in doc.lines):
        return []
    by_line = {r.line_start: r for r in reqs}
    # опорные места: поток от внешней системы, требование со словом «событие»
    flow = next((ln for ln in doc.lines if _EXT_SYSTEM.search(ln.text) and re.search(r"→|->|передаёт|отправляет|покупк", ln.text)), ext[0])
    refs = [_ref(by_line, flow, _EXT_SYSTEM.search(flow.text).group(0))]
    for ln in ev[:2]:
        if ln.lineno != flow.lineno:
            refs.append(_ref(by_line, ln, _EVENT.search(ln.text).group(0)))
    no_delivery = not any(_DELIVERY.search(ln.text) for ln in doc.lines)
    types = re.search(r"возврат|отмен|перевод|сняти\w* наличн", doc.text, re.I)
    problem = ("Расчёт строится на событиях внешней системы, но контракт события не описан: нет состава полей (карта, "
               "операция, тип операции, сумма и валюта, время с часовым поясом, ссылка на исходную операцию)")
    if types:
        problem += f", нет перечня типов операций, хотя правила их различают («{types.group(0)}»)"
    if no_delivery:
        problem += ", не заданы гарантии доставки, порядок и обработка дублей"
    problem += ". Сервис нельзя реализовать однозначно, а интеграцию — протестировать."
    return [SetFinding(
        "gap", "set_complete", refs, problem, "critical",
        "Описать контракт события: поля и типы, перечень типов операций (покупка, возврат, отмена, перевод, снятие), "
        "идентификатор для дедупликации, гарантию доставки (at-least-once), порядок и поведение при опоздавших событиях; "
        "пример сообщения.", "правило")]


def _ref(by_line: dict, ln, frag: str) -> SetRef:
    r = by_line.get(ln.lineno)
    if r and frag.lower() in r.text.lower():
        return SetRef(r.rid, _ctx(r.text, frag))
    return SetRef("DOC", _ctx(ln.text.strip(), frag))


# ---------------------------------------------------------------- учёт строк документа

_SERVICE = re.compile(r"^\s*(?:#{1,6}\s|\|?\s*:?-{3,}|```|---\s*$|\*\*\*\s*$)|^\s*\|(?:\s*\|)+\s*$")


_DESCRIPTIVE = re.compile(r"цел[иь]|архитектур|bpmn|sequence|схем|диаграмм|назначени|введени|общие положени", re.I)
_GLOSSARY = re.compile(r"термин|глоссари|определени|сокращени", re.I)
_META = {"author", "developer", "автор", "разработчик", "gitlab project", "framework", "swagger", "controller",
         "поле", "parameter", "параметр", "исходные условия", "проверка", "подразделение"}


def line_coverage(doc: Document, reqs: list[Requirement]) -> dict:
    """Каждая непустая строка учтена: вошла в требование или исключена с причиной (разметка, описание-контекст,
    пример кода, метаданные, раздел шаблона). Остаток — «не учтено» — показывается в отчёте явно."""
    covered = set()
    for r in reqs:
        covered.update(range(r.line_start, r.line_end + 1))
    lines = doc.lines
    section, level, in_code = "", 0, False
    reasons: dict[str, int] = {}
    out = {"total": 0, "requirements": 0, "uncovered": []}

    def skip(reason):
        reasons[reason] = reasons.get(reason, 0) + 1

    for i, ln in enumerate(lines):
        t = ln.text.strip()
        h = re.match(r"^(#{1,6})\s+(.*)", t)
        if h:
            section, level = h.group(2).strip(), len(h.group(1))
        if t.startswith("```"):
            in_code = not in_code
            if t:
                out["total"] += 1
                skip("разметка")
            continue
        if not t:
            continue
        out["total"] += 1
        nxt = next((x.text.strip() for x in lines[i + 1:] if x.text.strip()), "")
        cell0 = re.sub(r"[*`]", "", t.strip("|").split("|")[0]).strip().lower() if t.startswith("|") else ""
        if ln.lineno in covered:
            out["requirements"] += 1
        elif h or _SERVICE.search(t) or len(re.sub(r"[\W_]+", "", t)) < 3 or re.fullmatch(r"\**\d{3}\**", t):
            skip("разметка")
        elif in_code:
            skip("пример кода")
        elif t.startswith("|") and re.match(r"^\|?\s*:?-{3,}", nxt):
            skip("заголовок таблицы")
        elif cell0 in _META:
            skip("метаданные")
        elif MODAL_RE.search(t) and not EXCLUDED_SECTION_RE.search(section) and not t.startswith(">"):
            skip("утверждение без идентификатора — см. замечания к набору")
            out.setdefault("unnumbered", []).append({"line": ln.lineno, "section": section, "text": t[:160]})
        elif EXCLUDED_SECTION_RE.search(section):
            skip(f"раздел шаблона «{section[:40]}»")
        elif _DESCRIPTIVE.search(section):
            skip("описание (контекст для проверки)")
        elif _GLOSSARY.search(section):
            skip("глоссарий")
        elif t.startswith(">") or level <= 2:
            skip("вводный текст")
        elif re.fullmatch(r"(?:или|либо|or)\W*", t, re.I):
            skip("разметка")
        else:
            out["uncovered"].append({"line": ln.lineno, "section": section, "text": t[:160]})
    out["accounted"] = out["total"] - len(out["uncovered"])
    out["percent"] = round(100 * out["accounted"] / out["total"]) if out["total"] else 100
    out["excluded"] = [{"reason": k, "lines": v} for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])]
    return out


# ---------------------------------------------------------------- матрица и покрытие приёмкой

def criteria_matrix(rv) -> dict:
    rows = []
    for rr in rv.req_results:
        cells = {}
        for f in rr.findings:
            if f.criterion not in cells or ORDER[f.severity] < ORDER[cells[f.criterion]]:
                cells[f.criterion] = f.severity
        rows.append({"rid": rr.req.rid, "doc_id": rr.req.doc_id, "cells": cells})
    return {"criteria": [{"key": k, "name": criterion_name(k)} for k in INDIVIDUAL], "rows": rows}


_STOP = set("если когда должен должна должно должны система клиент держатель сумма сумму суммы при для или как это что все "
            "всех также только после через более менее одного один одна".split())
_ACC_SECTION = re.compile(r"критери\w* при[её]мк|acceptance|пример\w* (?:сценари|приёмк)|сценари\w* приёмк", re.I)
_RULE_SECTION = re.compile(r"функциональн|бизнес[- ]?правил|правила", re.I)


def _stems(text: str) -> set[str]:
    words = re.findall(r"[a-zа-яё]{4,}", text.lower().replace("ё", "е"))
    return {w[:5] for w in words if w not in _STOP}


def acceptance_coverage(rv) -> dict:
    reqs = [rr.req for rr in rv.req_results]
    acc = [r for r in reqs if _ACC_SECTION.search(r.section or "")]
    rules = [r for r in reqs if r.doc_id and not _ACC_SECTION.search(r.section or "")] or \
            [r for r in reqs if _RULE_SECTION.search(r.section or "")]
    if not rules:
        return {"percent": None, "covered": [], "uncovered": [], "acceptance_rows": len(acc), "method": ""}
    linked = set()
    for f in rv.set_findings:  # перекрёстная проверка связала пример с правилом — пример относится к правилу
        ids = {x.req_id for x in f.refs}
        if ids & {a.rid for a in acc}:
            linked |= ids
    covered, uncovered = [], []
    for r in rules:
        rs = _stems(r.text)
        ok = r.rid in linked or any(len(rs & _stems(a.text)) >= 3 for a in acc)
        (covered if ok else uncovered).append({"rid": r.rid, "doc_id": r.doc_id, "text": r.text[:120]})
    pct = round(100 * len(covered) / len(rules))
    return {"percent": pct, "covered": covered, "uncovered": uncovered, "acceptance_rows": len(acc),
            "method": "оценка: общие термины правила и строки приёмки (≥ 3) или связь, найденная перекрёстной проверкой"}


def acceptance_gap(rv, cov: dict) -> SetFinding | None:
    if cov.get("percent") is None or cov["percent"] >= 60 or not cov["uncovered"]:
        return None
    unc = cov["uncovered"][:4]
    return SetFinding(
        "gap", "set_validatable", [SetRef(u["rid"], u["text"][:60]) for u in unc],
        f"Критерии приёмки покрывают {cov['percent']} % правил ({len(cov['covered'])} из {len(cov['covered']) + len(cov['uncovered'])}). "
        f"Без примеров остаются: {', '.join(u['doc_id'] or u['rid'] for u in cov['uncovered'][:8])}. "
        "Приёмку нельзя провести по документу — каждый тестировщик придумает свои ожидаемые результаты.",
        "major", "Добавить по каждому правилу хотя бы один пример «исходные условия → действие → ожидаемый результат», "
        "включая граничные значения и отрицательные сценарии.", "правило")


# ---------------------------------------------------------------- вердикты и план исправлений

_TEST_BLOCK = {"verifiable", "unambiguous", "set_consistent", "set_verifiable", "correct"}


def verdicts(rv) -> dict:
    fs = [f for rr in rv.req_results for f in rr.findings] + list(rv.set_findings)
    crit = [f for f in fs if f.severity == "critical"]
    major = [f for f in fs if f.severity == "major"]
    dev = "нельзя" if crit else ("с оговорками" if major else "можно")
    test_crit = [f for f in crit if f.criterion in _TEST_BLOCK]
    test = "нельзя" if test_crit else ("с оговорками" if crit or any(f.criterion in _TEST_BLOCK for f in major) else "можно")
    return {"development": dev, "testing": test,
            "rule": "Разработка: «нельзя» при любом критичном дефекте, «с оговорками» — при существенных. Тестирование: "
                    "«нельзя» при критичных противоречиях, неоднозначностях или непроверяемости, «с оговорками» — при "
                    "остальных критичных или существенных дефектах этих критериев."}


def fix_plan(rv, limit: int = 8) -> list[dict]:
    """Что исправить первым: критичные (по одному пункту), затем существенные, сгруппированные по критерию."""
    items = []
    sid = {id(f): f"S-{i:02d}" for i, f in enumerate(rv.set_findings, 1)}
    for f in sorted(rv.set_findings, key=lambda f: ORDER[f.severity]):
        if f.severity == "critical":
            items.append({"severity": "critical", "ids": [sid[id(f)]], "reqs": [r.req_id for r in f.refs if r.req_id != "DOC"],
                          "title": f.problem.split(". ")[0][:140], "action": f.fix})
    for rr in rv.req_results:
        for f in rr.findings:
            if f.severity == "critical":
                items.append({"severity": "critical", "ids": [rr.req.rid], "reqs": [rr.req.rid],
                              "title": f"{rr.req.doc_id or rr.req.rid}: {f.problem.split('. ')[0][:120]}", "action": f.fix})
    groups: dict[str, list] = {}
    for rr in rv.req_results:
        for f in rr.findings:
            if f.severity == "major":
                groups.setdefault(f.criterion, []).append((rr.req.rid, f))
    for f in rv.set_findings:
        if f.severity == "major":
            groups.setdefault(f.criterion, []).append((sid[id(f)], f))
    for crit, lst in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        items.append({"severity": "major", "ids": [i for i, _ in lst][:10], "reqs": [i for i, _ in lst if i.startswith("R-")][:10],
                      "title": f"{criterion_name(crit)}: замечаний — {len(lst)}", "action": lst[0][1].fix})
    return items[:limit]


# ---------------------------------------------------------------- узкий проход полноты (LLM, 1 запрос)

SYSTEM_GAPS = """Ты — ведущий аналитик требований и тест-дизайнер в банке. Проверь документ по ЧЕК-ЛИСТУ ПОЛНОТЫ.
Ищи только то, чего в документе НЕТ или что определено неоднозначно, и только если это мешает реализовать или
протестировать функцию. Для каждого пункта чек-листа — не более 2 замечаний, самые важные:
1. terms — термин используется в правиле, но нигде не определён (что значит «активная карта», «проведённая покупка»…).
2. edge — граничные и альтернативные сценарии: возврат/частичный возврат/отмена в другом периоде, повтор, одновременные
   действия, событие пришло с опозданием.
3. errors — ошибки и состояние после ошибки: что видит пользователь при 401/403/404/500/таймауте, сохранено ли изменение.
4. defaults — значение по умолчанию и первое использование (что возвращается, если настройка ещё не задавалась).
5. messages — тексты сообщений пользователю (ошибка ввода, успех) и где они показываются.
6. nfr — нефункциональное требование без метрики: перцентиль, нагрузка, точка измерения, период.
7. data — модель данных: единицы, типы, срок хранения, кто владелец данных.
8. template — незаполненные служебные разделы шаблона (версия документа, согласующие, чек-лист, раздел тестирования).
В refs — 1–2 ДОСЛОВНЫЕ цитаты (3–15 слов, символ в символ) из документа: id требования из нарезки или "DOC" для текста
вне нарезки. problem — что именно не определено и к чему это приведёт; fix — конкретно, что дописать (с примером).
severity: critical — функцию нельзя реализовать однозначно; major — нужно до тест-кейсов; minor — оформление.
Не повторяй уже найденные замечания (список ниже). Пиши по-русски. Верни ТОЛЬКО JSON:
{"findings":[{"check":"terms","type":"gap","criterion":"set_complete|set_comprehensible|set_validatable",
"refs":[{"id":"R-001","quote":"..."}],"problem":"...","severity":"major","fix":"..."}]}"""

_GAP_CRIT = {"terms": "set_comprehensible", "messages": "set_complete", "nfr": "set_validatable", "template": "set_complete"}


def completeness_pass(split, doc: Document, llm, dropped: list[dict], found: list[SetFinding], log=print) -> None:
    import json as _json
    import os

    from .checker import SET, LLMError, LLMFatalError, _doc_context, _norm_crit, _norm_sev
    from .verify import quote_in

    if os.getenv("REQLENS_GAPS", "1") == "0" or getattr(llm, "provider", "") == "rules":
        return
    reqs = split.requirements
    by_id = {r.rid: r for r in reqs}
    known = [f.problem[:160] for f in found]
    payload = {"ДОКУМЕНТ": _doc_context(doc)[:40000], "НАРЕЗКА": [{"id": r.rid, "doc_id": r.doc_id, "text": r.text[:300]} for r in reqs],
               "УЖЕ НАЙДЕНО": known[:40]}
    log("  проход полноты: термины, граничные случаи, ошибки, умолчания, сообщения, НФТ, данные, шаблон")
    try:
        data = llm.generate_json(SYSTEM_GAPS, _json.dumps(payload, ensure_ascii=False, indent=1), task="gaps",
                                 context={"reqs": reqs, "doc": doc})
    except LLMFatalError:
        raise
    except LLMError as e:
        log(f"  проход полноты пропущен ({e})")
        return
    seen = {(f.criterion, x.quote) for f in found for x in f.refs}
    added = 0
    for f in (data or {}).get("findings", []) or []:
        refs = []
        for ref in f.get("refs", []) or []:
            rid, q = str(ref.get("id", "")).strip(), str(ref.get("quote", "")).strip()
            src = by_id[rid].text if rid in by_id else doc.text
            if quote_in(q, src):
                refs.append(SetRef(rid if rid in by_id else "DOC", q))
            else:
                dropped.append({"where": rid or "набор", "quote": q, "problem": f.get("problem", "")})
        if not refs:
            continue
        crit = _norm_crit(f.get("criterion") or _GAP_CRIT.get(str(f.get("check", "")), "set_complete"), SET, "set_complete")
        if any((crit, r.quote) in seen for r in refs):
            continue
        seen |= {(crit, r.quote) for r in refs}
        kind = "terminology" if str(f.get("check", "")) == "terms" else "gap"
        found.append(SetFinding(kind, crit, refs, str(f.get("problem", "")).strip(), _norm_sev(f.get("severity")),
                                str(f.get("fix", "")).strip(), "LLM (проход полноты)"))
        added += 1
    log(f"  проход полноты: добавлено замечаний {added}")
