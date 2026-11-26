"""Проверка требований: каждое по отдельности и набор целиком."""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field

from .criteria import INDIVIDUAL, SET, SEVERITY, criteria_prompt_block
from .llm import BaseLLM, LLMError, LLMFatalError
from .reader import Document
from .rules import RuleHit, check_requirement
from .splitter import MODAL_RE, Requirement, SplitResult
from .verify import norm, quote_in

DOC_CONTEXT_LIMIT = 60_000  # символов полного текста, передаваемого как контекст


@dataclass
class Finding:
    req_id: str
    criterion: str
    quote: str
    problem: str
    severity: str
    fix: str
    source: str  # "LLM" | "правило" | "LLM + правило" | "тест-проба"
    confidence: str = ""  # high | medium | low (после критика)
    critic_note: str = ""
    basis: list = field(default_factory=list)  # основания из базы знаний kb/: [{"source","section","quote","url"}]


@dataclass
class ReqResult:
    req: Requirement
    findings: list[Finding] = field(default_factory=list)
    rewrite: str = ""
    llm_checked: bool = True
    note: str = ""
    test_possible: bool | None = None  # результат Testability Probe
    test_gherkin: str = ""
    test_blocker: str = ""  # дословная цитата, мешающая составить тест
    test_reason: str = ""
    ears: str = ""  # тип по EARS
    test_scenarios: list = field(default_factory=list)  # [{"title", "gherkin"}] — 1–3 сценария
    rewrite_pattern: dict | None = None  # шаблон хорошего требования из kb/patterns, на который опирается правка
    category: str = ""  # функциональное / нефункциональное / интерфейс / интеграция / данные / регуляторное


@dataclass
class SetRef:
    req_id: str  # R-xxx или "DOC"
    quote: str


@dataclass
class SetFinding:
    kind: str
    criterion: str
    refs: list[SetRef]
    problem: str
    severity: str
    fix: str
    source: str
    confidence: str = ""
    critic_note: str = ""
    values: list = field(default_factory=list)  # конфликтующие значения: [{"rid", "value", "quote"}]
    basis: list = field(default_factory=list)


@dataclass
class ReviewResult:
    doc: Document
    split: SplitResult
    req_results: list[ReqResult]
    set_findings: list[SetFinding]
    dropped: list[dict]  # отброшенные (неподтверждённые) замечания LLM
    set_llm_checked: bool = True
    notes: list[str] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)  # отклонены критиком
    domain: object = None  # DomainResult (финтех-чек-лист)
    glossary: object = None  # GlossaryResult
    critic_used: bool = False
    critic_scope: str = ""  # "all" | "critical" (self-consistency в профиле fast)
    self_check: dict = field(default_factory=dict)  # v6: самосогласованность {"confirmed", "removed"}
    focus: dict = field(default_factory=dict)  # v6: узкие проходы {task: добавлено замечаний}
    critic_merged: int = 0  # v5: дубли, объединённые критиком (ушли в rejected с причиной «дубль S-xx»)
    rag: dict = field(default_factory=dict)  # статистика базы знаний: число оснований, режим поиска
    categories: dict = field(default_factory=dict)  # {категория: число требований}
    coverage: list = field(default_factory=list)  # карта покрытия шагов процесса домена
    depth: dict = field(default_factory=dict)  # v5: учёт строк, матрица критериев, покрытие приёмкой, вердикты, план


# ---------------------------------------------------------------- промпты

