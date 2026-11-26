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


# ---------------------------------------------------------------- полнота: НФТ, ошибки, сообщения, шаблон, приёмка

_NFR_SECTION = re.compile(r"нефункциональн|производительн|non-?functional|\bnfr\b|быстродейств", re.I)
_TIME_LIMIT = re.compile(r"в течение (?:минуты|секунды|часа|\d+(?:[.,]\d+)?\s*(?:с|сек\w*|мс|минут\w*|час\w*)\b)|"
                         r"не (?:более|дольше|позднее) \d+(?:[.,]\d+)?\s*(?:с|сек\w*|мс|минут\w*)\b|"
                         r"за \d+(?:[.,]\d+)?\s*(?:с|сек\w*|мс)\b", re.I)
_PERCENTILE = re.compile(r"перцентил\w*|\bp\s?9\d\b|\b\d{2}(?:[.,]\d+)?\s*%\s*(?:запрос|случа|событи|операци|вызов)|"
                         r"для \d{2}(?:[.,]\d+)?\s*%|в \d{2}(?:[.,]\d+)?\s*% случа", re.I)
_LOAD = re.compile(r"\b(?:rps|tps|qps)\b|нагрузк\w*|запрос\w* в секунд|событи\w* в секунд|одновременн\w*", re.I)


def _section_of(doc: Document) -> dict:
    sec, out = "", {}
    for ln in doc.lines:
        h = re.match(r"^\s*#{1,6}\s+(.*)", ln.text)
        if h:
            sec = h.group(1).strip()
        out[ln.lineno] = sec
    return out


