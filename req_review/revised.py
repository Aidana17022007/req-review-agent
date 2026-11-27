"""v12: исправленная редакция ТЗ после ответов аналитика (`<отчёт>_revised.md`) и блок «Кратко».

- Изменённые требования: «Было» (дословно) → «Стало» (значения из конкретных ответов вписаны в формулировку) и
  «Устраняет: R-xxx.N, S-xx · по ответу Q-xx» с дословной цитатой ответа.
- Новые требования: пропуски набора (нет метода, контракта, значения по умолчанию …), закрытые ответом, — NEW-xx.
- Новые критерии приёмки: Given/When/Then к изменённым и новым требованиям.
- Осталось уточнить: уклончивые и противоречивые ответы, критичные вопросы без ответа — плейсхолдер
  «[уточнить: Q-xx …]» прямо в тексте требования.
- Предложения агента: правки формулировок без ответа аналитика — отдельно, чтобы не выдавать догадку за ответ.

«Стало» пишет модель (задача "revise"); код проверяет: каждое число из «Стало» и критерия приёмки есть в исходном
тексте, в ответе или в цитате — иначе формулировка отклоняется и остаётся шаблонная подстановка ответа.
"""
from __future__ import annotations

import re

SYSTEM_REVISE = """Ты — аналитик требований. Перепиши требования с учётом ответов владельца ТЗ.
Для каждого элемента верни after — новую формулировку требования (одно-два предложения, стиль «Система должна …»
или как в исходном тексте), в которую ВПИСАНЫ значения и решения из ответа, и gherkin — один приёмочный сценарий
(Дано / Когда / Тогда) на русском. Для нового требования (before пустой) сформулируй требование по проблеме и ответу.
НЕ добавляй чисел, сроков, сумм и фактов, которых нет ни в исходном тексте, ни в ответе. Пиши на русском.
Верни ТОЛЬКО JSON: {"items":[{"id":"R-003","after":"…","gherkin":"Дано …\\nКогда …\\nТогда …"}]}"""

_NUM = re.compile(r"\d+(?:[   ]\d{3})*(?:[.,]\d+)?")


_ID = re.compile(r"\b(?:[A-ZА-ЯЁ]{1,6}-\d{1,4}(?:\.\d+)?|NEW-\d+)\b")  # R-002, Q-01, S-03, FR-02, NEW-01 — не значения


def _nums(s: str) -> set[str]:
    s = _ID.sub(" ", s or "")
    return {re.sub(r"[   ]", "", m.group(0)).replace(",", ".") for m in _NUM.finditer(s)}


def grounded(text: str, *sources: str) -> bool:
    """Каждое число в тексте есть хотя бы в одном источнике (исходное требование, ответ, цитата)."""
    allowed = set().union(*(_nums(s) for s in sources))
    return _nums(text) <= allowed


def _cap(s: str) -> str:
    s = s.strip().rstrip(".;")
    return s[:1].upper() + s[1:] if s else s