SYSTEM_REQ = f"""Ты — опытный аналитик требований и ревьюер спецификаций. Ты проводишь статическое ревью
документа требований ДО разработки (не запускаешь тесты). Оцени каждое переданное требование по критериям
ISO/IEC/IEEE 29148:2018 п. 5.2.5 и IEEE Std 830-1998 п. 4.3:
{criteria_prompt_block(INDIVIDUAL)}

Правила ответа:
1. Каждое замечание обязано содержать поле quote — ДОСЛОВНЫЙ фрагмент текста ЭТОГО требования (копируй символ в символ,
   3–15 слов, без перефразирования). Замечание без точной цитаты будет отброшено.
2. Не выдумывай проблем. Если требование хорошее по критерию — не пиши замечание. Пустой список findings допустим.
3. Не пиши общих фраз: problem объясняет, что именно не так в процитированном фрагменте; fix — конкретная
   исправленная формулировка или что именно добавить (числа, условия, субъект).
4. severity: "critical" — требование непроверяемо, противоречиво или настолько неполно, что его нельзя реализовать/протестировать;
   "major" — существенная двусмысленность/неполнота, риск неверной реализации; "minor" — оформление, стиль, мелкие уточнения.
5. hints — сигналы автоматического пред-фильтра (словарь размытых слов). Подтверди их отдельным замечанием, если это реальная
   проблема в контексте, или перечисли термин в dismissed_hints, если в контексте он допустим.
6. Учитывай контекст документа (глоссарий, другие разделы): не считай термин неопределённым, если он определён в документе.
7. suggested_rewrite — улучшенная формулировка требования целиком (одной строкой) или пустая строка, если правок не нужно.
   Формулируй по шаблону EARS, соответствующему типу требования.
8. ears — тип требования по EARS: ubiquitous («Система должна …»), event («Когда <событие>, система должна …»),
   state («Пока <состояние>, система должна …»), unwanted («Если <нежелательное событие>, то система должна …»),
   optional («Там, где <функция включена>, система должна …»), complex.
8a. Строки критериев приёмки (раздел «Критерии приёмки») и строки таблиц параметров API — это примеры и описание
   интерфейса, а не формулировки требований: не делай к ним замечаний по шаблону EARS («conforming»). Проверяй их
   содержательно: результат примера должен следовать из правил документа (период/дата, порог, исключения), формат и
   единицы параметра — совпадать с другими разделами. Пример, дающий результат не по правилу, — замечание «correct»
   (критичное) с цитатой примера; в problem назови правило, которому он противоречит.
9. test — Testability Probe: попробуй написать приёмочный тест для требования В ТЕКУЩЕЙ формулировке
   (Gherkin на русском: «Дано / Когда / Тогда», с конкретными значениями ИЗ ТЕКСТА требования, не выдумывай чисел).
   Если тест составить можно — possible=true и scenarios: 1–3 сценария (основной позитивный; негативный и/или
   граничный — если в тексте есть порог, лимит или условие ошибки), у каждого title и gherkin. Если нельзя (нет измеримого критерия, открытый список, TBD,
   субъективная оценка) — possible=false, reason (почему) и blocker_quote — ДОСЛОВНЫЙ фрагмент, который мешает.
10. Пиши на русском языке. Верни ТОЛЬКО JSON по схеме:
category — тип требования: functional | performance | availability | security | data | interface | integration | regulatory | acceptance | other.
{{"results":[{{"id":"R-001","ears":"event","category":"functional","findings":[{{"criterion":"<ключ критерия>","quote":"...","problem":"...","severity":"critical|major|minor","fix":"..."}}],"dismissed_hints":["..."],"suggested_rewrite":"...","test":{{"possible":true,"scenarios":[{{"title":"...","gherkin":"Дано ...\\nКогда ...\\nТогда ..."}}],"reason":"","blocker_quote":""}}}}]}}
Ключи критериев: {", ".join(INDIVIDUAL)}."""

SYSTEM_SET = f"""Ты — опытный аналитик требований. Проведи статическое ревью НАБОРА требований целиком по критериям
ISO/IEC/IEEE 29148:2018 п. 5.2.6 и IEEE Std 830-1998 п. 4.3:
{criteria_prompt_block(SET)}

Ищи прежде всего: противоречия между требованиями (contradiction), дубли и пересечения (duplicate), разнобой терминов
и единиц измерения (terminology), пропуски — обязательные для такой системы аспекты, которые не покрыты
(gap: ошибки и исключения, безопасность, производительность, роли и права, журналирование, ограничения, данные),
неопределённые ссылки и зависимости (dependency), проблемы структуры, приоритизации и трассируемости (structure).

Обязательно сверь между собой (это самые частые критичные дефекты):
- каждое правило с критериями приёмки и примерами: пример, дающий другой результат, чем правило (дата/период, порог,
  округление, часовой пояс), — противоречие с цитатами правила и примера;
- правила между собой: ограничение (например, «не более одного … за период») и исключение из него в другом пункте
  (что произойдёт, если оба условия выполняются одновременно — какое правило победит?);
- для каждого примера/критерия приёмки «пройди» его по правилам шаг за шагом (какая дата, какой период, какая сумма)
  и сравни с ожидаемым результатом примера; расхождение — противоречие (contradiction) с цитатами правила и примера;
- успешный код ответа, внутри которого возвращается ошибка, и ошибка валидации, описанная в разных местах разными кодами;
- спецификацию API саму с собой: назначение метода в описании, тип запроса (GET для изменения данных), URL всех сред,
  параметры и их форматы в запросе и ответе, заявленный Content-Type и наличие тела, перечень кодов ответа и примеры
  (код, указанный в одном месте и отличающийся в другом; ошибка внутри успешного кода; описанный, но не используемый код);
- единицы измерения одной величины в разных разделах (тенге/тиыны, секунды/минуты);
- незаполненные места шаблона: «—» вместо значения, «заполняется позже/тестировщиками», пустые таблицы и версии документа;
- CRUD-полноту API: экран показывает текущие значения или интеграция «читает» данные, а в API описан только метод
  изменения (save/update) — нет метода чтения; это critical gap (функцию нельзя реализовать целиком);
- контракт интеграции: расчёт строится на событиях/сообщениях внешней системы (процессинг, шина, очередь), но нигде нет
  состава полей события, перечня типов операций, гарантий доставки, порядка и обработки дублей — critical gap.

Правила ответа:
1. Каждое замечание содержит refs — список ссылок {{"id": "R-xxx", "quote": "дословный фрагмент текста этого требования"}}.
   Для противоречий и дублей — минимум две ссылки. Для пропуска — ссылка на требование или раздел, к которому относится
   пропуск; если требования нет, используй id "DOC" и дословную цитату из текста документа (например, заголовок раздела).
   Цитаты копируй символ в символ (3–15 слов). Замечание без подтверждённой цитаты будет отброшено.
2. Не выдумывай проблем и не пиши общих фраз: problem объясняет конкретную проблему со ссылкой на цитаты; fix — конкретное
   действие (какое требование добавить/изменить и как).
3. severity: "critical" — противоречие или пропуск, блокирующий разработку/тестирование; "major" — существенный риск;
   "minor" — оформление.
4. Пиши на русском языке. Верни ТОЛЬКО JSON по схеме:
{{"findings":[{{"type":"contradiction|duplicate|terminology|gap|dependency|structure|other","criterion":"<ключ критерия>","refs":[{{"id":"R-001","quote":"..."}}],"problem":"...","severity":"critical|major|minor","fix":"..."}}]}}
Ключи критериев: {", ".join(SET)}."""

