"""v13+ A12: заполнение чек-листа «Ревью требований» из шаблона документа.

Если в документе есть раздел-чек-лист (заголовок «Ревью требований», «Чек-лист», «Контрольный список» или таблица, где в
колонках «Да / Нет»), агент отвечает по каждому пункту: да / нет / частично — со ссылками на свои замечания и цитаты.
Ответ выводится из результатов проверки (критерии 29148, правила, трассировка, комплаенс), а не из модели.
Пункт, тему которого агент не распознал, получает ответ «не оценено» — без догадок.
"""
from __future__ import annotations

import re

_SECTION = re.compile(r"ревью требовани|чек-?лист|checklist|контрольн\w* спис|тексеру парағы", re.I)
_YESNO = re.compile(r"да\s*/\s*нет|yes\s*/\s*no|иә\s*/\s*жоқ", re.I)

# тема пункта → (критерии замечаний, которые говорят «нет»; признак в тексте, который говорит «есть»; пояснение)
THEMES = [
    (r"тестир|проверяем|test", ["verifiable"], None, "проверяемость требований (тест-проба, критерий verifiable)"),
    (r"противореч|операционн\w* риск", ["set_consistent", "consistent"], None, "непротиворечивость набора"),
    (r"модел\w* данн|поток", ["set_complete:данн"], r"требования к данным|модель данных", "модель данных"),
    (r"структурирован|стандарт|шаблон", ["conforming", "set_traceable", "set_ranked"], None, "оформление по шаблону и трассируемость"),
    (r"бизнес-требован|покрывает бизнес", ["set_complete", "complete"], r"цел[иь]|бизнес-процесс", "полнота относительно цели"),
    (r"sequence|взаимодейств|интеграц", ["set_complete:событ|интеграц|контракт"], r"sequence|интеграц", "интеграция и взаимодействие систем"),
    (r"ux|ui|дизайн", ["set_complete:экран|поле|интерфейс"], r"\bui\b|дизайн|экран", "покрытие UI"),
    (r"откат", [], r"откат|rollback", "схема отката"),
    (r"архитектур", [], r"архитектур", "архитектура"),
    (r"информационн\w* безопасн|\bиб\b", ["compliance"], r"безопасн|tls|шифр", "риски ИБ (блок «Комплаенс и безопасность»)"),
    (r"бизнес-процесс|bpmn|схем\w* полного", [], r"bpmn|схема процесса|бизнес-процесс", "схема бизнес-процесса"),
    (r"версионност|верси", ["set_complete:верси"], r"верси[яи]\s*[:\d]|дата\s*[:\d]", "версия и дата документа"),
    (r"согласован\w*.*ответствен|иные продукты|согласующ", [], r"согласован", "согласование со смежными командами"),
]


def _section_rows(doc) -> tuple[str, list[tuple[int, str]]]:
    sec, rows, found = "", [], ""
    for ln in doc.lines:
        h = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", ln.text)
        if h:
            sec = h.group(1)
            continue
        t = ln.text.strip()
        if not t.startswith("|") or set(t) <= set("|-: "):
            continue
        cells = [c.strip() for c in t.strip("|").split("|")]
        if not cells or not cells[0] or re.fullmatch(r"проверка|пункт|критерий|тексеру|check", cells[0], re.I):
            continue
        if _SECTION.search(sec) and (_YESNO.search(t) or len(cells) >= 2):
            if not found:
                found = sec
            if sec == found:
                rows.append((ln.lineno, cells[0]))
    return found, rows


def fill(rv) -> dict:
    """{"section","items":[{"item","line","answer","why","refs"}],"summary":{...}} или {} — если чек-листа нет."""
    from .traceability import finding_id

    section, rows = _section_rows(rv.doc)
    if not rows:
        return {}
    # поиск «есть ли в документе» — без самого чек-листа и блока согласующих (там эти слова есть всегда)
    sec, keep, approvals = "", [], []
    for ln in rv.doc.lines:
        h = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", ln.text)
        if h:
            sec = h.group(1)
        if sec == section:
            continue
        if re.search(r"согласующ|лист согласования", sec, re.I):
            t = ln.text.strip()
            if t.startswith("|") and not set(t) <= set("|-: "):
                approvals.append([c.strip() for c in t.strip("|").split("|")])
            continue
        keep.append(ln.text)
    text = "\n".join(keep).lower()
    approved = len(approvals) > 1 and all(len(r) > 1 and r[1] for r in approvals[1:])  # строки после заголовка заполнены
    fs = [f for rr in rv.req_results for f in rr.findings] + list(rv.set_findings)
    comp = getattr(rv, "compliance", None) or {}
    items = []
    for line, item in rows:
        low = item.lower()
        theme = next((t for t in THEMES if re.search(t[0], low)), None)
        if theme is None:
            items.append({"item": item, "line": line, "answer": "не оценено", "why": "тема пункта не распознана", "refs": []})
            continue
        _, crits, present, why = theme
        if why.startswith("согласование"):
            items.append({"item": item, "line": line, "answer": "да" if approved else "нет", "refs": [],
                          "why": why + (": блок согласующих заполнен" if approved else ": блок согласующих не заполнен")})
            continue
        bad = []
        for c in crits:
            if c == "compliance":
                bad += [x["_finding"] for x in comp.get("checks", []) if x.get("status") == "fired" and x.get("_finding")]
                continue
            crit, _, kw = c.partition(":")
            bad += [f for f in fs if f.criterion == crit and f.severity != "minor"
                    and (not kw or re.search(kw, f.problem, re.I))]
        has = bool(re.search(present, text, re.I)) if present else None
        crit_bad = [f for f in bad if f.severity == "critical"]
        if bad:
            answer = "нет" if crit_bad or has is False else "частично"
        elif has is False:
            answer = "нет"
        else:
            answer = "да"
        refs = list(dict.fromkeys(fid for fid in (finding_id(rv, f) for f in bad[:6]) if fid))
        note = why + (f": замечаний {len(bad)} (критичных {len(crit_bad)})" if bad else
                      (": в документе нет" if has is False else ": замечаний нет"))
        items.append({"item": item, "line": line, "answer": answer, "why": note, "refs": refs})
    summary = {a: sum(i["answer"] == a for i in items) for a in ("да", "частично", "нет", "не оценено")}
    return {"section": section, "items": items, "summary": summary}


def report_md(bc: dict) -> list[str]:
    if not bc:
        return []
    icon = {"да": "✅", "частично": "🟠", "нет": "❌", "не оценено": "—"}
    s = bc["summary"]
    w = [f"### Чек-лист «{bc['section']}» — заполнен агентом", "",
         f"Да — {s['да']}, частично — {s['частично']}, нет — {s['нет']}, не оценено — {s['не оценено']}. "
         "Ответы выведены из замечаний отчёта (ссылки — номера замечаний).", "",
         "| Пункт чек-листа | Ответ | Почему | Замечания |", "|---|---|---|---|"]
    for i in bc["items"]:
        refs = ", ".join(f"[{r}](#{r.lower().replace('.', '')})" for r in i["refs"]) or "—"
        w.append(f"| {i['item'][:120].replace('|', '/')} | {icon[i['answer']]} {i['answer']} | {i['why']} | {refs} |")
    return w + [""]