def nfr_metric(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    """НФТ со сроком («в течение минуты») без доли событий (перцентиль), нагрузки и точки измерения — не проверяется."""
    sec = _section_of(doc)
    hits = [ln for ln in doc.lines if _TIME_LIMIT.search(ln.text)
            and (_NFR_SECTION.search(sec.get(ln.lineno, "")) or re.search(r"\bНФТ|\bNFR", ln.text))]
    if not hits or any(_PERCENTILE.search(ln.text) for ln in doc.lines):
        return []
    by_line = {r.line_start: r for r in reqs}
    no_load = not any(_LOAD.search(ln.text) for ln in doc.lines)
    ln = hits[0]
    q = _TIME_LIMIT.search(ln.text).group(0)
    problem = (f"Нефункциональное требование задаёт срок («{q}»), но не говорит, для какой доли событий он выполняется "
               "(перцентиль: 95 % или 99 %), от какой точки и до какой измеряется время")
    problem += (", при какой нагрузке (событий в секунду) — " if no_load else " — ")
    problem += "требование нельзя проверить нагрузочным тестом: любой замер можно трактовать как выполнение."
    return [SetFinding(
        "gap", "set_validatable", [_ref(by_line, h, _TIME_LIMIT.search(h.text).group(0)) for h in hits[:2]], problem, "major",
        "Переписать измеримо: «Для 99 % событий процессинга push передаётся сервису отправки не позднее 60 с с момента "
        "получения события сервисом расходов при нагрузке до N событий в секунду; измерение — по меткам времени в журнале».",
        "правило")]


_STATUS_500 = re.compile(r"\*{0,2}\b500\b[.:]?\*{0,2}[.:]?\s*(?:ответ|internal|ошибк|unsuccess)|\b500\. unsuccessful", re.I)
_AFTER_ERR = re.compile(r"\b500\b[^.\n]{0,120}(?:сохран|откат|состояни|изменени\w* не)|откат\w* (?:транзакц|изменени)|"
                        r"транзакци\w*|атомарн\w*|идемпотентн\w* (?:повтор|сохранени)", re.I)


def state_after_error(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    """API изменяет данные и описывает ответ 500, но не говорит, применено ли изменение после внутренней ошибки."""
    s500 = [ln for ln in doc.lines if _STATUS_500.search(ln.text)]
    if not s500 or not _api_lines(doc) or any(_AFTER_ERR.search(ln.text) for ln in doc.lines):
        return []
    urls = [m.group(0) for ln in doc.lines if re.search(r"\b(?:request url|url|endpoint)\b", ln.text, re.I)
            for m in re.finditer(r"/[\w/{}.-]+", ln.text)]
    mut_line = next((ln for ln in doc.lines if re.search(r"замени\w*|сохрани\w*|обнови\w*|удали\w*", ln.text, re.I)
                     and re.match(r"^\s*\d+\.", ln.text)), None)
    if not any(_MUTATE.search(u) for u in urls) and not mut_line:
        return []
    by_line = {r.line_start: r for r in reqs}
    refs = [_ref(by_line, s500[0], re.search(r"500", s500[0].text).group(0))]
    if mut_line:
        refs.append(_ref(by_line, mut_line, mut_line.text.strip().split(" ", 1)[-1][:60]))
    refs[0] = SetRef(refs[0].req_id, _ctx(s500[0].text.strip(), "500"))
    return [SetFinding(
        "gap", "set_complete", refs,
        "Для ответа 500 не определено, сохранена ли настройка: метод изменяет данные, но документ не говорит, откатывается "
        "ли изменение при внутренней ошибке и что показывать клиенту. Приложение не знает, повторять ли запрос, а "
        "тестировщик — какое состояние ожидать после сбоя.", "major",
        "Дописать: «При ответе 500 настройка не изменяется (операция атомарна); приложение показывает сообщение "
        "„Не удалось сохранить, попробуйте позже“ и прежние значения; повтор запроса безопасен».", "правило")]


_MSG_SHOWN = re.compile(r"(?:сообщени\w*|ошибк\w*|уведомлени\w* об ошибк\w*)[^.\n]{0,40}(?:появля\w*|отобража\w*|показыва\w*|выводи\w*)|"
                        r"(?:появля\w*|отобража\w*|показыва\w*|выводи\w*)[^.\n]{0,20}сообщени\w*", re.I)


def message_texts(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    """Документ говорит, что пользователю показывается сообщение, но не задаёт его текст."""
    by_line = {r.line_start: r for r in reqs}
    for ln in doc.lines:
        t = ln.text
        m = _MSG_SHOWN.search(t)
        if not m or re.search(r"[«\"“][^»\"”]{3,}[»\"”]", t[m.start():]) or re.search(r"текст\w* сообщени", t, re.I):
            continue
        return [SetFinding(
            "gap", "set_complete", [_ref(by_line, ln, m.group(0))],
            f"Текст сообщения пользователю не задан («{m.group(0)}»): не указано, что именно видит клиент при каждой "
            "ошибке (сумма вне диапазона, не целое число, нет связи, сессия истекла). Разработчик придумает тексты сам, "
            "тестировщику не с чем сравнивать.", "major",
            "Добавить таблицу сообщений: условие → текст → место показа. Например: сумма меньше 1 000 ₸ — «Введите сумму "
            "от 1 000 до 1 000 000 ₸» под полем «Порог».", "правило")]
    return []


def template_unfilled(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    """Служебные разделы шаблона не заполнены: версия/дата документа, отметки чек-листа, блок согласующих."""
    refs, what = [], []
    lines = doc.lines
    for ln in lines:
        if re.search(r"(?:верси\w*|дат\w*)[^.\n]{0,40}не заполнен", ln.text, re.I):
            refs.append(SetRef("DOC", _ctx(ln.text.strip(), re.search(r"не заполнен\w*", ln.text).group(0))))
            what.append("версия и дата документа")
            break
    yn = [ln for ln in lines if ln.text.strip().startswith("|") and re.search(r"\|\s*Да\s*/\s*Нет(?:\s*/\s*Не требуется)?\s*\|", ln.text)]
    if len(yn) >= 3:
        refs.append(SetRef("DOC", re.search(r"Да\s*/\s*Нет(?:\s*/\s*Не требуется)?", yn[0].text).group(0)))
        what.append(f"отметки чек-листа ревью ({len(yn)} пунктов «Да / Нет» без выбора)")
    for i, ln in enumerate(lines):
        if re.search(r"\|\s*\**(?:фио|подпись|согласующ)", ln.text, re.I) and ln.text.strip().startswith("|"):
            rows = [x.text for x in lines[i + 1:i + 8] if x.text.strip().startswith("|")]
            data = [r for r in rows if not re.match(r"^\|?\s*:?-{3,}", r.strip())]
            if data and all(not re.sub(r"[|\s]", "", r) for r in data):
                cell = re.search(r"(?:ФИО|Подпись|Согласующ)[^|]*", ln.text, re.I)
                refs.append(SetRef("DOC", cell.group(0).strip() if cell else ln.text.strip()[:40]))
                what.append("блок согласующих (нет ни одного подразделения и ФИО)")
            break
    if not what:
        return []
    return [SetFinding(
        "structure", "set_complete", refs[:3],
        "Служебные разделы шаблона не заполнены: " + "; ".join(what) + ". Нельзя понять, какая версия документа "
        "проверяется, кем она согласована и прошла ли внутреннее ревью — изменения нельзя отследить.", "minor",
        "Заполнить версию и дату документа, проставить отметки чек-листа ревью с примечаниями и указать согласующих "
        "(подразделение, ФИО) до передачи в разработку.", "правило")]


_PRECOND_HEAD = re.compile(r"исходн\w* услови|предуслови|\bgiven\b|начальн\w* состояни", re.I)
_TOGGLE = re.compile(r"(?:уведомлени\w*|функци\w*|настройк\w*)[^.\n]{0,30}(?:выключен|включен|отключен)|переключател\w*", re.I)
_ONCE = re.compile(r"(?:максимум|не более|только) (?:один|одного|одно|1)\b[^.\n]{0,40}(?:push|уведомлени|сообщени)", re.I)
_EXPECT_NOTIFY = re.compile(r"\bpush\b|уведомлени\w*|сообщени\w*", re.I)


def acceptance_preconditions(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    """В строках критериев приёмки не задано начальное состояние, от которого зависит результат
    (включено ли уведомление, отправлялся ли уже push в этом месяце)."""
    toggle = any(_TOGGLE.search(ln.text) for ln in doc.lines)
    once = any(_ONCE.search(ln.text) for ln in doc.lines)
    if not toggle and not once:
        return []
    lines = doc.lines
    bad, first = [], None
    for i, ln in enumerate(lines):
        cells = [c.strip() for c in ln.text.strip().strip("|").split("|")]
        if not (ln.text.strip().startswith("|") and cells and _PRECOND_HEAD.search(cells[0])):
            continue
        for row in lines[i + 1:]:
            t = row.text.strip()
            if not t.startswith("|"):
                break
            if re.match(r"^\|?\s*:?-{3,}", t):
                continue
            c = [x.strip() for x in t.strip("|").split("|")]
            pre, res = c[0], " ".join(c[1:])
            miss = []
            if toggle and not re.search(r"включ|выключ|отключ|enabled", pre, re.I):
                miss.append("включено ли уведомление")
            if once and _EXPECT_NOTIFY.search(res) and not re.search(r"не отправля|не было|уже (?:отправ|получ)|отправлен|первый", pre, re.I):
                miss.append("отправлялся ли push в этом месяце")
            if miss and pre:
                bad.append((pre, miss))
                first = first or row
        break
    if not bad:
        return []
    by_line = {r.line_start: r for r in reqs}
    refs = [_ref(by_line, first, bad[0][0])] + [SetRef("DOC", p) for p, _ in bad[1:2]]
    need = sorted({m for _, ms in bad for m in ms})
    return [SetFinding(
        "gap", "set_validatable", refs,
        f"Критерии приёмки: в исходных условиях не заданы предусловия, от которых зависит результат — {', '.join(need)} "
        f"(строк без них: {len(bad)}). Один и тот же пример даёт разный ожидаемый результат в зависимости от состояния, "
        "тест нельзя повторить.", "major",
        "В каждой строке «Исходные условия» указать полное состояние: «Уведомление включено, порог 50 000 ₸, расходы "
        "за месяц 48 500 ₸, push в этом месяце не отправлялся».", "правило")]


_DECLARED = re.compile(r"^\s*(?:\*\*|#+\s*)([1-5]\d{2})\b[.*\s]")
_CODE_CTX = re.compile(r"(?:результат|код\w*|ответ\w*|статус\w*|status|response)[^.\n]{0,40}?\b([1-5]\d{2})\b(?:[^.\n]{0,20}?(?:или|,|и)\s*([1-5]\d{2})\b)?",
                       re.I)


def api_codes_and_body(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    """API: код ответа упомянут в тексте, но не описан среди статусов; Content-Type задан, а тело не используется."""
    if not _api_lines(doc):
        return []
    by_line = {r.line_start: r for r in reqs}
    out: list[SetFinding] = []
    declared = {m.group(1) for ln in doc.lines for m in [_DECLARED.match(ln.text)] if m}
    if declared:
        for ln in doc.lines:
            if _DECLARED.match(ln.text):
                continue
            for m in _CODE_CTX.finditer(ln.text):
                for code in filter(None, m.groups()):
                    if code in declared or not code.startswith(("2", "3")):
                        continue
                    out.append(SetFinding(
                        "gap", "set_complete", [_ref(by_line, ln, m.group(0))],
                        f"Код {code} назван в описании ответа, но не описан в перечне статусов ({', '.join(sorted(declared))}): "
                        f"нет ни условия, когда он возвращается, ни примера тела. Клиент не знает, ждать ли {code} и как его обработать.",
                        "major", f"Либо описать код {code} (когда возвращается, пример ответа), либо убрать его из текста и "
                                 "оставить один успешный код.", "правило"))
                    break
                else:
                    continue
                break
            if out:
                break
    ct = next((ln for ln in doc.lines if re.search(r"content-type", ln.text, re.I)), None)
    nobody = next((ln for ln in doc.lines if re.search(r"тел\w* (?:запроса )?не используется|без тела|body is not used|no request body",
                                                        ln.text, re.I)), None)
    if ct and nobody:
        out.append(SetFinding(
            "contradiction", "set_consistent", [_ref(by_line, ct, "Content-Type"), _ref(by_line, nobody, nobody.text.strip().lstrip("*- ")[:40])],
            "Content-Type запроса указан (application/json), но тело не используется: непонятно, передаются ли параметры в "
            "теле или в строке запроса, и что проверять при пустом теле.", "major",
            "Если параметры передаются в строке запроса — убрать Content-Type запроса; если в теле — описать тело JSON с "
            "полями и примером (предпочтительно для метода изменения данных).", "правило"))
    return out


_UNITS = [("тиын", "тенге"), ("копе", "рубл"), ("цент", "доллар"), ("миллисекунд", "секунд")]


def unit_mix(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    """Сравниваемые величины хранятся в разных единицах (сумма в тиынах, порог в тенге)."""
    by_line = {r.line_start: r for r in reqs}
    for ln in doc.lines:
        low = ln.text.lower()
        for small, big in _UNITS:
            ms, mb = re.search(rf"\w*\s*в {small}\w*", low), re.search(rf"\w*\s*в {big}\w*", low)
            if ms and mb:
                qs = ln.text[ms.start():ms.end()]
                return [SetFinding(
                    "terminology", "set_consistent", [_ref(by_line, ln, qs)],
                    f"Сравниваемые величины хранятся в разных единицах: «{qs.strip()}» и «{ln.text[mb.start():mb.end()].strip()}». "
                    f"Порог сравнивается с суммой расходов — без явного правила пересчёта ({small} × 100 = {big}) возможна "
                    "ошибка в 100 раз.", "major",
                    f"Хранить обе величины в одной единице (например, в {small}ах как целое) и записать правило пересчёта "
                    "для отображения и API.", "правило")]
    return []


_LIMIT = re.compile(r"(?:максимум|не более|не чаще|только) (?:один|одного|одно|1)\b[^.\n]{0,60}?(?:за|в)\s+(?:календарн\w+\s+)?"
                    r"(?:месяц|сутки|день|недел\w*|период|час)", re.I)
_REGARDLESS = re.compile(r"независимо от (?:истори\w*|предыдущ\w*|ранее\w*|прошл\w*|того,? (?:был|отправ)\w*)", re.I)
_NOTIFY = re.compile(r"\bpush\b|уведомлени\w*|сообщени\w*|\bsms\b|\bсмс\b", re.I)


def limit_vs_exception(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    """Ограничение частоты («не более одного … за месяц») и правило «независимо от истории» в другом требовании:
    какое правило главнее, не сказано — разработчик и тестировщик выберут разное."""
    lim = next((r for r in reqs if _LIMIT.search(r.text) and _NOTIFY.search(r.text)), None)
    exc = next((r for r in reqs if r is not lim and _REGARDLESS.search(r.text) and (_NOTIFY.search(r.text) or "вызыва" in r.text)), None)
    if not lim or not exc:
        return []
    a, b = lim.doc_id or lim.rid, exc.doc_id or exc.rid
    qa, qb = _LIMIT.search(lim.text).group(0), _REGARDLESS.search(exc.text).group(0)
    return [SetFinding(
        "contradiction", "set_consistent", [SetRef(lim.rid, _ctx(lim.text, qa)), SetRef(exc.rid, _ctx(exc.text, qb))],
        f"{a} ограничивает частоту («{qa}»), а {b} требует отправки «{qb}». Если оба условия выполняются в одном периоде "
        f"(уведомление уже отправлено, затем изменён порог и он снова достигнут), {a} запрещает второе уведомление, а {b} "
        "его требует — какое правило главнее, не сказано. Реализация и ожидаемый результат теста зависят от толкования.",
        "critical",
        f"Явно задать приоритет: например, «При изменении порога признак отправки в текущем месяце сбрасывается; лимит "
        f"{a} считается от последнего изменения порога» — и добавить критерий приёмки на этот случай.", "правило")]


_AUTH = re.compile(r"\bbearer\b|\bтокен\w*|\btoken\b|\bсесси\w*", re.I)
_AUTH_LIFE = re.compile(r"срок\w* (?:действия|жизни) (?:токен|сесси)\w*|(?:токен|сесси)\w*[^.\n]{0,40}(?:истек|истёк|просроч|действителен|"
                        r"живёт|живет|ttl)|refresh|expire|обновлени\w* токен\w*", re.I)


def session_lifecycle(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    """API требует авторизации (Bearer, сессия), но не определено, что это за токен, сколько он живёт и что
    происходит при истёкшей или чужой сессии."""
    if not _api_lines(doc):
        return []
    auth = next((ln for ln in doc.lines if re.search(r"authorization|авторизац", ln.text, re.I) and _AUTH.search(ln.text)), None)
    if not auth or any(_AUTH_LIFE.search(ln.text) for ln in doc.lines):
        return []
    by_line = {r.line_start: r for r in reqs}
    return [SetFinding(
        "gap", "set_complete", [_ref(by_line, auth, _AUTH.search(auth.text).group(0))],
        "Токен и сессия не определены: не указано, какой токен ожидается (кем выдан, что в нём), сколько живёт сессия и "
        "что возвращает метод при истёкшей, отозванной или чужой сессии. Без этого нельзя реализовать проверку доступа "
        "и написать негативные тесты авторизации.", "major",
        "Описать: тип токена и издателя, срок жизни сессии, ответ при истёкшем токене (401 с телом {\"message\": …}), "
        "поведение приложения (повторный вход) и пример заголовка Authorization.", "правило")]


_RANGE_SET = re.compile(r"(?:зада\w*|устанавлива\w*|указыва\w*|выбира\w*|настраива\w*)[^.\n]{0,60}?\bот\s+[\d\s ]+\s+до\s+[\d\s ]+",
                        re.I)
_DEFAULT_VAL = re.compile(r"по умолчанию[^.\n]{0,60}(?:\d|порог|значени|сумм|лимит|равн)|(?:начальн|исходн)\w* значени", re.I)


def missing_default(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    """Пользователь задаёт значение из диапазона, но не определено значение до первого сохранения
    (что возвращает чтение и что показывает экран)."""
    r = next((r for r in reqs if _RANGE_SET.search(r.text)), None)
    if r is None or any(_DEFAULT_VAL.search(ln.text) for ln in doc.lines):
        return []
    q = _RANGE_SET.search(r.text).group(0).strip()
    name = r.doc_id or r.rid
    return [SetFinding(
        "gap", "set_complete", [SetRef(r.rid, _ctx(r.text, q))],
        f"Не задано значение по умолчанию для параметра, который настраивается в {name} («{q[:70]}»): неизвестно, что хранится и "
        "что показывает экран до первого сохранения, и чем первое сохранение отличается от изменения. Разработчик "
        "выберет сам (0, пусто или минимум диапазона), тестировщику не с чем сравнивать.", "major",
        "Дописать: «До первого сохранения порог не задан: экран показывает пустое поле, уведомление выключено, метод "
        "чтения возвращает amount = null» — или конкретное значение по умолчанию.", "правило")]


_REFUND = re.compile(r"возврат\w*[^.\n]{0,80}(?:уменьша\w*|вычита\w*|учитыва\w*|снижа\w*|корректиру\w*)", re.I)
_REFUND_EDGE = re.compile(r"частичн\w* возврат|возврат\w*[^.\n]{0,60}(?:частичн|друг\w* месяц|следующ\w* месяц|после отправ|"
                          r"уже отправ|ниже порог)", re.I)
_TRIGGER = re.compile(r"порог\w*|лимит\w*|\bpush\b|уведомлени\w*", re.I)


def refund_edges(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    """Возврат меняет накопленную сумму, от которой зависит срабатывание (порог, уведомление), но граничные случаи
    не описаны: частичный возврат, возврат в другом месяце, возврат после отправленного уведомления."""
    r = next((r for r in reqs if _REFUND.search(r.text)), None)
    if r is None or not any(_TRIGGER.search(x.text) for x in reqs if x is not r) or any(_REFUND_EDGE.search(ln.text) for ln in doc.lines):
        return []
    q = _REFUND.search(r.text).group(0)
    return [SetFinding(
        "gap", "set_complete", [SetRef(r.rid, _ctx(r.text, q))],
        f"Возврат меняет сумму, от которой зависит срабатывание порога («{q}»), но граничные случаи возвратов не "
        "описаны: частичный возврат, возврат в другом месяце (прошлый месяц уже закрыт?), возврат после отправленного "
        "уведомления — отзывается ли push, отправляется ли он снова, если сумма опустилась ниже порога и снова его "
        "достигла. Разработчик и тестировщик решат эти случаи по-разному.", "major",
        "Добавить правила и примеры приёмки: «Частичный возврат уменьшает расходы на сумму возврата; push, уже "
        "отправленный в этом месяце, не отзывается и повторно не отправляется; возврат по покупке прошлого месяца "
        "меняет только счётчик того месяца».", "правило")]


def completeness_rules(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    """Детерминированные проверки полноты v5 (подключаются в checker.deterministic_set_checks)."""
    out: list[SetFinding] = []
    for fn in (limit_vs_exception, api_codes_and_body, session_lifecycle, missing_default, refund_edges, unit_mix, nfr_metric,
               state_after_error, message_texts, acceptance_preconditions, template_unfilled):
        out.extend(fn(reqs, doc))
    return out


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


SYSTEM_RECOVER = """Ты — аналитик требований. Ниже — строки документа, которые не вошли ни в одно требование при
автоматической нарезке. Найди среди них утверждения-требования (что система или пользователь должны делать, свойство,
ограничение, правило). Не придумывай и не переформулируй: quote — дословный текст требования из этих строк.
Служебные строки, заголовки и пояснения пропусти. doc_id — идентификатор, если он есть в строке, иначе null.
Верни ТОЛЬКО JSON: {"requirements":[{"doc_id":null,"quote":"..."}]}"""


def recover_uncovered(doc: Document, split, llm, log=print) -> dict:
    """«Дорезка»: строки, которые учёт строк оставил «не учтёнными», уходят модели отдельным запросом (task split);
    найденные требования добавляются в нарезку и проверяются вместе с остальными. Остаток — явный список в отчёте."""
    import json as _json
    import os

    from .llm import LLMError, LLMFatalError
    from .verify import quote_in

    lc = line_coverage(doc, split.requirements)
    unc = lc["uncovered"]
    info = {"uncovered_before": len(unc), "recovered": 0}
    if not unc or os.getenv("REQLENS_RECOVER", "1") == "0" or getattr(llm, "provider", "") == "rules":
        return info
    log(f"  дорезка: строк вне нарезки — {len(unc)}, отправляю модели")
    payload = [{"line": u["line"], "section": u["section"], "text": next(ln.text for ln in doc.lines if ln.lineno == u["line"])}
               for u in unc[:80]]
    try:
        data = llm.generate_json(SYSTEM_RECOVER, "СТРОКИ (JSON):\n" + _json.dumps(payload, ensure_ascii=False, indent=1),
                                 task="split", context={"doc": doc, "lines": payload})
    except LLMFatalError:
        raise
    except LLMError as e:
        log(f"  дорезка пропущена ({e})")
        return info
    used: set[int] = set()
    n = len(split.requirements)
    for item in (data or {}).get("requirements", []) or []:
        q = " ".join(str(item.get("quote", "")).split())
        if len(q) < 8:
            continue
        src = next((p for p in payload if p["line"] not in used and quote_in(q, p["text"])), None)
        if src is None:  # цитата не из переданных строк — не добавляем
            continue
        used.add(src["line"])
        n += 1
        split.requirements.append(Requirement(rid=f"R-{n:03d}", doc_id=item.get("doc_id") or None, text=q,
                                              section=src["section"], line_start=src["line"], line_end=src["line"],
                                              extra={"recovered": True}))
    info["recovered"] = len(used)
    log(f"  дорезка: добавлено требований {len(used)}, осталось не учтено {len(unc) - len(used)}")
    return info


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


def _example(rv, rids: list[str], fix: str) -> tuple[str, str]:
    """Пример правильной формулировки: переписанное моделью требование, шаблон kb/patterns или пример из рекомендации."""
    by = {rr.req.rid: rr for rr in rv.req_results}
    for rid in rids:
        rr = by.get(rid)
        if rr is not None and getattr(rr, "rewrite", ""):
            return rr.rewrite, f"переписанное {rid}"
    for rid in rids:
        pat = getattr(by.get(rid), "rewrite_pattern", None) or {}
        if pat.get("template"):
            return pat["template"], f"шаблон kb/patterns: {pat.get('title') or pat.get('id', '')}"
    m = re.search(r"[«\"]([^»\"]{20,})[»\"]", fix or "")
    if m:
        return m.group(1), "из рекомендации"
    m = re.search(r"\b[Нн]апример[,:]?\s*([^);]{12,240}?)(?:\)|;|\.\s|\.$|$)", fix or "")
    if m:
        return m.group(1).strip(" ,"), "из рекомендации"
    return "", ""


def fix_plan(rv, limit: int = 8) -> list[dict]:
    """Что исправить первым: критичные (по одному пункту), затем существенные, сгруппированные по критерию.
    У каждого пункта — пример правильной формулировки (example) и его источник (example_source)."""
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
    items = items[:limit]
    for it in items:
        it["example"], it["example_source"] = _example(rv, it["reqs"], it["action"])
    return items


# ---------------------------------------------------------------- узкий проход полноты (LLM, 1 запрос)

SYSTEM_GAPS = """Ты — ведущий аналитик требований и тест-дизайнер в банке. Проверь документ по ЧЕК-ЛИСТУ ПОЛНОТЫ.
Ищи только то, чего в документе НЕТ или что определено неоднозначно, и только если это мешает реализовать или
протестировать функцию. Для каждого пункта чек-листа — не более 2 замечаний, самые важные:
1. terms — термин используется в правиле, но нигде не определён: статус объекта («активная карта» — какие статусы?),
   квалификатор («карта KZT» — валюта счёта или карты?), событие («проведённая покупка» — авторизация или клиринг?).
2. edge — граничные и альтернативные сценарии: возврат (частичный, в другом месяце, после отправленного push — отзывается
   ли push, может ли сумма уйти ниже порога и снова его пересечь), отмена, повтор, одновременные действия, событие
   пришло с опозданием или не по порядку.
3. errors — ошибки и состояние после ошибки: что видит пользователь при 401/403/404/500/таймауте, сохранено ли изменение;
   сессия и токен (какой токен, срок жизни, что при истёкшей сессии); повтор запроса после сбоя.
4. defaults — значение по умолчанию и первое использование: что возвращается и что показывает экран, если настройка ещё
   ни разу не сохранялась (порог не задан); начальное значение счётчика в новом месяце.
5. messages — тексты сообщений пользователю (каждая ошибка ввода, успех, сбой) и где они показываются.
6. nfr — нефункциональное требование без метрики: перцентиль (95 %/99 %), нагрузка (событий в секунду), точка начала и
   конца измерения, период; доступность и поведение при недоступности зависимостей.
7. data — модель данных: единицы, типы, срок хранения, кто владелец данных, требования к персональным данным.
8. template — незаполненные служебные разделы шаблона (версия документа, согласующие, чек-лист, раздел тестирования).
9. acceptance — критерии приёмки: каждая строка задаёт полное начальное состояние (включено ли уведомление, отправлялся
   ли уже push в этом месяце, текущий порог); есть ли негативные и граничные примеры для каждого правила.
В refs — 1–2 ДОСЛОВНЫЕ цитаты (3–15 слов, символ в символ) из документа: id требования из нарезки или "DOC" для текста
вне нарезки. problem — что именно не определено и к чему это приведёт; fix — конкретно, что дописать (с примером).
severity: critical — функцию нельзя реализовать однозначно; major — нужно до тест-кейсов; minor — оформление.
Не повторяй уже найденные замечания (список ниже). Пиши по-русски. Верни ТОЛЬКО JSON:
{"findings":[{"check":"terms","type":"gap","criterion":"set_complete|set_comprehensible|set_validatable",
"refs":[{"id":"R-001","quote":"..."}],"problem":"...","severity":"major","fix":"..."}]}"""

_GAP_CRIT = {"terms": "set_comprehensible", "messages": "set_complete", "nfr": "set_validatable", "template": "set_complete",
             "acceptance": "set_validatable"}


def completeness_pass(split, doc: Document, llm, dropped: list[dict], found: list[SetFinding], log=print) -> None:
    import json as _json
    import os

    from .checker import SET, LLMError, LLMFatalError, _doc_context, _norm_crit, _norm_sev, norm_refs
    from .verify import quote_in

    if os.getenv("REQLENS_GAPS", "1") == "0" or getattr(llm, "provider", "") == "rules":
        return
    reqs = split.requirements
    by_id = {r.rid: r for r in reqs}
    known = [f.problem[:160] for f in found]
    payload = {"ДОКУМЕНТ": _doc_context(doc)[:40000], "НАРЕЗКА": [{"id": r.rid, "doc_id": r.doc_id, "text": r.text[:300]} for r in reqs],
               "УЖЕ НАЙДЕНО": known[:40]}
    log("  проход полноты: термины, граничные случаи, ошибки, умолчания, сообщения, НФТ, данные, шаблон, приёмка")
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
        if not isinstance(f, dict):  # ответ модели не по схеме — пропускаем элемент
            continue
        refs = []
        for ref in norm_refs(f.get("refs")):
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
