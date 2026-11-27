"""v12: классы пропусков, которые не зависят от силы модели (детерминированные правила по всему документу).

- data_model_gaps: поле, на которое опираются правила, экран или API (переключатель, тип операции, связь возврата
  с исходной покупкой), не названо в требованиях к хранимым данным;
- repeat_action: правило «при изменении X …» меняет состояние, но не сказано, считается ли изменением повторное
  сохранение того же значения или выключение и включение — признак или счётчик может сброситься без изменения;
- stub_sections: раздел-заглушка («заполняется позже», «заполняются тестировщиками», TBD) или пустой раздел;
- same_object_names: один объект назван по-разному («держатель карты» / «владелец карты», «клиент» / «пользователь»);
- error_without_code: ошибки API описаны только текстом (`message`) без машинного кода — клиент не различает ошибки.

Все цитаты — дословные фрагменты строк документа. Правила общие: работают на любом ТЗ, проверяются тестами на
выдуманных примерах (tests/test_depth_v12.py).
"""
from __future__ import annotations

import re

from .checker import SetFinding, SetRef, _ctx
from .reader import Document
from .splitter import Requirement

_HEAD = re.compile(r"^\s*(#{1,6})\s+(.*\S)")


def _sections(doc: Document) -> list[tuple[int, str, int, list]]:
    """[(уровень, заголовок, строка заголовка, [строки содержимого до следующего заголовка])]."""
    out, cur = [], None
    for ln in doc.lines:
        m = _HEAD.match(ln.text)
        if m:
            cur = (len(m.group(1)), m.group(2).strip(), ln.lineno, [])
            out.append(cur)
        elif cur is not None:
            cur[3].append(ln)
    return out


def _ref(by_line: dict, ln, frag: str) -> SetRef:
    for r in by_line.get(ln.lineno, []):
        if frag.lower() in r.text.lower():
            return SetRef(r.rid, _ctx(r.text, frag))
    return SetRef("DOC", _ctx(ln.text.strip(), frag))


def _by_line(reqs: list[Requirement]) -> dict:
    out: dict = {}
    for r in reqs:
        for n in range(r.line_start, r.line_end + 1):
            out.setdefault(n, []).append(r)
    return out


# ---------------------------------------------------------------- модель данных неполна

_DATA_HEAD = re.compile(r"требовани\w* к данным|модель данных|хранени\w* данных|хранимые данные|структура данных|data model", re.I)
_STORE_LINE = re.compile(r"^\s*(?:[-*]\s*)?(?:хранить|хранится|хранятся|сохранять в базе|в базе хранится)\b", re.I)
_CONCEPTS = [
    # (что ищем в правилах / экране / API, что должно быть в данных, как назвать)
    (re.compile(r"переключател\w*|уведомлени\w* (?:включен|выключен)\w*|по умолчанию [^.\n]{0,30}выключен\w*|\benabled\b", re.I),
     re.compile(r"включ\w*|выключ\w*|enabled|переключ\w*|статус\w* уведомлени|активн\w* уведомлени", re.I),
     "признак включения уведомления (переключатель / enabled)"),
    (re.compile(r"(?:исключа\w*|не учитыва\w*|не входят|кроме)[^.\n]{0,60}(?:перевод\w*|сняти\w*|возврат\w*)|"
                r"(?:перевод\w*|сняти\w* наличных)[^.\n]{0,40}(?:исключа\w*|не учитыва\w*)", re.I),
     re.compile(r"тип\w* операци|вид\w* операци|категори\w* операци|\bmcc\b|тип\w* транзакци", re.I),
     "тип операции (чтобы отличать покупку от перевода, снятия, возврата)"),
    (re.compile(r"возврат\w*[^.\n]{0,80}(?:исходн\w*|первоначальн\w*|оригинальн\w*) (?:покупк|операци|транзакци)", re.I),
     re.compile(r"исходн\w*|первоначальн\w*|ссылк\w* на (?:покупк|операци)|связ\w* с (?:покупк|операци)|original", re.I),
     "связь возврата с исходной покупкой (её идентификатор и дата)"),
]


