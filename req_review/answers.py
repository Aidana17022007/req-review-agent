"""v9: ответы аналитика на вопросы отчёта → перепроверка.

Поток: отчёт пишет шаблон `<отчёт>_answers_template.md` (все вопросы с заголовками «### Q-xx»); аналитик вписывает
ответы; `python review.py <док> <отчёт> --answers answers.md` проверяет документ заново и учитывает ответы:

- конкретный ответ (значение, перечень, решение) → связанные замечания закрыты: уходят в `rejected` с причиной
  «закрыто ответом Q-xx», а в исправленный документ попадает формулировка с этими значениями;
- уклончивый («уточним позже», «TBD») → замечания остаются открытыми с пометкой;
- противоречивый (значение не совпадает ни с одним из значений документа или с другим ответом) → замечания остаются,
  добавляется новое замечание набора «ответ противоречив» с дословной цитатой ответа.

Ничего не закрывается без дословной цитаты ответа. Тип определяют правила; модель (задача "answers") может уточнить
тип и цитату, но правила проверяют её вывод: цитата обязана быть подстрокой ответа, противоречие по числам —
приоритетнее «конкретного».
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .checker import SetFinding, SetRef

HEAD_RE = re.compile(r"^#{2,4}\s*(Q-\d{2,3})\b[^\n]*$", re.M)
KEY_RE = re.compile(r"<!--\s*reqlens:\s*(\S+)\s+(\S*)(?:\s+(\S+))?\s*-->")
EVASIVE_RE = re.compile(
    r"уточн\w*\s+(позже|потом|после|дополнительно|с\s)|позже|после пилота|\bTBD\b|\bTBA\b|не знаю|затрудня\w*|обсуд\w*|"
    r"на усмотрение|по согласованию|решим|пока не (определ|решен|извест)|будет определ\w*|определ\w* позже|"
    r"в процессе|нет информации|не готов\w*|вернёмся|вернемся|\?\s*$", re.I)
CONCRETE_RE = re.compile(
    r"\d|только|не используется|не требуется|не нужн|обязательн|не более|не менее|не позднее|в течение|≤|≥|<=|>=|"
    r"\bда\b|\bнет\b|допускается|запрещ\w*|исключ\w*|отказ\w*|должн\w*|https?://|согласован\w*|\bметод\w*|"
    r"\b(GET|PUT|POST|PATCH|DELETE)\b", re.I)
NUM_RE = re.compile(r"(\d[\d\s\u00a0\u202f]*(?:[.,]\d+)?)\s*(%|тенге|₸|тг|руб\w*|сек\w*|с\b|мин\w*|час\w*|дн\w*|сут\w*|"
                    r"мс\b|раз\w*|попыт\w*|символ\w*|запрос\w*|МБ|ГБ)?", re.I)
TYPES = ("concrete", "evasive", "contradictory")
TYPE_RU = {"concrete": "конкретный", "evasive": "уклончивый", "contradictory": "противоречивый"}

SYSTEM_ANSWERS = """Ты — эксперт по анализу требований. Тебе дают вопросы к документу требований и ответы аналитика.
Для каждого ответа определи тип:
- concrete — ответ даёт конкретное значение, перечень или решение, которое закрывает вопрос;
- evasive — ответ уклончивый: обещает уточнить позже, не называет значения, «TBD», «по согласованию»;
- contradictory — ответ противоречит документу (значение не совпадает с тем, что в документе) или другому ответу.
quote — ДОСЛОВНЫЙ фрагмент ответа (подстрока), на котором основан вывод. note — коротко, что закрыто или почему открыто.
Пиши на русском. Верни ТОЛЬКО JSON: {"items":[{"qid":"Q-01","type":"concrete|evasive|contradictory","quote":"…","note":"…"}]}"""


@dataclass
class AnswerItem:
    qid: str
    question: str
    answer: str
    type: str
    closes: list = field(default_factory=list)
    quote: str = ""
    note: str = ""


# ------------------------------------------------------------------ шаблон и разбор

def template_md(questions, title: str) -> str:
    """Шаблон ответов: все вопросы с заголовками «### Q-xx», ссылки на замечания и пустое место для ответа."""
    out = [f"# Ответы аналитика — {title}", "",
           "> Впишите ответ под каждым вопросом (вместо строки «Ответ:») и запустите перепроверку:",
           "> `python review.py <документ> <отчёт>.md --answers <этот файл>`.",
           "> Конкретный ответ (значение, перечень, решение) закрывает замечания; «уточним позже» оставляет их открытыми.",
           "> Вопросы без ответа можно удалить или оставить пустыми. Служебные строки `<!-- reqlens … -->` не трогайте.", ""]
    for q in questions:
        out += [f"### {q.qid}. {q.ref} — {q.section}", "",
                f"<!-- reqlens: {q.rid or q.ref} {q.criterion}" + (f" {','.join(q.refs)}" if q.refs else "") + " -->",
                f"**Вопрос.** {q.text}", "",
                f"*Закроет замечания:* {', '.join(q.closes) if q.closes else '—'}", "",
                "Ответ: ", ""]
    return "\n".join(out).rstrip() + "\n"


