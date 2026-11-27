"""v9: повестка решений для владельца продукта — реальные развилки из противоречий и критичных пропусков.

Формулировки собирает код из подтверждённых замечаний (report.json): какое решение принять, где расходится документ
(требования и строки), что меняется для клиента и разработки, варианты. Модель по желанию (`--decisions-llm`) только
перефразирует заголовок и последствия на бизнес-язык; ссылки, строки и варианты остаются от кода. Без модели — как есть.
"""
from __future__ import annotations

import re

MAX_ITEMS = 8
MAX_GAPS = 2

SYSTEM_DECISIONS = """Ты помогаешь владельцу продукта. Перефразируй каждое решение на понятный бизнес-язык, без жаргона
разработки. Не добавляй фактов, чисел и требований, которых нет во входе. title — вопрос, на который нужно ответить
(до 120 символов); impact — одно предложение: что изменится для клиента или разработки. Пиши на русском.
Верни ТОЛЬКО JSON: {"items":[{"id":"D-01","title":"…","impact":"…"}]}"""


def _label(ref: dict, reqs: dict) -> str:
    rid = ref.get("req_id", "")
    r = reqs.get(rid)
    if r is None:
        line = (ref.get("span") or {}).get("line")
        return f"строка {line}" if line else "документ"
    return r.get("doc_id") or rid


def _where(f: dict, reqs: dict) -> list[dict]:
    out, seen = [], set()
    for ref in f.get("refs", []):
        rid = ref.get("req_id", "")
        line = (ref.get("span") or {}).get("line") or (reqs.get(rid) or {}).get("line_start")
        key = (rid, line)
        if key in seen:
            continue
        seen.add(key)
        out.append({"rid": rid, "doc_id": (reqs.get(rid) or {}).get("doc_id"), "line": line})
    return out


def _sentences(text: str) -> list[str]:
    """Предложения без разрывов внутри кавычек «…»; предложения не по-русски (латиница) пропускаются."""
    out, buf = [], ""
    for part in re.split(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z«(])", " ".join(str(text).split())):
        buf = f"{buf} {part}".strip() if buf else part
        if buf.count("«") <= buf.count("»"):
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return [s for s in out if len(re.findall(r"[А-Яа-яЁё]", s)) >= len(re.findall(r"[A-Za-z]", s)) / 2]


def _first(text: str) -> str:
    """Первое предложение по-русски или пустая строка (текст целиком на латинице, пустой — не ошибка)."""
    ss = _sentences(text or "")
    return ss[0] if ss else ""


def _short(s: str, n: int) -> str:
    s = " ".join(str(s).split()).strip().rstrip(".")
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _quote(ref: dict, n: int = 90) -> str:
    return _short(ref.get("quote", ""), n)


def _impact(f: dict) -> str:
    rest = _sentences(f.get("problem", ""))[1:]
    if rest:
        return _short(" ".join(rest[:2]), 260) + "."
    if f.get("kind") == "gap":
        return "Без решения разработчики додумают поведение сами, а тестировщики не смогут написать приёмочные тесты."
    return "Разработка и тестирование прочтут документ по-разному: без решения нельзя написать однозначные тест-кейсы."


def _item(f: dict, sid: str, reqs: dict) -> dict:
    labeled = [r for r in f.get("refs", []) if r.get("quote")]
    labels = list(dict.fromkeys(_label(r, reqs) for r in labeled))
    fix = _short(_first(f.get("fix", "")), 200)
    if f.get("kind") == "gap":
        title = f"Нужно ли закрыть пропуск: {_short(_first(f.get('problem', '')), 110)}?"
        options = [f"Дописать в документ: {fix}" if fix else "Дописать требование в документ",
                   "Сознательно исключить из этой версии и записать это в документе"]
    elif f.get("values"):
        vals = list(dict.fromkeys(str(v.get("value", "")).strip() for v in f["values"] if v.get("value")))
        title = f"Какое значение принять: {' или '.join(vals[:3])}?"
        options = [f"{v.get('value')} ({_label({'req_id': v.get('rid')}, reqs)})" for v in f["values"][:3]]
    elif len(labels) >= 2:
        title = f"Что верно: {labels[0]} или {labels[1]}? {_short(_first(f.get('problem', '')), 110)}"
        options = [f"Принять {_label(r, reqs)}: «{_quote(r)}»" for r in labeled[:2]]
        if fix:
            options.append(f"Изменить оба места: {fix}")
    else:
        title = f"Как разрешить противоречие в {labels[0] if labels else 'документе'}? {_short(_first(f.get('problem', '')), 110)}"
        options = [f"Как предлагает агент: {fix}" if fix else "Исправить формулировку",
                   "Оставить как есть и явно описать исключение в документе"]
    return {"title": title, "where": _where(f, reqs), "impact": _impact(f), "options": options[:3], "source_ids": [sid],
            "wording": "код", "_rids": {r.get("req_id") for r in f.get("refs", []) if r.get("req_id") != "DOC"}}