def _short(s: str, n: int = 90) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def plan(rv, questions, result: dict, closed: list[dict]) -> dict:
    """Что меняется: {"changed": {rid: {...}}, "added": [...], "open": [...]} — до формулировок."""
    req_idx = {rr.req.rid: rr for rr in rv.req_results}
    qs = {q.qid: q for q in questions}
    set_crit = {}  # S-xx → критерий замечания (по исходной нумерации, из закрытых)
    for c in closed:
        if c["id"].startswith("S-"):
            set_crit[c["id"]] = c.get("criterion", "")
    changed: dict[str, dict] = {}
    added: list[dict] = []
    open_: list[dict] = []
    for it in result["items"]:
        q = qs.get(it.qid)
        if it.type == "concrete" and it.closes:
            rids, gaps = [], []
            for fid in it.closes:
                if fid.startswith("R-"):
                    rids.append(fid.rsplit(".", 1)[0])
                elif set_crit.get(fid) == "set_complete" or not (q and q.refs):
                    gaps.append(fid)
                else:
                    rids += [r for r in q.refs if r in req_idx]
            for rid in dict.fromkeys(rids):
                if rid not in req_idx:
                    continue
                e = changed.setdefault(rid, {"rid": rid, "doc_id": req_idx[rid].req.doc_id, "before": req_idx[rid].req.text,
                                             "fixes": [], "qids": [], "quotes": []})
                e["fixes"] += [f for f in it.closes if f.startswith(rid + ".") or f.startswith("S-")]
                # закрыто противоречие — решение из ответа заменяет формулировку, а не дописывается к ней
                e["replace"] = e.get("replace", False) or any(set_crit.get(f) == "set_consistent" for f in it.closes)
                e["qids"].append(it.qid)
                e["quotes"].append(it.quote)
            if gaps:
                problem = next((c["problem"] for c in closed if c["id"] in gaps), q.text if q else "")
                added.append({"from": it.qid, "fixes": gaps, "problem": problem, "quote": it.quote})
        elif it.type in ("evasive", "contradictory"):
            rid = (q.rid if q and q.rid in req_idx else (q.refs[0] if q and q.refs else "")) if q else ""
            open_.append({"qid": it.qid, "rid": rid, "type": it.type,
                          "placeholder": f"[уточнить: {it.qid} — {_short(it.question, 80)}]", "quote": it.quote})
    answered = {it.qid for it in result["items"]}
    for q in questions:  # критичные вопросы без ответа — тоже в «Осталось уточнить»
        if q.severity == "critical" and q.qid not in answered:
            rid = q.rid if q.rid in req_idx else (q.refs[0] if q.refs else "")
            open_.append({"qid": q.qid, "rid": rid, "type": "без ответа",
                          "placeholder": f"[уточнить: {q.qid} — {_short(q.text, 80)}]", "quote": ""})
    for o in open_:  # плейсхолдер — прямо в тексте требования
        rr = req_idx.get(o["rid"])
        o["text"] = (rr.req.text.rstrip() + " " + o["placeholder"]) if rr else o["placeholder"]
    return {"changed": changed, "added": added, "open": open_}


def write(rv, p: dict, llm=None, log=print) -> dict:
    """Формулировки «Стало» и критерии приёмки (модель + проверка чисел кодом; без модели — шаблон)."""
    req_idx = {rr.req.rid: rr for rr in rv.req_results}
    items = [{"id": rid, "before": e["before"], "answer": " ".join(e["quotes"]), "replace": e.get("replace", False)}
             for rid, e in p["changed"].items()]
    items += [{"id": f"NEW-{i:02d}", "before": "", "problem": a["problem"], "answer": a["quote"]}
              for i, a in enumerate(p["added"], 1)]
    got: dict[str, dict] = {}
    if items and llm is not None and getattr(llm, "provider", "") != "rules":
        prompt = "\n\n".join(f"{x['id']}. Исходное требование: {x['before'] or '(нет — новое требование)'}\n"
                             + (f"Проблема: {x['problem']}\n" if x.get("problem") else "")
                             + ("Ответ разрешает противоречие: замени противоречащую часть решением из ответа.\n"
                                if x.get("replace") else "")
                             + f"Ответ владельца ТЗ: {x['answer']}" for x in items)
        try:
            data = llm.generate_json(SYSTEM_REVISE, prompt, task="revise", context={"items": items})
            got = {str(x.get("id")): x for x in (data or {}).get("items", []) if isinstance(x, dict)}
        except Exception as e:  # noqa: BLE001 — без модели остаётся шаблон
            log(f"исправленное ТЗ: модель недоступна ({str(e)[:80]}) — шаблонная подстановка ответов")
    out_changed, out_added, acceptance = [], [], []
    rejected = 0
    for x in items:
        m = got.get(x["id"]) or {}
        after = " ".join(str(m.get("after", "")).split())
        gherkin = str(m.get("gherkin", "")).strip()
        src = x["before"] + " " + x.get("problem", "")
        if after and not grounded(after, src, x["answer"]):
            after, rejected = "", rejected + 1  # модель вписала число, которого нет ни в документе, ни в ответе
        if gherkin and not grounded(gherkin, src, x["answer"], after):
            gherkin = ""
        if not after:  # шаблон: исходная формулировка + решение из ответа (при противоречии — только решение)
            keep = x["before"] and not x.get("replace")
            after = (x["before"].strip().rstrip(".") + ". " if keep else "") + _cap(x["answer"]) + "."
        if x["before"]:
            e = p["changed"][x["id"]]
            out_changed.append({"rid": x["id"], "doc_id": e["doc_id"], "before": x["before"], "after": after,
                                "fixes": list(dict.fromkeys(e["fixes"])), "qids": e["qids"], "quotes": e["quotes"],
                                "source": "ответ"})
            rr = req_idx.get(x["id"])
            if rr is not None:  # исправленный документ (<отчёт>_requirements_fixed.md) — та же формулировка
                rr.rewrite = after
                rr.answered = list(dict.fromkeys(rr.answered + e["qids"]))
        else:
            a = p["added"][int(x["id"].split("-")[1]) - 1]
            out_added.append({"id": x["id"], "text": after, "from": a["from"], "fixes": a["fixes"], "quote": a["quote"]})
        if gherkin:
            acceptance.append({"rid": x["id"], "gherkin": gherkin, "source": "модель, проверено кодом"})
    if rejected:
        log(f"исправленное ТЗ: отклонено формулировок модели с числами не из документа и не из ответа — {rejected}")
    return {"changed": out_changed, "added": out_added, "acceptance": acceptance,
            "open": [{k: o[k] for k in ("qid", "rid", "type", "placeholder", "quote", "text")} for o in p["open"]]}