def parse_answers(text: str) -> dict[str, dict]:
    """{qid: {"answer", "key": (rid, criterion) | None}} — только непустые ответы."""
    out: dict[str, dict] = {}
    heads = list(HEAD_RE.finditer(text))
    for i, m in enumerate(heads):
        body = text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        km = KEY_RE.search(body)
        key = (km.group(1), km.group(2), km.group(3) or "") if km else None
        lines = []
        for ln in body.splitlines():
            s = ln.strip()
            if not s or s.startswith(("<!--", ">")) or s.startswith(("**Вопрос.**", "*Закроет замечания:*", "**Вопрос**")):
                continue
            s = re.sub(r"^(\*\*)?Ответ(\*\*)?\s*[:.]\s*(\*\*)?\s*", "", s, flags=re.I)
            if s:
                lines.append(s)
        ans = " ".join(lines).strip()
        if ans:
            out[m.group(1)] = {"answer": ans, "key": key}
    return out


# ------------------------------------------------------------------ классификация

def _norm(s: str) -> str:
    return " ".join(str(s).replace("ё", "е").replace("\u00a0", " ").replace("\u202f", " ").split()).lower()


def _numbers(s: str) -> list[float]:
    out = []
    for m in NUM_RE.finditer(s or ""):
        raw = re.sub(r"[\s\u00a0\u202f]", "", m.group(1)).replace(",", ".")
        try:
            out.append(float(raw))
        except ValueError:
            continue
    return out


def _sentence(answer: str, pat: re.Pattern) -> str:
    """Предложение ответа, где сработал признак, — дословно (подстрока ответа)."""
    parts = re.split(r"(?<=[.!?;])\s+", answer)
    for p in parts:
        if pat.search(p):
            return p.strip().rstrip(".;")
    return parts[0].strip().rstrip(".;")


UNIT_GROUPS = {"money": r"тенге|₸|тг|тиын\w*", "percent": r"%", "time": r"сек\w*|с\b|мин\w*|час\w*|мс\b|дн\w*|сут\w*"}
_UNIT_NUM = re.compile(r"(\d[\d\s\u00a0\u202f]*(?:[.,]\d+)?)\s*(" + "|".join(UNIT_GROUPS.values()) + ")", re.I)
NUMERIC_CHECK = {"set_consistent", "correct"}  # вопросы «что верно» — новое значение той же единицы = противоречие


def _unit_numbers(s: str) -> dict[str, set[float]]:
    out: dict[str, set[float]] = {}
    for m in _UNIT_NUM.finditer(s or ""):
        unit = next(g for g, p in UNIT_GROUPS.items() if re.fullmatch(p, m.group(2), re.I))
        try:
            out.setdefault(unit, set()).add(float(re.sub(r"[\s\u00a0\u202f]", "", m.group(1)).replace(",", ".")))
        except ValueError:
            continue
    return out


def _conflict_values(q, rv) -> list[float]:
    """Значения документа, с которыми должен совпасть ответ: противоречие набора (values)."""
    if q.rid.startswith("S-"):
        try:
            f = rv.set_findings[int(q.rid[2:]) - 1]
        except (ValueError, IndexError):
            return []
        if f.criterion == "set_consistent" and f.values:
            return [n for v in f.values for n in _numbers(v.get("value", ""))]
    return []