SYSTEM_SPLIT = """Ты — аналитик требований. Выдели из документа отдельные требования (утверждения о том, что система/пользователь
должны делать или какими свойствами система должна обладать). Не придумывай и не переформулируй: quote — дословный
текст требования из документа. doc_id — идентификатор требования в документе, если он есть, иначе null.
Верни ТОЛЬКО JSON: {"requirements":[{"doc_id":null,"quote":"..."}]}"""


def _doc_context(doc: Document) -> str:
    t = doc.text
    if len(t) > DOC_CONTEXT_LIMIT:
        return t[:DOC_CONTEXT_LIMIT] + "\n[... текст обрезан ...]"
    return t


def _req_payload(r: Requirement, hints: list[RuleHit] | None = None) -> dict:
    d = {"id": r.rid, "doc_id": r.doc_id, "section": r.section, "text": r.text}
    if r.extra:
        d["attributes"] = r.extra
    if hints is not None:
        d["hints"] = [{"terms": h.terms or [h.term], "criterion": h.criterion, "quote": h.quote} for h in hints]
    return d


# ---------------------------------------------------------------- LLM-нарезка (запасной путь)

def llm_split(doc: Document, llm: BaseLLM) -> list[Requirement]:
    data = llm.generate_json(SYSTEM_SPLIT, "ДОКУМЕНТ:\n" + _doc_context(doc), task="split", context={"doc": doc})
    out: list[Requirement] = []
    for item in data.get("requirements", []):
        q = str(item.get("quote", "")).strip()
        if not q:
            continue
        line = next((l for l in doc.lines if quote_in(q[:60], l.text)), None)
        if line is None and not quote_in(q, doc.text):
            continue
        n = len(out) + 1
        out.append(Requirement(rid=f"R-{n:03d}", doc_id=item.get("doc_id") or None, text=" ".join(q.split()),
                               section="", line_start=line.lineno if line else 0,
                               line_end=line.lineno if line else 0, page=line.page if line else None))
    return out


# ---------------------------------------------------------------- проверка требований

def norm_refs(refs) -> list[dict]:
    """Ссылки замечания из ответа модели → [{"id", "quote"}]. Модель иногда возвращает строку вместо объекта
    («R-003: цитата» или просто цитату) или одиночный объект вместо списка — такие ответы не должны ронять прогон."""
    if isinstance(refs, (dict, str)):
        refs = [refs]
    out = []
    for ref in refs or []:
        if isinstance(ref, dict):
            out.append(ref)
        elif isinstance(ref, str) and re.fullmatch(r"\s*(R-\d{3}|DOC)\s*", ref):  # только ID, без цитаты
            out.append({"id": ref.strip(), "quote": ""})
        elif isinstance(ref, str) and ref.strip():
            m = re.match(r"^\s*(R-\d{3}|DOC)\s*[:—–-]\s*(.+)$", ref.strip())
            out.append({"id": m.group(1), "quote": m.group(2).strip().strip("«»\"")} if m else {"id": "DOC", "quote": ref.strip()})
    return out


def _norm_sev(s: str) -> str:
    s = str(s or "").lower().strip()
    if s in SEVERITY:
        return s
    if s.startswith(("крит", "high", "block")):
        return "critical"
    if s.startswith(("сущ", "med", "maj")):
        return "major"
    return "minor"


def _norm_crit(c: str, allowed: dict, default: str) -> str:
    c = str(c or "").strip().lower()
    if c in allowed:
        return c
    for k, v in allowed.items():
        if c and (c in v[0].lower() or c in k):
            return k
    return default