_FUNC_END = re.compile(r"\b(и|или|а|но|от|до|в|на|с|со|по|для|согласно|быть|быстро|как|чем|что|при)\s*[.;:]?\s*$", re.I)


def _sane_rewrite(before: str, after: str) -> bool:
    """Предложение агента без ответа — только если оно не ломает фразу: удаление слов из середины
    («должна обеспечивать защиту от» → «должна от») и обрыв на служебном слове отбрасываются."""
    if _FUNC_END.search(after.strip()):
        return False
    b, a = before.split(), after.split()
    if len(a) < len(b) and all(w in b for w in a):  # чистое удаление слов — допустимо только хвостом
        k = len(a) - 1
        return [w.strip(".,;") for w in b[:k]] == [w.strip(".,;") for w in a[:k]]
    return True


def agent_suggestions(rv, answered_rids: set) -> list[dict]:
    """Правки агента без ответа аналитика — отдельным списком «предложение агента»."""
    out = []
    for rr in rv.req_results:
        if rr.req.rid in answered_rids or not rr.rewrite or not rr.findings or rr.rewrite.strip() == rr.req.text.strip():
            continue
        if not _sane_rewrite(rr.req.text, rr.rewrite):
            continue
        out.append({"rid": rr.req.rid, "doc_id": rr.req.doc_id, "before": rr.req.text, "after": rr.rewrite,
                    "source": "предложение агента"})
    return out