def _unit_conflict(q, answer: str, rv) -> str:
    """Для вопросов «что верно»: число с единицей (₸, %, время), которого нет в затронутых требованиях, — противоречие."""
    if getattr(q, "criterion", "") not in NUMERIC_CHECK:
        return ""
    texts = {rr.req.rid: rr.req.text for rr in rv.req_results} if hasattr(rv, "req_results") else {}
    rids = [q.rid] if q.rid in texts else list(getattr(q, "refs", []) or [])
    doc = _unit_numbers(" ".join(texts.get(r, "") for r in rids))
    ans = _unit_numbers(answer)
    for unit, vals in ans.items():
        new = vals - doc.get(unit, set())
        if doc.get(unit) and new:
            shown = ", ".join(f"{v:,.0f}".replace(",", " ") for v in sorted(doc[unit]))
            return f"В ответе {', '.join(f'{v:,.0f}'.replace(',', ' ') for v in sorted(new))}, а в документе — {shown}"
    return ""


def classify_rules(q, answer: str, rv) -> tuple[str, str, str]:
    """(type, quote, note) по правилам; quote — дословная подстрока ответа."""
    nums = _numbers(answer)
    doc_vals = _conflict_values(q, rv)
    if doc_vals and nums and not any(abs(n - v) < 1e-9 for n in nums for v in doc_vals):
        quote = _sentence(answer, re.compile(r"\d"))
        shown = ", ".join(f"{v:,.0f}".replace(",", " ") for v in sorted(set(doc_vals)))
        return "contradictory", quote, f"Значение ответа не совпадает ни с одним из значений документа ({shown})"
    why = _unit_conflict(q, answer, rv)
    if why:
        return "contradictory", _sentence(answer, re.compile(r"\d")), why
    if EVASIVE_RE.search(answer) and not nums:
        return "evasive", _sentence(answer, EVASIVE_RE), "Остаётся открытым: значение не названо"
    if len(answer) >= 8 and (nums or CONCRETE_RE.search(answer)):
        return "concrete", _sentence(answer, re.compile(r"\d") if nums else CONCRETE_RE), ""
    return "evasive", _sentence(answer, re.compile(r".")), "Остаётся открытым: ответ не даёт значения или решения"


def classify(items: list[tuple], rv, llm=None, log=print) -> list[tuple[str, str, str]]:
    """items: [(question, answer)] → [(type, quote, note)]. Модель уточняет тип и цитату; правила проверяют её вывод."""
    res = [classify_rules(q, a, rv) for q, a in items]
    if llm is None or getattr(llm, "provider", "") == "rules" or not items:
        return res
    prompt = "\n\n".join(f"{q.qid}. Вопрос: {q.text}\nОтвет аналитика: {a}" for q, a in items)
    try:
        data = llm.generate_json(SYSTEM_ANSWERS, prompt, task="answers", context={"items": items})
    except Exception as e:  # noqa: BLE001 — без модели остаются правила
        log(f"ответы: модель недоступна ({str(e)[:80]}) — классификация правилами")
        return res
    by = {str(x.get("qid")): x for x in (data or {}).get("items", []) if isinstance(x, dict)}
    out = []
    for (q, a), (rt, rquote, rnote) in zip(items, res):
        m = by.get(q.qid)
        t = str((m or {}).get("type", "")).lower()
        if t not in TYPES or rt == "contradictory":  # противоречие по числам — за правилами
            out.append((rt, rquote, rnote))
            continue
        quote = str(m.get("quote", "")).strip().strip("«»\"")
        if not quote or _norm(quote) not in _norm(a):  # цитата модели обязана быть подстрокой ответа
            quote = rquote
        elif quote not in a:  # нормализованно совпало — берём точный фрагмент ответа
            i = _norm(a).find(_norm(quote))
            quote = a[i: i + len(quote)] if i >= 0 and _norm(a[i: i + len(quote)]) == _norm(quote) else rquote
        if t == "concrete" and rt == "evasive" and EVASIVE_RE.search(a) and not _numbers(a):
            out.append(("evasive", rquote, rnote))  # «уточним позже» без значения не закрывает замечание, что бы ни сказала модель
            continue
        out.append((t, quote, str(m.get("note", "")).strip() or rnote))
    return out