def data_model_gaps(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    store = []
    for lvl, title, _ln, lines in _sections(doc):
        if _DATA_HEAD.search(title):
            store += [ln for ln in lines if ln.text.strip()]
    store += [ln for ln in doc.lines if _STORE_LINE.match(ln.text) and ln not in store]
    if not store:
        return []
    store_text = " ".join(ln.text for ln in store)
    store_lines = {ln.lineno for ln in store}
    by_line = _by_line(reqs)
    missing, refs = [], []
    for used, stored, name in _CONCEPTS:
        if stored.search(store_text):
            continue
        hit = next(((ln, m) for ln in doc.lines if ln.lineno not in store_lines for m in [used.search(ln.text)] if m), None)
        if hit:
            missing.append(name)
            refs.append(_ref(by_line, hit[0], hit[1].group(0)))
    if not missing:
        return []
    first = store[0]
    anchor = first.text.strip().lstrip("*- ")
    refs.insert(0, _ref(by_line, first, anchor[:60]))
    return [SetFinding(
        "gap", "set_complete", refs[:4],
        "Требования к данным неполны: не хранится " + "; ".join(missing) + ". Правила, экран или API опираются на эти "
        "значения, но сохранить и проверить их нечем — реализация додумает поля сама.", "major",
        "Дописать в требования к данным: " + "; ".join(missing) + " — с типом, допустимыми значениями и тем, когда "
        "поле заполняется.", "правило")]


# ---------------------------------------------------------------- повторное действие

_ON_CHANGE = re.compile(r"при (?:изменени\w*|смен\w*|обновлени\w*|переключени\w*) (\w+)", re.I)
_STATE_EFFECT = re.compile(r"сохраня\w*|сбрас\w*|обнул\w*|вызыва\w*|независимо|заново|повторно", re.I)
# документ уже говорит, что будет при том же значении или выключении-включении — замечания нет
# («повторное сохранение заменяет настройку» не отвечает, сбрасывается ли признак при том же значении)
_SAME_VALUE = re.compile(r"(?:то же|тот же|та же|той же|ту же|тем же|прежн\w*|неизменн\w*|совпадающ\w*) (?:значени|порог|сумм)\w*|"
                         r"(?:то|тот|та|той|ту|тем) же \w+[^.\n]{0,60}(?:не считает|не мен|не сбрас|не влия)|"
                         r"(?:тех же|того же|тем же) значени\w*|"
                         r"без изменени\w* значени|значени\w* не измен|не считается изменени|изменени\w* не считает|"
                         r"выключ\w*[^.\n]{0,40}(?:и|затем)[^.\n]{0,20}включ", re.I)


def repeat_action(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    if any(_SAME_VALUE.search(ln.text) for ln in doc.lines):
        return []
    by_line = _by_line(reqs)
    for ln in doc.lines:
        m = _ON_CHANGE.search(ln.text)
        if m and _STATE_EFFECT.search(ln.text[m.end():]):
            what = m.group(1)
            return [SetFinding(
                "gap", "set_complete", [_ref(by_line, ln, m.group(0))],
                f"Правило «{m.group(0)}» меняет состояние, но не сказано, что считается изменением: повторное сохранение "
                f"того же значения или выключение и включение функции. Признак отправки или счётчик может сброситься без "
                "реального изменения — клиент получит повторное уведомление или не получит нужное.", "major",
                f"Уточнить: «Изменением {what} считается только сохранение нового значения; повторное сохранение того же "
                "значения и выключение / включение уведомления состояние не меняют» (или наоборот) — и добавить критерий "
                "приёмки на этот случай.", "правило")]
    return []


# ---------------------------------------------------------------- разделы-заглушки

_STUB = re.compile(r"^\s*(?:[-*]\s*)?(?:заполня\w*(?:\s+\w+){0,3}|будет (?:заполнен|добавлен|описан|определ)\w*(?:\s+\w+){0,3}|"
                   r"tbd|tba|todo|в разработке|описание будет позже|раздел в разработке|см\. позже|n/?a|—|-)\s*\.?\s*$", re.I)
_SKIP_STUB_HEAD = re.compile(r"ревью|согласующ|чек-?лист|история изменени|содержани|оглавлени", re.I)


def stub_sections(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    secs = _sections(doc)
    by_line = _by_line(reqs)
    stubs = []
    for i, (lvl, title, hln, lines) in enumerate(secs):
        if _SKIP_STUB_HEAD.search(title):
            continue
        body = [ln for ln in lines if ln.text.strip()]
        if body and all(_STUB.match(ln.text) for ln in body):
            stubs.append((title, body[0]))
    if not stubs:
        return []
    names = ", ".join(f"«{t}»" for t, _ in stubs[:4])
    return [SetFinding(
        "gap", "set_complete", [_ref(by_line, ln, ln.text.strip()) for _t, ln in stubs[:3]],
        f"Раздел не заполнен — вместо содержания заглушка: {names}. Документ нельзя считать полным: без этого раздела "
        "не проверить требования (например, нет тест-кейсов и данных для тестирования).", "major",
        "Заполнить раздел до передачи документа в работу или явно указать, кто и к какому сроку его заполняет, и вынести "
        "это в открытые вопросы.", "правило")]


# ---------------------------------------------------------------- один объект — разные названия

_NAME_GROUPS = [
    # объект: варианты названий — замечание, если в документе есть хотя бы два разных. Пары вроде «клиент» /
    # «пользователь» ищет проход модели по синонимам (extras): там нужен контекст, правило дало бы дубль
    ("карта", [r"держател\w* (?:активн\w* )?карт\w*", r"владел\w* (?:активн\w* )?карт\w*", r"обладател\w* карт\w*"]),
    ("счёт", [r"держател\w* сч[её]т\w*", r"владел\w* сч[её]т\w*"]),
]


def same_object_names(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    by_line = _by_line(reqs)
    out = []
    for obj, pats in _NAME_GROUPS:
        found = []
        for p in pats:
            hit = next(((ln, m) for ln in doc.lines for m in [re.search(p, ln.text, re.I)] if m), None)
            if hit:
                found.append(hit)
        if len(found) < 2:
            continue
        names = [m.group(0) for _ln, m in found]
        out.append(SetFinding(
            "terminology", "set_comprehensible", [_ref(by_line, ln, m.group(0)) for ln, m in found[:3]],
            "Один и тот же участник назван по-разному: " + ", ".join(f"«{n}»" for n in names) + ". Неясно, один это "
            "человек или разные роли (например, держатель дополнительной карты и владелец счёта) — от этого зависят права "
            "и проверки доступа.", "minor",
            f"Выбрать один термин («{names[0]}»), определить его в разделе терминов и заменить остальные варианты.",
            "правило"))
    return out


# ---------------------------------------------------------------- ошибки API без машинного кода

_ERR_HEAD = re.compile(r"\b[45]\d\d\b|ошибк|error", re.I)
_ERR_JSON = re.compile(r'\{\s*"(?:message|error_message|errorMessage|text)"\s*:')
_CODE_KEY = re.compile(r'"(?:code|errorCode|error_code|errCode|status_code|reason)"\s*:', re.I)


def error_without_code(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    if any(_CODE_KEY.search(ln.text) for ln in doc.lines):
        return []
    by_line = _by_line(reqs)
    errs = []
    for lvl, title, _hln, lines in _sections(doc):
        if not _ERR_HEAD.search(title):
            continue
        for ln in lines:
            m = _ERR_JSON.search(ln.text)
            if m:
                errs.append((ln, ln.text.strip()))
                break
    if len(errs) < 2:
        return []
    return [SetFinding(
        "gap", "set_complete", [_ref(by_line, ln, frag) for ln, frag in errs[:3]],
        f"Ошибки API описаны только текстом сообщения ({len(errs)} ответов с полем message и без машинного кода): "
        "клиент не может надёжно различить причины (неверная сумма, нет доступа, карта не найдена) — только разбирая "
        "текст, который может измениться или быть переведён.", "minor",
        "Добавить в тело ошибки машинный код (например \"code\": \"AMOUNT_OUT_OF_RANGE\") и перечень кодов с описанием; "
        "текст message оставить для показа пользователю.", "правило")]


def v12_rules(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    out: list[SetFinding] = []
    for fn in (data_model_gaps, repeat_action, stub_sections, same_object_names, error_without_code):
        out.extend(fn(reqs, doc))
    return out