def check_requirements(reqs: list[Requirement], doc: Document, llm: BaseLLM, batch_size: int,
                       dropped: list[dict], log=print) -> list[ReqResult]:
    hints_by_req = {r.rid: check_requirement(r) for r in reqs}
    results = {r.rid: ReqResult(req=r) for r in reqs}
    llm_out: dict[str, dict] = {}
    from .rag.context import context_for, mode_for, record

    mode = mode_for(doc)
    full_ctx = _doc_context(doc) if mode == "full" else ""
    if mode == "rag":
        log(f"  длинный документ ({len(doc.text)} символов): контекст запросов собирается RAG-выборкой")

    batches = [reqs[i:i + batch_size] for i in range(0, len(reqs), batch_size)]
    for bi, batch in enumerate(batches, start=1):
        log(f"  проверка требований: пакет {bi}/{len(batches)} ({batch[0].rid}–{batch[-1].rid})")
        payload = [_req_payload(r, hints_by_req[r.rid]) for r in batch]
        ctx = full_ctx if mode == "full" else context_for(doc, [r.text for r in batch])
        title = "ПОЛНЫЙ ТЕКСТ ДОКУМЕНТА (контекст)" if mode == "full" else "КОНТЕКСТ ДОКУМЕНТА (оглавление, термины, релевантные фрагменты)"
        prompt = (f"НАЗВАНИЕ ДОКУМЕНТА: {doc.title}\n\n{title}:\n<<<\n{ctx}\n>>>\n\n"
                  f"ТРЕБОВАНИЯ ДЛЯ ПРОВЕРКИ (JSON):\n{json.dumps(payload, ensure_ascii=False, indent=1)}")
        record(doc, mode, len(SYSTEM_REQ) + len(prompt))
        try:
            data = llm.generate_json(SYSTEM_REQ, prompt, task="check", context={"reqs": batch, "hints": hints_by_req})
            for item in data.get("results", []) or []:
                if isinstance(item, dict):  # ответ модели не по схеме — пропускаем элемент
                    llm_out[str(item.get("id", "")).strip()] = item
        except LLMFatalError:
            raise
        except LLMError as e:
            for r in batch:
                results[r.rid].llm_checked = False
                results[r.rid].note = f"Модель не ответила ({e}); показаны только срабатывания правил."

    for r in reqs:
        res = results[r.rid]
        item = llm_out.get(r.rid)
        if item is None and res.llm_checked:
            res.llm_checked = False
            res.note = "Модель не вернула результат по этому требованию; показаны только срабатывания правил."
        dismissed = {norm(str(x)) for x in (item or {}).get("dismissed_hints", []) or []}
        for f in (item or {}).get("findings", []) or []:
            if not isinstance(f, dict):  # ответ модели не по схеме — пропускаем элемент
                continue
            quote = str(f.get("quote", "")).strip()
            if not quote_in(quote, r.text):
                dropped.append({"where": r.rid, "quote": quote, "problem": f.get("problem", "")})
                continue
            res.findings.append(Finding(r.rid, _norm_crit(f.get("criterion"), INDIVIDUAL, "unambiguous"), quote,
                                        str(f.get("problem", "")).strip(), _norm_sev(f.get("severity")),
                                        str(f.get("fix", "")).strip(), "LLM"))
        if item:
            res.rewrite = str(item.get("suggested_rewrite", "") or "").strip()
            res.ears = str(item.get("ears", "") or "").strip().lower()
            res.category = str(item.get("category", "") or "").strip().lower()
            _apply_test_probe(res, item.get("test") or {}, dropped)
        # срабатывания правил, которые модель не покрыла и не отклонила
        for h in hints_by_req[r.rid]:
            terms = [norm(t) for t in (h.terms or [h.term])]
            if all(t in dismissed for t in terms):
                continue
            covered = False
            for f in res.findings:
                if any(t in norm(f.quote) for t in terms) or (f.criterion == h.criterion and _overlap(f.quote, h.quote)):
                    if f.source == "LLM":
                        f.source = "LLM + правило"
                    covered = True
                    break
            if covered:
                continue
            if res.llm_checked and h.severity == "minor":
                continue  # мелкие сигналы без подтверждения модели не выводим, чтобы не шуметь
            res.findings.append(Finding(r.rid, h.criterion, h.quote, h.problem + f" (маркер: {h.terms_label or '«' + h.term + '»'})",
                                        h.severity, h.fix, "правило"))
        res.findings.sort(key=lambda f: {"critical": 0, "major": 1, "minor": 2}[f.severity])
    return [results[r.rid] for r in reqs]


def _apply_test_probe(res: ReqResult, t: dict, dropped: list[dict]) -> None:
    """Testability Probe: невозможность составить тест — доказательство непроверяемости."""
    if not isinstance(t, dict) or "possible" not in t:
        return
    r = res.req
    possible = bool(t.get("possible"))
    if possible:
        scen = []
        for x in (t.get("scenarios") or [])[:3]:
            if isinstance(x, dict) and str(x.get("gherkin", "")).strip():
                scen.append({"title": str(x.get("title", "") or "").strip() or (r.doc_id or r.rid),
                             "gherkin": str(x["gherkin"]).strip()})
        if not scen and str(t.get("gherkin", "") or "").strip():  # старый формат ответа — один сценарий
            scen = [{"title": r.doc_id or r.rid, "gherkin": str(t["gherkin"]).strip()}]
        res.test_scenarios = scen
        # для UI и Markdown — все сценарии одним текстом с заголовками «Сценарий:»
        g = "\n\n".join(f"Сценарий: {x['title']}\n" + "\n".join("  " + ln.strip() for ln in x["gherkin"].splitlines() if ln.strip())
                        for x in scen)
        if g:
            res.test_possible, res.test_gherkin = True, g
        return
    q = str(t.get("blocker_quote", "") or "").strip()
    reason = str(t.get("reason", "") or "").strip()
    if not quote_in(q, r.text):
        dropped.append({"where": r.rid + " (тест-проба)", "quote": q, "problem": reason})
        return
    res.test_possible, res.test_blocker, res.test_reason = False, q, reason
    for f in res.findings:
        if f.criterion == "verifiable":
            f.problem += f" Подтверждено тест-пробой: тест составить невозможно — {reason}"
            f.severity = "critical"
            return
    res.findings.append(Finding(r.rid, "verifiable", q, f"Тест составить невозможно: {reason}", "critical",
                                "Переформулировать так, чтобы появился объективный критерий приёмки (число, условие, ожидаемый результат).",
                                "тест-проба"))