# ------------------------------------------------------------------ применение к результату

def _resolve(questions, parsed: dict) -> list[tuple]:
    """Сопоставить ответы с вопросами: по метке (rid, criterion) из шаблона, иначе по Q-xx."""
    by_key = {(q.rid or q.ref, q.criterion): q for q in questions if not (q.rid or "").startswith("S-")}
    by_refs = {(q.criterion, ",".join(q.refs)): q for q in questions if (q.rid or "").startswith("S-") and q.refs}
    by_qid = {q.qid: q for q in questions}
    out, unknown, used = [], [], set()
    for qid, v in parsed.items():
        if v.get("key"):  # метка шаблона есть — только по ней: номер Q-xx в другом прогоне может означать другой вопрос
            rid, crit, refs = v["key"]
            # замечания набора перенумеровываются от прогона к прогону — узнаём по критерию и затронутым требованиям
            q = by_refs.get((crit, refs)) if rid.startswith("S-") and refs else by_key.get((rid, crit))
        else:
            q = by_qid.get(qid)
        if q is None or q.qid in used:
            unknown.append(qid)
            continue
        used.add(q.qid)
        out.append((q, v["answer"]))
    return out, unknown


def apply_answers(rv, questions, parsed: dict, llm=None, log=print) -> dict:
    """Учесть ответы в результате проверки rv (меняет его). Возвращает {"items","unknown_qids","closed","added"}."""
    pairs, unknown = _resolve(questions, parsed)
    kinds = classify(pairs, rv, llm, log)
    # ID замечаний по исходной нумерации — до любых удалений
    req_idx = {rr.req.rid: rr for rr in rv.req_results}
    findings_by_id = {f"{rr.req.rid}.{n}": (rr, f) for rr in rv.req_results for n, f in enumerate(rr.findings, 1)}
    set_by_id = {f"S-{i:02d}": f for i, f in enumerate(rv.set_findings, 1)}
    items: list[AnswerItem] = []
    close: dict[int, tuple] = {}  # id(finding) → (qid, quote)
    added: list[SetFinding] = []
    for (q, ans), (t, quote, note) in zip(pairs, kinds):
        closes = []
        if t == "concrete" and quote:
            for fid in q.closes:
                if fid in findings_by_id or fid in set_by_id:
                    closes.append(fid)
                    f = findings_by_id[fid][1] if fid in findings_by_id else set_by_id[fid]
                    close.setdefault(id(f), (q.qid, quote, fid))
            note = note or (f"{', '.join(closes)} закрыто: «{quote}»" if closes else "Связанных замечаний в этом прогоне нет")
            rr = req_idx.get(q.rid)
            if rr is not None and closes:  # в исправленный документ — формулировка со значением из ответа
                base = (rr.rewrite or rr.req.text).strip().rstrip(".")
                rr.rewrite = f"{base}. Уточнено ответом {q.qid}: {quote.rstrip('.')}."
                rr.answered.append(q.qid)
        elif t == "evasive":
            for fid in q.closes:
                hit = findings_by_id.get(fid)
                f = hit[1] if hit else set_by_id.get(fid)
                if f is not None:
                    f.critic_note = (f.critic_note + " " if f.critic_note else "") + f"Ответ {q.qid} уклончивый: «{quote}»."
        elif t == "contradictory":
            base_f = set_by_id.get(q.rid) if q.rid.startswith("S-") else None
            refs = list(base_f.refs) if base_f else ([SetRef(q.rid, req_idx[q.rid].req.text)] if q.rid in req_idx else [])
            vals = [{"rid": q.qid, "value": quote, "quote": quote}] + (list(base_f.values) if base_f else [])
            added.append(SetFinding(
                kind="contradiction", criterion="set_consistent", refs=refs,
                problem=f"Ответ на {q.qid} противоречит документу: «{quote}». {note}".strip(),
                fix="Согласовать одно значение с владельцем продукта и записать его в одном требовании.",
                severity="critical" if base_f and base_f.severity == "critical" else "major",
                source=f"ответ {q.qid}", confidence="high", values=vals))
        items.append(AnswerItem(q.qid, q.text, ans, t, closes, quote, note))
    # закрыть замечания: в rejected с причиной, из активных — убрать
    for rr in rv.req_results:
        keep = []
        for f in rr.findings:
            hit = close.get(id(f))
            if hit:
                rv.rejected.append({"where": rr.req.rid, "quote": f.quote, "problem": f.problem,
                                    "reason": f"закрыто ответом {hit[0]}", "closed_by": hit[0]})
            else:
                keep.append(f)
        rr.findings = keep
    keep_set = []
    for f in rv.set_findings:
        hit = close.get(id(f))
        if hit:
            rv.rejected.append({"where": hit[2], "quote": f.refs[0].quote if f.refs else "", "problem": f.problem,
                                "reason": f"закрыто ответом {hit[0]}", "closed_by": hit[0]})
        else:
            keep_set.append(f)
    rv.set_findings = keep_set + added
    log(f"ответы аналитика: {len(items)} учтено — конкретных {sum(i.type == 'concrete' for i in items)}, "
        f"уклончивых {sum(i.type == 'evasive' for i in items)}, противоречивых {sum(i.type == 'contradictory' for i in items)}; "
        f"закрыто замечаний {len(close)}" + (f"; неизвестные вопросы: {', '.join(unknown)}" if unknown else ""))
    return {"items": items, "unknown_qids": unknown, "closed": len(close), "added": len(added)}


