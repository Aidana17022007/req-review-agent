"""Доменная экспертиза (финтех-чек-лист полноты) и глоссарий/согласованность терминов.

Обе проверки делаются ОДНИМ обращением к модели (экономия квоты бесплатного тарифа).
Всё, что модель называет «покрыто», подтверждается дословными цитатами из документа;
без подтверждённой цитаты область считается не покрытой.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .checker import ReviewResult, SetFinding, SetRef
from .llm import BaseLLM, LLMError, LLMFatalError
from .verify import norm, quote_in

DOMAINS_DIR = Path(__file__).parent / "domains"

STOP = set("""это для при или как что так все его она они оно также если когда чтобы который которая которые должен должна должно
должны может могут быть было будет системы система сервис клиент через после более менее каждый данные данных между только
""".split())


@dataclass
class AreaResult:
    id: str
    title: str
    status: str  # covered | partial | missing
    quotes: list[str]
    comment: str
    question: str


@dataclass
class DomainResult:
    name: str
    disclaimer: str
    areas: list[AreaResult]

    @property
    def coverage_pct(self) -> int:
        if not self.areas:
            return 0
        score = sum(1 if a.status == "covered" else 0.5 if a.status == "partial" else 0 for a in self.areas)
        return round(100 * score / len(self.areas))


@dataclass
class Term:
    term: str
    definition: str = ""
    count: int = 0
    defined: bool = False
    reqs: list[str] = field(default_factory=list)


@dataclass
class GlossaryResult:
    terms: list[Term]
    synonyms: list[dict]  # {"terms": [...], "preferred": str, "problem": str}


def load_domain(name: str) -> dict | None:
    if not name or name == "none":
        return None
    p = DOMAINS_DIR / f"{name}.yaml"
    if not p.exists():
        raise ValueError(f"Домен «{name}» не найден. Доступны: " + ", ".join(x.stem for x in DOMAINS_DIR.glob("*.yaml") if not x.stem.endswith(".rules")))
    import yaml

    return yaml.safe_load(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- глоссарий (детерминированно)

DEF_RE = re.compile(r"^\s*(?:[-*•]\s+)?(?:\*\*)?(?P<term>[A-ZА-ЯЁ][\wА-Яа-яЁё \-]{1,40}?)(?:\*\*)?\s+[—–-]\s+(?P<def>.{5,})$")


def extract_glossary(rv: ReviewResult) -> list[Term]:
    doc = rv.doc
    terms: dict[str, Term] = {}
    in_terms = False
    for l in doc.lines:
        t = l.text.strip()
        if t.startswith("#"):
            in_terms = bool(re.search(r"термин|определени|глоссари|сокращени|glossary|terms", t, re.I))
            continue
        if in_terms:
            m = DEF_RE.match(t)
            if m:
                name = m.group("term").strip()
                terms[name.lower()] = Term(name, m.group("def").strip(), defined=True)
    words = Counter()
    for r in rv.split.requirements:
        for w in re.findall(r"[А-Яа-яЁёA-Za-z]{5,}", r.text):
            lw = w.lower()
            if lw not in STOP:
                words[lw[:7]] += 1
    for key, term in terms.items():
        stem = key[:7]
        term.count = words.get(stem, 0)
        term.reqs = [r.rid for r in rv.split.requirements if stem in r.text.lower()]
    frequent = [w for w, c in words.most_common(40) if c >= 3 and not any(w in k for k in terms)]
    for w in frequent[:12]:
        full = next((m.group(0) for r in rv.split.requirements for m in re.finditer(w + r"[а-яёa-z]*", r.text, re.I)), w)
        terms[w] = Term(full, "", words[w], False, [r.rid for r in rv.split.requirements if w in r.text.lower()])
    return sorted(terms.values(), key=lambda t: (-t.defined, -t.count))


# ---------------------------------------------------------------- один запрос к модели

SYSTEM_EXTRAS = """Ты — аналитик требований банковских систем. Выполни две задачи по документу требований.
1) coverage: для каждой области из списка AREAS определи, покрыта ли она требованиями документа:
   "covered" — есть конкретные требования; "partial" — упомянута, но без деталей; "missing" — не упомянута.
   quotes — ДОСЛОВНЫЕ фрагменты документа (3–15 слов), на которых основан вывод. Без цитат covered/partial не засчитываются.
2) synonyms: найди группы разных терминов, которыми документ называет ОДНО И ТО ЖЕ понятие
   (например «клиент» / «пользователь» / «абонент»). Каждый термин в группе должен дословно встречаться в документе.
   preferred — какой термин оставить; problem — чем опасен разнобой.