def _overlap(a: str, b: str) -> bool:
    a, b = norm(a), norm(b)
    return a in b or b in a


# ---------------------------------------------------------------- проверка набора

def deterministic_set_checks(split: SplitResult, doc: Document) -> list[SetFinding]:
    out: list[SetFinding] = []
    reqs = split.requirements
    by_doc_id = {}
    for r in reqs:
        if r.doc_id:
            by_doc_id.setdefault(r.doc_id, []).append(r)
    for did, rs in by_doc_id.items():
        if len(rs) > 1:
            out.append(SetFinding("structure", "set_traceable", [SetRef(r.rid, r.text[:80]) for r in rs],
                                  f"Идентификатор «{did}» используется {len(rs)} раза(-ов) — требования нельзя однозначно трассировать.",
                                  "major", f"Присвоить уникальные идентификаторы требованиям с ID «{did}».", "правило"))
    # почти дубли
    for i in range(len(reqs)):
        for j in range(i + 1, len(reqs)):
            a, b = norm(reqs[i].text), norm(reqs[j].text)
            if min(len(a), len(b)) < 25:
                continue
            sm = difflib.SequenceMatcher(None, a, b)
            if sm.real_quick_ratio() < 0.85 or sm.quick_ratio() < 0.85:  # дешёвые верхние оценки — для длинных документов
                continue
            ratio = sm.ratio()
            if ratio >= 0.85:
                out.append(SetFinding("duplicate", "set_consistent",
                                      [SetRef(reqs[i].rid, reqs[i].text[:100]), SetRef(reqs[j].rid, reqs[j].text[:100])],
                                      f"Формулировки совпадают на {ratio:.0%} — вероятный дубль; при изменении одного второе останется прежним.",
                                      "major" if ratio < 0.98 else "minor",
                                      "Оставить одно требование, второе удалить или явно разграничить область применения.", "правило"))
    # модальные утверждения без идентификаторов
    if split.method == "ids":
        for ln, text in split.unnumbered[:15]:
            m = MODAL_RE.search(text) or MODAL_RE.search(ln.text)
            word = m.group(0) if m else "должен"
            out.append(SetFinding("structure", "set_traceable", [SetRef("DOC", text[:120])],
                                  f"Утверждение со словом «{word}» (строка {ln.lineno}) похоже на требование, "
                                  "но не имеет идентификатора — оно выпадает из трассировки и проверки.",
                                  "minor", "Присвоить идентификатор и оформить как требование, либо переформулировать как пояснение.",
                                  "правило"))
    # REST: метод GET у операции, меняющей данные (сохранение/изменение/удаление) — небезопасный и неидемпотентный по смыслу
    get_req = next((r for r in reqs if re.search(r"\b(?:rest type|http[- ]?метод|метод|method)\b[^|]*\|\s*GET\b", r.text, re.I)), None)
    if get_req:
        mut = re.compile(r"\b(?:save|update|create|delete|remove|set)[A-Z]\w*|/(?:save|update|create|delete|set)\w*|"
                         r"сохранени\w*|сохран\w+ настройк\w*|замени\w* настройк\w*|изменени\w* (?:порог|настройк)\w*|удалени\w*", re.I)
        # ближайшее к объявлению метода упоминание изменения данных (описание метода, URL, логика работы)
        near = sorted((r for r in reqs if r is not get_req and mut.search(r.text)),
                      key=lambda r: abs(r.line_start - get_req.line_start))
        mreq = near[0] if near and abs(near[0].line_start - get_req.line_start) <= 40 else None
        if mreq:
            mq = mut.search(mreq.text).group(0)
            out.append(SetFinding(
                "contradiction", "set_consistent",
                [SetRef(get_req.rid, get_req.text[:60]), SetRef(mreq.rid, _ctx(mreq.text, mq))],
                f"Метод объявлен как GET («{get_req.text[:40]}»), но выполняет изменение данных («{mq}»). GET по смыслу "
                "безопасен и не меняет состояние: такие запросы кэшируются, повторяются браузером и прокси, параметры "
                "попадают в логи и историю — сохранение порога через GET приведёт к непредсказуемым изменениям.",
                "critical", "Использовать POST/PUT (например, PUT /alerts/limit), параметры передать в теле JSON; "
                "GET оставить только для чтения настройки.", "правило"))
    out.extend(api_consistency(reqs, doc))
    from .depth import completeness_rules, integration_contract, missing_read_method  # v5: глубина

    out.extend(missing_read_method(reqs, doc))
    out.extend(integration_contract(reqs, doc))
    out.extend(completeness_rules(reqs, doc))
    # незаполненные значения для продуктивной среды («Prod: —»)
    for r in reqs:
        m = re.search(r"\b(?:prod|прод\w*|production)\s*:\s*[—–-](?=\s*(?:$|\.|\||;))", r.text, re.I)
        if m:
            out.append(SetFinding(
                "gap", "set_complete", [SetRef(r.rid, _ctx(r.text, m.group(0)))],
                f"Для продуктивной среды не указано значение («{m.group(0)}») — реализацию нельзя развернуть и проверить в Prod.",
                "critical", "Указать значение для Prod (URL/параметр) или явно зафиксировать, когда и кем оно будет определено.",
                "правило"))
    # ранжирование
    has_priority = any(
        any(re.search(r"приоритет|priority|важност", k, re.I) for k in r.extra) or
        re.search(r"\b(приоритет|must|should|could|высокий|средний|низкий)\b", r.text, re.I)
        for r in reqs)
    if reqs and not has_priority and not re.search(r"приоритет|priority", doc.text, re.I):
        out.append(SetFinding("structure", "set_ranked", [SetRef(reqs[0].rid, reqs[0].text[:80])],
                              "Ни у одного требования нет приоритета или признака стабильности (IEEE 830 §4.3.5) — "
                              "невозможно спланировать порядок реализации и объём MVP.",
                              "major", "Добавить атрибут «Приоритет» (например, MoSCoW) каждому требованию.", "правило"))
    return out