def build_decisions(data: dict) -> list[dict]:
    """report.json → 0–8 решений: критичные противоречия, до двух критичных пропусков, существенные противоречия."""
    reqs = {r["rid"]: r for r in data.get("requirements", [])}
    sets = [(f"S-{i:02d}", f) for i, f in enumerate(data.get("set_findings", []), 1)]
    contra = [(sid, f) for sid, f in sets if f.get("criterion") == "set_consistent" and f.get("kind") != "terminology"
              and (f.get("kind") == "contradiction" or f.get("values"))]
    gaps = [(sid, f) for sid, f in sets if f.get("kind") == "gap" and f.get("severity") == "critical"]
    n_refs = lambda f: len({r.get("req_id") for r in f.get("refs", []) if r.get("req_id") != "DOC"})  # noqa: E731
    ordered = ([x for x in contra if x[1].get("severity") == "critical"]
               + sorted(gaps, key=lambda x: -n_refs(x[1]))[:MAX_GAPS]
               + sorted([x for x in contra if x[1].get("severity") == "major"], key=lambda x: -n_refs(x[1])))
    out: list[dict] = []
    for sid, f in ordered:
        it = _item(f, sid, reqs)
        host = next((d for d in out if it["_rids"] and it["_rids"] <= d["_rids"]), None)
        if host is not None:  # то же место документа — одно решение, несколько замечаний
            host["source_ids"].append(sid)
            continue
        out.append(it)
        if len(out) >= MAX_ITEMS:
            break
    for i, d in enumerate(out, 1):
        d.pop("_rids", None)
        d["id"] = f"D-{i:02d}"
    return [{"id": d["id"], **{k: d[k] for k in ("title", "where", "impact", "options", "source_ids", "wording")}} for d in out]


def rephrase(decisions: list[dict], llm, log=print) -> list[dict]:
    """По желанию: модель перефразирует title и impact; остальное — от кода. Ошибка модели — остаётся формулировка кода."""
    if not decisions or llm is None or getattr(llm, "provider", "") in ("rules", "mock"):
        return decisions
    prompt = "\n\n".join(f"{d['id']}. Решение: {d['title']}\nПоследствия: {d['impact']}\nВарианты: {'; '.join(d['options'])}"
                         for d in decisions)
    try:
        data = llm.generate_json(SYSTEM_DECISIONS, prompt, task="decisions", context={"items": decisions})
    except Exception as e:  # noqa: BLE001
        log(f"решения: модель недоступна ({str(e)[:80]}) — формулировки кода")
        return decisions
    by = {str(x.get("id")): x for x in (data or {}).get("items", []) if isinstance(x, dict)}
    for d in decisions:
        m = by.get(d["id"])
        title, impact = str((m or {}).get("title", "")).strip(), str((m or {}).get("impact", "")).strip()
        nums = set(re.findall(r"\d+", d["title"] + d["impact"] + " ".join(d["options"])))
        if title and impact and set(re.findall(r"\d+", title + impact)) <= nums:  # модель не добавляет новых чисел
            d.update(title=_short(title, 160), impact=_short(impact, 300) + ".", wording="модель")
    return decisions


def decisions_md(decisions: list[dict], level: int = 3) -> list[str]:
    w = ["#" * level + f" Решения для владельца продукта ({len(decisions)})", "",
         "Реальные развилки документа: без этих решений разработка и тестирование прочтут требования по-разному. "
         "Собрано из подтверждённых противоречий и критичных пропусков.", "",
         "| # | Какое решение принять | Где расходится | Что меняется для клиента / разработки | Варианты |", "|---|---|---|---|---|"]
    cell = lambda s: str(s).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    for d in decisions:
        where = ", ".join(f"{x['doc_id'] or x['rid']} (стр. {x['line']})" if x.get("line") else (x["doc_id"] or x["rid"])
                          for x in d["where"])
        opts = "<br>".join(f"{i}) {cell(o)}" for i, o in enumerate(d["options"], 1))
        w.append(f"| {d['id']} | {cell(d['title'])} | {cell(where)} | {cell(d['impact'])} | {opts} |")
    return w + [""]


def decisions_file(decisions: list[dict], title: str) -> str:
    out = [f"# Решения для владельца продукта — {title}", "",
           "> Повестка ReqLens: что нужно решить, чтобы требования можно было реализовать и проверить. "
           "Каждый пункт — из подтверждённых замечаний отчёта (номера S-xx).", ""]
    for d in decisions:
        out += [f"## {d['id']}. {d['title']}", "",
                "**Где расходится:** " + "; ".join(
                    f"{x['doc_id'] or x['rid']}" + (f", строка {x['line']}" if x.get("line") else "") for x in d["where"]), "",
                f"**Что меняется:** {d['impact']}", "", "**Варианты:**", ""]
        out += [f"{i}. {o}" for i, o in enumerate(d["options"], 1)]
        out += ["", f"*Основание:* {', '.join(d['source_ids'])}", ""]
    return "\n".join(out).rstrip() + "\n"