def summary_state(rv, scores) -> dict:
    """Срез «до / после»: критичные, существенные, готовность, вердикт."""
    from .depth import verdicts

    fs = [f for rr in rv.req_results for f in rr.findings] + list(rv.set_findings)
    v = verdicts(rv)
    return {"critical": sum(f.severity == "critical" for f in fs), "major": sum(f.severity == "major" for f in fs),
            "readiness": scores.readiness, "verdict": {"development": v["development"], "testing": v["testing"]}}


def answers_json(source: str, result: dict, before: dict, after: dict) -> dict:
    return {"source": source, "items": [asdict(i) for i in result["items"]], "before": before, "after": after}


def answers_md(ans: dict, level: int = 3) -> list[str]:
    """Раздел отчёта «Ответы аналитика»: таблица и «было → стало»."""
    w = ["#" * level + " Ответы аналитика (перепроверка с учётом ответов)", "",
         f"Учтено ответов: **{len(ans['items'])}** (файл `{ans['source']}`). Замечание закрывается только конкретным ответом "
         "с дословной цитатой; уклончивые и противоречивые ответы оставляют замечания открытыми.", "",
         "| Вопрос | Тип ответа | Цитата ответа | Что закрыто / осталось |", "|---|---|---|---|"]
    for it in ans["items"]:
        res = (", ".join(it["closes"]) + " закрыто") if it["closes"] else ("добавлено замечание «ответ противоречив»"
                                                                          if it["type"] == "contradictory" else "остаётся открытым")
        cell = lambda s: str(s).replace("|", "\\|").replace("\n", " ")  # noqa: E731
        note = re.sub(r"^Остаётся открытым:\s*", "", it["note"] or "")
        w.append(f"| {it['qid']} | {TYPE_RU[it['type']]} | «{cell(it['quote'])}» | {cell(res)}"
                 + (f": {cell(note)}" if note and not it["closes"] else "") + " |")
    b, a = ans["before"], ans["after"]
    w += ["", "**Было → стало**", "", "| Показатель | До ответов | После ответов |", "|---|---|---|",
          f"| Критичных дефектов | {b['critical']} | {a['critical']} |", f"| Существенных дефектов | {b['major']} | {a['major']} |",
          f"| Готовность к разработке | {b['readiness']} % | {a['readiness']} % |",
          f"| Можно начинать разработку | {b['verdict']['development']} | {a['verdict']['development']} |",
          f"| Можно начинать тестирование | {b['verdict']['testing']} | {a['verdict']['testing']} |", ""]
    return w