def check_set(split: SplitResult, doc: Document, llm: BaseLLM, dropped: list[dict], log=print) -> tuple[list[SetFinding], bool]:
    reqs = split.requirements
    by_id = {r.rid: r for r in reqs}
    found = deterministic_set_checks(split, doc)
    log("  проверка набора требований целиком")
    payload = [_req_payload(r) for r in reqs]
    from .rag.context import mode_for, outline

    doc_part = _doc_context(doc) if mode_for(doc) == "full" else outline(doc, 8000)  # длинный документ: оглавление + термины
    prompt = (f"НАЗВАНИЕ ДОКУМЕНТА: {doc.title}\n\nДОКУМЕНТ:\n<<<\n{doc_part}\n>>>\n\n"
              f"НАРЕЗКА ТРЕБОВАНИЙ (JSON):\n{json.dumps(payload, ensure_ascii=False, indent=1)}")
    try:
        data = llm.generate_json(SYSTEM_SET, prompt, task="set", context={"reqs": reqs, "doc": doc})
    except LLMFatalError:
        raise
    except LLMError:
        add_numeric_conflicts(found, reqs, log)
        return found, False
    for f in data.get("findings", []) or []:
        if not isinstance(f, dict):  # ответ модели не по схеме — пропускаем элемент
            continue
        refs: list[SetRef] = []
        bad = False
        for ref in norm_refs(f.get("refs")):
            rid = str(ref.get("id", "")).strip()
            q = str(ref.get("quote", "")).strip()
            src = by_id[rid].text if rid in by_id else doc.text
            if rid not in by_id:
                rid = "DOC"
            if not quote_in(q, src):
                bad = True
                dropped.append({"where": rid, "quote": q, "problem": f.get("problem", "")})
                continue
            refs.append(SetRef(rid, q))
        kind = str(f.get("type", "other")).strip().lower()
        need = 2 if kind in ("contradiction", "duplicate") else 1
        if len(refs) < need:
            if not bad:
                dropped.append({"where": "набор", "quote": "", "problem": f.get("problem", "")})
            continue
        found.append(SetFinding(kind, _norm_crit(f.get("criterion"), SET, "set_consistent"), refs,
                                str(f.get("problem", "")).strip(), _norm_sev(f.get("severity")),
                                str(f.get("fix", "")).strip(), "LLM"))
    add_numeric_conflicts(found, reqs, log)
    crosscheck(split, doc, llm, dropped, found, log)
    from .depth import completeness_pass  # v5: узкий проход полноты по чек-листу (1 запрос)

    completeness_pass(split, doc, llm, dropped, found, log)
    found.sort(key=lambda f: {"critical": 0, "major": 1, "minor": 2}[f.severity])
    return found, True


def add_numeric_conflicts(found: list[SetFinding], reqs: list[Requirement], log=print) -> None:
    """Числовые противоречия (детерминированно, numbers.py). Если модель уже нашла противоречие по той же паре —
    помечаем его как подтверждённое правилом и добавляем конфликтующие значения; иначе — новое замечание."""
    from .numbers import find_conflicts

    by_id = {r.rid: r for r in reqs}
    lbl = lambda rid: rid + (f" ({by_id[rid].doc_id})" if by_id[rid].doc_id else "")  # noqa: E731
    conflicts = find_conflicts(reqs)
    if conflicts:
        log(f"  числовые противоречия (правило): {len(conflicts)}")
    for c in conflicts:
        values = [{"rid": c.a.rid, "value": c.a.raw, "quote": c.a.quote}, {"rid": c.b.rid, "value": c.b.raw, "quote": c.b.quote}]
        pair = {c.a.rid, c.b.rid}
        same = next((f for f in found if f.kind == "contradiction" and pair <= {r.req_id for r in f.refs}), None)
        if same:
            if "правило" not in same.source:
                same.source = same.source + " + правило"
            same.values = values
            same.severity = "critical"
            continue
        found.append(SetFinding(
            "contradiction", "set_consistent",
            [SetRef(c.a.rid, c.a.quote), SetRef(c.b.rid, c.b.quote)],
            f"Числовое противоречие: {lbl(c.a.rid)} — «{c.a.raw}», {lbl(c.b.rid)} — «{c.b.raw}» ({c.reason}). "
            "Реализовать и протестировать оба требования одновременно невозможно.",
            "critical",
            f"Согласовать одно значение с владельцем требований и оставить его в одном требовании "
            f"(второе — ссылкой на первое), например: заменить «{c.b.raw}» на «{c.a.raw}» или наоборот.",
            "правило", values=values))