def revised_md(title: str, revised: dict, summary: dict, suggestions: list[dict]) -> str:
    lab = lambda r: f"{r['doc_id']} ({r['rid']})" if r.get("doc_id") else r["rid"]  # noqa: E731
    out = [f"# {title} — исправленная редакция требований", "",
           f"> Подготовлено ReqLens по ответам аналитика: изменено требований — **{len(revised['changed'])}**, новых — "
           f"**{len(revised['added'])}**, закрыто блокеров — **{summary['blockers_closed']} из {summary['blockers_total']}**, "
           f"открытых замечаний — **{summary['open_after']} из {summary['open_before']}**.",
           "> «Стало» содержит только значения из документа и из ответов (числа сверены кодом). Плейсхолдер "
           "[уточнить: Q-xx …] — вопрос, на который ещё нет конкретного ответа.", ""]
    out += ["## Изменённые требования", ""]
    if not revised["changed"]:
        out += ["Ответы не изменили формулировок требований.", ""]
    for c in revised["changed"]:
        out += [f"### {lab(c)}", "", f"**Было:** {c['before']}", "", f"**Стало:** {c['after']}", "",
                f"*Устраняет:* {', '.join(c['fixes']) or '—'} · *по ответу* {', '.join(c['qids'])}: "
                + " / ".join(f"«{q}»" for q in c["quotes"]), ""]
    out += ["## Новые требования", ""]
    if not revised["added"]:
        out += ["Новых требований по ответам нет.", ""]
    for a in revised["added"]:
        out += [f"### {a['id']}", "", a["text"], "", f"*Закрывает:* {', '.join(a['fixes'])} · *по ответу* {a['from']}: «{a['quote']}»", ""]
    out += ["## Новые критерии приёмки", ""]
    if not revised["acceptance"]:
        out += ["Критерии приёмки по изменённым требованиям не сформированы (прогон без модели).", ""]
    for t in revised["acceptance"]:
        out += [f"**{t['rid']}**", "", "```gherkin", t["gherkin"], "```", ""]
    out += ["## Осталось уточнить", ""]
    if not revised["open"]:
        out += ["Открытых вопросов нет.", ""]
    for o in revised["open"]:
        kind = _KIND.get(o["type"], o["type"])
        tail = f" — ответ: «{o['quote']}» ({kind})" if o["quote"] else f" ({kind})"
        out.append(f"- **{o['rid'] or 'документ'}**{tail}: {o.get('text') or o['placeholder']}")
    out.append("")
    if suggestions:
        out += ["## Предложения агента (без ответа аналитика)", "",
                "Правки формулировок, которые агент предлагает сам; их нужно подтвердить у владельца ТЗ.", ""]
        for s in suggestions:
            out += [f"- **{lab(s)}** — было: «{_short(s['before'], 160)}» → предложение агента: «{_short(s['after'], 200)}»"]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


_KIND = {"evasive": "уклончивый ответ", "contradictory": "ответ противоречит документу"}


def brief_md(answers: dict) -> list[str]:
    """«Кратко» — первый блок отчёта после ответов: вердикт до → после, блокеры и как каждый закрыт, что осталось."""
    b, a, s = answers["before"], answers["after"], answers["summary"]
    w = ["## Кратко: что изменилось после ответов аналитика", "",
         "| | До ответов | После ответов |", "|---|---|---|",
         f"| Можно начинать разработку | {b['verdict']['development']} | **{a['verdict']['development']}** |",
         f"| Можно начинать тестирование | {b['verdict']['testing']} | **{a['verdict']['testing']}** |",
         f"| Блокеры (критичные) | {s['blockers_total']} | **{s['blockers_total'] - s['blockers_closed']}** |",
         f"| Открытых замечаний | {s['open_before']} | **{s['open_after']}** |", "",
         f"**Закрыто блокеров: {s['blockers_closed']} из {s['blockers_total']}.**"
         + (" Номера замечаний — как в отчёте до ответов." if s.get("closed_blockers") else ""), ""]
    for c in s.get("closed_blockers", []):
        w.append(f"- {c['id']} — {_short(c['problem'], 110)} → закрыт ответом {c['qid']}: «{_short(c['quote'], 110)}»")
    if s.get("closed_blockers"):
        w.append("")
    rev = answers.get("revised") or {}
    if rev.get("open"):
        w += ["**Осталось решить:** " + "; ".join(f"{o['qid']} ({_KIND.get(o['type'], o['type'])})" for o in rev["open"][:6]) + ".", ""]
    w += [f"Изменено требований: {len(rev.get('changed', []))}, новых: {len(rev.get('added', []))} — "
          "исправленная редакция в файле `<отчёт>_revised.md`.", ""]
    return w