Пиши на русском. Верни ТОЛЬКО JSON:
{"coverage":[{"id":"auth","status":"covered|partial|missing","quotes":["..."],"comment":"..."}],
 "synonyms":[{"terms":["клиент","пользователь"],"preferred":"клиент","problem":"..."}]}"""


def extras_call(rv, llm: BaseLLM, domain: dict | None):
    """Запрос доменной проверки и глоссария (зависит только от документа и нарезки) → (термины, ответ | исключение).
    v13: вызывается заранее, параллельно с проверкой требований и набора (prefetch в review_document)."""
    doc = rv.doc
    terms = extract_glossary(rv)
    areas = (domain or {}).get("areas", [])
    payload = {"AREAS": [{"id": a["id"], "title": a["title"]} for a in areas],
               "TERMS_CANDIDATES": [t.term for t in terms]}
    text = doc.text[:60_000]
    try:
        return terms, llm.generate_json(SYSTEM_EXTRAS, f"ДОКУМЕНТ:\n<<<\n{text}\n>>>\n\nВХОДНЫЕ ДАННЫЕ:\n"
                                        f"{json.dumps(payload, ensure_ascii=False)}", task="extras",
                                        context={"doc": doc, "areas": areas})
    except LLMFatalError:
        raise
    except LLMError as e:
        return terms, e


def run_extras(rv: ReviewResult, llm: BaseLLM, domain: dict | None, log=print, prefetched=None) -> None:
    doc = rv.doc
    areas = (domain or {}).get("areas", [])
    log("  доменная проверка полноты и глоссарий")
    terms, data = prefetched.result() if prefetched is not None else extras_call(rv, llm, domain)
    if isinstance(data, Exception):
        e = data
        rv.notes.append(f"Доменная проверка и глоссарий не выполнены: модель не ответила ({e}).")
        rv.glossary = GlossaryResult(terms, [])
        return

    # --- домен
    if domain:
        got = {str(c.get("id")): c for c in data.get("coverage", []) or []}
        res = []
        for a in areas:
            c = got.get(a["id"], {})
            quotes = [q for q in (c.get("quotes") or []) if isinstance(q, str) and quote_in(q, doc.text)]
            status = str(c.get("status", "missing")).lower()
            if status not in ("covered", "partial", "missing"):
                status = "missing"
            if status != "missing" and not quotes:
                status = "missing"
            res.append(AreaResult(a["id"], a["title"], status, quotes[:3], str(c.get("comment", "") or ""), a.get("question", "")))
        rv.domain = DomainResult(domain.get("name", ""), domain.get("disclaimer", ""), res)
        anchor = _anchor(rv)
        missing = [a for a in res if a.status == "missing"]
        if missing:
            rv.set_findings.append(SetFinding(
                "gap", "set_complete", [SetRef("DOC", anchor)],
                "Не покрыты области, типовые для банковского продукта (по доменному чек-листу): "
                + "; ".join(a.title for a in missing) + ".",
                "major" if len(missing) >= 3 else "minor",
                "Добавить требования или явно зафиксировать, что области вне рамок проекта. Вопросы заказчику: "
                + " ".join(f"{a.title}: {a.question}" for a in missing[:6]),
                "домен"))

    # --- глоссарий / синонимы
    syn_ok = []
    low = norm(doc.text)
    for s in data.get("synonyms", []) or []:
        ts = [str(t).strip() for t in s.get("terms", []) or [] if str(t).strip()]
        ts = [t for t in ts if norm(t) in low]
        if len(ts) < 2:
            continue
        syn_ok.append({"terms": ts, "preferred": str(s.get("preferred", ts[0])), "problem": str(s.get("problem", ""))})
        refs = []
        for t in ts:
            r = next((r for r in rv.split.requirements if norm(t) in norm(r.text)), None)
            refs.append(SetRef(r.rid, t) if r else SetRef("DOC", t))
        rv.set_findings.append(SetFinding(
            "terminology", "set_comprehensible", refs,
            f"Одно понятие названо по-разному: {', '.join('«' + t + '»' for t in ts)}. {s.get('problem', '')}".strip(),
            "minor", f"Использовать единый термин «{s.get('preferred', ts[0])}» и определить его в разделе терминов.", "LLM"))
    rv.glossary = GlossaryResult(terms, syn_ok)


def _anchor(rv: ReviewResult) -> str:
    for l in rv.doc.lines:
        t = l.text.strip().lstrip("#").strip()
        if t and quote_in(t, rv.doc.text):
            return t[:120]
    return rv.doc.title