def run_review(doc: Document, split: SplitResult, llm: BaseLLM, batch_size: int = 8, log=print,
               on_set=lambda: None) -> ReviewResult:
    dropped: list[dict] = []
    req_results = check_requirements(split.requirements, doc, llm, batch_size, dropped, log=log)
    on_set()
    set_findings, set_ok = check_set(split, doc, llm, dropped, log=log)
    return ReviewResult(doc=doc, split=split, req_results=req_results, set_findings=set_findings,
                        dropped=dropped, set_llm_checked=set_ok)


def _ctx(text: str, frag: str, width: int = 30) -> str:
    """Дословная цитата вокруг фрагмента (для ссылок замечаний набора)."""
    i = text.find(frag)
    if i < 0:
        return frag
    s, e = max(0, i - width), min(len(text), i + len(frag) + width)
    if s > 0 and " " in text[s:i]:  # цитата начинается с целого слова
        s = text.index(" ", s) + 1
    if e < len(text) and " " in text[i + len(frag):e]:
        e = text.rindex(" ", i + len(frag), e)
    return text[s:e].strip()


# ---------------------------------------------------------------- перекрёстная проверка: примеры ↔ правила, правило ↔ правило

SYSTEM_CROSS = """Ты — тест-аналитик. Тебе даны ПРАВИЛА (требования) и ПРИМЕРЫ (критерии приёмки) одного документа.
Для КАЖДОГО примера выполни его по правилам шаг за шагом: какая дата/период, какие операции учитываются, какая сумма,
сработает ли порог, сколько уведомлений. Сравни с ожидаемым результатом примера. Если результат по правилам другой —
это противоречие: укажи правило и пример. Только реальные противоречия; в refs — дословные цитаты (3–15 слов, символ
в символ) из правила и примера с их id; в problem — пошаговое объяснение. Пиши по-русски. Верни ТОЛЬКО JSON:
{"findings":[{"type":"contradiction","criterion":"set_consistent","refs":[{"id":"R-001","quote":"..."},{"id":"R-002","quote":"..."}],"problem":"...","severity":"critical|major","fix":"..."}]}"""

SYSTEM_RULES = """Ты — аналитик требований. Тебе даны ПРАВИЛА одного документа. Ищи КОНФЛИКТЫ МЕЖДУ ПРАВИЛАМИ:
для каждой пары правил придумай конкретную ситуацию (последовательность событий), в которой оба правила применимы.
Дают ли они разный результат? Типичные случаи: ограничение «не более N раз за период» и правило, которое требует
действия ещё раз в том же периоде («независимо от истории», «после изменения настройки»); правило «сохраняется» и
правило «сбрасывается»; разные пороги/единицы одной величины. Опиши ситуацию по шагам и какое правило что требует.
Только реальные конфликты; в refs — дословные цитаты (3–15 слов, символ в символ) обоих правил с их id.
Пиши по-русски. Верни ТОЛЬКО JSON:
{"findings":[{"type":"contradiction","criterion":"set_consistent","refs":[{"id":"R-001","quote":"..."},{"id":"R-002","quote":"..."}],"problem":"...","severity":"critical|major","fix":"..."}]}"""

_RULE_SECTION = re.compile(r"функциональн|правил|логика|бизнес", re.I)
_EXAMPLE_SECTION = re.compile(r"критери\w* при[её]мк|пример|сценари", re.I)


def crosscheck(split: SplitResult, doc: Document, llm: BaseLLM, dropped: list[dict], found: list[SetFinding], log=print) -> None:
    reqs = split.requirements
    rules = [r for r in reqs if r.doc_id or _RULE_SECTION.search(r.section or "")]
    examples = [r for r in reqs if _EXAMPLE_SECTION.search(r.section or "")]
    rules = [r for r in rules if r not in examples]
    if len(rules) < 2 and not examples:
        return
    log(f"  перекрёстная проверка: {len(examples)} примеров × {len(rules)} правил")
    by_id = {r.rid: r for r in reqs}
    rule_payload = [{"id": r.rid, "doc_id": r.doc_id, "text": r.text} for r in rules]
    tasks = []
    if examples:
        tasks.append((SYSTEM_CROSS, {"ПРАВИЛА": rule_payload, "ПРИМЕРЫ": [{"id": r.rid, "text": r.text, "columns": r.extra}
                                                                       for r in examples]}))
    if len(rules) >= 2:
        tasks.append((SYSTEM_RULES, {"ПРАВИЛА": rule_payload}))
    results = []
    for system, payload in tasks:
        try:
            results.append(llm.generate_json(system, json.dumps(payload, ensure_ascii=False, indent=1), task="crosscheck",
                                             context={"rules": rules, "examples": examples}))
        except LLMFatalError:
            raise
        except LLMError as e:
            log(f"  перекрёстная проверка: часть пропущена ({e})")
    data = {"findings": [f for d in results for f in (d.get("findings") or [])]}
    have = {frozenset(r.req_id for r in f.refs) for f in found if f.kind == "contradiction"}
    for f in data.get("findings", []) or []:
        if not isinstance(f, dict):  # ответ модели не по схеме — пропускаем элемент
            continue
        refs = []
        for ref in norm_refs(f.get("refs")):
            rid, q = str(ref.get("id", "")).strip(), str(ref.get("quote", "")).strip()
            if rid in by_id and quote_in(q, by_id[rid].text):
                refs.append(SetRef(rid, q))
            else:
                dropped.append({"where": rid or "набор", "quote": q, "problem": f.get("problem", "")})
        if len({r.req_id for r in refs}) < 2 or frozenset(r.req_id for r in refs) in have:
            continue
        have.add(frozenset(r.req_id for r in refs))
        found.append(SetFinding("contradiction", "set_consistent", refs, str(f.get("problem", "")).strip(),
                                "critical" if _norm_sev(f.get("severity")) == "critical" else "major",
                                str(f.get("fix", "")).strip(), "LLM (перекрёстная проверка)"))


def api_consistency(reqs: list[Requirement], doc: Document) -> list[SetFinding]:
    """Детерминированная сверка API-спецификации: типы одного параметра в разных таблицах, коды ответа,
    описанные под одним заголовком, но возвращаемые другие, и ошибка внутри успешного кода ответа."""
    out: list[SetFinding] = []
    # 1) один параметр — разные форматы (запрос vs ответ)
    fmt_key = lambda e: next((e[k] for k in e if k.lower() in ("format", "формат", "тип", "type")), "")  # noqa: E731
    name_key = lambda e: next((e[k] for k in e if k.lower() in ("parameter", "параметр", "поле", "field", "name")), "")  # noqa: E731
    params: dict[str, list[Requirement]] = {}
    for r in reqs:
        n, f = name_key(r.extra).strip("`"), fmt_key(r.extra)
        if n and f:
            params.setdefault(n, []).append(r)
    for n, rs in params.items():
        fmts = {fmt_key(r.extra).lower() for r in rs}
        if len(fmts) > 1:
            a, b = rs[0], next(r for r in rs[1:] if fmt_key(r.extra).lower() != fmt_key(rs[0].extra).lower())
            out.append(SetFinding(
                "terminology", "set_consistent", [SetRef(a.rid, a.text[:60]), SetRef(b.rid, b.text[:60])],
                f"Параметр «{n}» описан с разными форматами: {fmt_key(a.extra)} ({a.section}) и {fmt_key(b.extra)} "
                f"({b.section}). Клиент и сервер по-разному сериализуют значение — ошибки разбора и сравнения.",
                "major", f"Задать единый формат «{n}» во всех таблицах (например, integer) и пример ответа в том же формате.",
                "правило"))
    # 2) коды ответа: объявленные и фактически возвращаемые
    declared = {m.group(1) for line in doc.lines for m in [re.match(r"^\s*(?:\*\*|#+\s*)(\d{3})\.", line.text)] if m}
    for r in reqs:
        for m in re.finditer(r"возвраща\w+\s+(\d{3})", r.text):
            code = m.group(1)
            sec = re.match(r"^(\d{3})\.", r.section or "")
            q = _ctx(r.text, m.group(0))
            if sec and sec.group(1) != code:
                out.append(SetFinding(
                    "contradiction", "set_consistent", [SetRef(r.rid, q)],
                    f"Раздел ответа {sec.group(1)} («{r.section}») сообщает, что на самом деле возвращается {code}. Описанный "
                    f"код {sec.group(1)} не используется, клиент не узнает, какой код обрабатывать.",
                    "major", f"Оставить один код для этого случая и описать его в перечне статусов (например, только {code} "
                             f"или только {sec.group(1)}), убрать противоречивый раздел.", "правило"))
            elif declared and code not in declared:
                out.append(SetFinding(
                    "gap", "set_complete", [SetRef(r.rid, q)],
                    f"Код {code} упоминается в логике, но отсутствует в перечне статусов ответа ({', '.join(sorted(declared))}).",
                    "major", f"Добавить код {code} в перечень статусов с описанием и примером тела ответа.", "правило"))
    # 3) ошибка внутри успешного кода ответа (пример «ERROR» в разделе 2xx)
    code, in_fence = "", False
    for ln in doc.lines:
        t = ln.text.strip()
        h = re.match(r"^#+\s*(\d{3})\b", t)
        if h:
            code = h.group(1)
            continue
        if t.startswith("```"):
            in_fence = not in_fence
            continue
        # пример тела — в блоке кода (Markdown) или отдельной строкой-JSON (DOCX, PDF: блоков кода там нет)
        if (in_fence or t.startswith("{")) and code.startswith("2") and re.search(r'"result"\s*:\s*"(?:ERROR|FAIL\w*)"|"error"\s*:', t, re.I):
            bad = next((r for r in reqs if re.match(r"^400\.", r.text)), None)
            refs = [SetRef("DOC", t)] + ([SetRef(bad.rid, bad.text[:60])] if bad else [])
            out.append(SetFinding(
                "contradiction", "set_consistent", refs,
                f"В разделе успешного ответа {code} приведён пример с ошибкой ({t[:60]}), а для неверных параметров "
                "описан код 400. Непонятно, каким кодом сервис сообщает об отклонённой сумме — клиент может принять ошибку за успех.",
                "critical", "Возвращать ошибку валидации суммы только кодом 400 с телом {\"message\": …}; в разделе 200 "
                            "оставить только успешный ответ.", "правило"))
            break
    return out
