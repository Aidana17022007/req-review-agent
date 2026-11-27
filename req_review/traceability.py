"""v12: граф трассировки — код, без модели.

Узлы: требования, критерии приёмки, поля экрана (из описания UI), методы API, параметры, HTTP-статусы.
Рёбра: «в документе» — явная ссылка (ID требования в строке приёмки, название поля или путь метода в тексте);
«выведено кодом» — совпадение терминов (правило ↔ пример приёмки, поле экрана ↔ описание параметра),
операция ↔ метод чтения / записи.
Разрывы — замечания к набору с дословной цитатой: правило без критерия приёмки, поле экрана без параметра API,
операция без метода, статус без описания и примера, параметр без типа. Если такое замечание уже найдено (моделью,
правилом или проходом полноты), новое не создаётся — разрыв связывается с найденным.
"""
from __future__ import annotations

import re

from .checker import SetFinding, SetRef
from .textutil import clip_quote
from .verify import quote_in

DOC_EDGE, CODE_EDGE = "в документе", "выведено кодом"

_HEAD = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
_UI_SECTION = re.compile(r"\bUI\b|UX|интерфейс|экран|дизайн|макет", re.I)
# элемент экрана: тип + необязательное имя в кавычках; «поле «Порог, ₸»», «переключатель», «кнопка «Сохранить»»
_UI_EL = re.compile(r"\b(пол[еяю]|переключател[ьяюие]м?|чекбокс\w*|флаж[оке]к?\w*|выпадающ\w+ спис\w+|кнопк[аиуе])"
                    r"(?:\s+«([^»]{1,40})»)?", re.I)
_INPUT = re.compile(r"^(пол|перекл|чекбокс|флаж|выпада)", re.I)  # поля ввода (кнопка — действие, не данные)
_UI_SYNONYMS = {"перек": {"включ", "enabl", "activ", "flag", "призн", "статус"},
                "чекбо": {"включ", "enabl", "flag", "призн"}, "флажо": {"включ", "enabl", "flag", "призн"}}
_VERB = r"GET|POST|PUT|PATCH|DELETE"
_INLINE_METHOD = re.compile(rf"\b({_VERB})\b[\s`]+(/[A-Za-z][\w/{{}}.:-]*)")
_PATH = re.compile(r"`?(/[A-Za-z][\w{}.:-]*(?:/[\w{}.:-]+)+|/[A-Za-z][\w{}.-]+)`?")
_VERB_ROW = re.compile(rf"^\|\s*\**\s*(?:REST type|HTTP method|Method|Метод|Тип запроса)\s*\**\s*\|\s*`?({_VERB})\b", re.I)
_URL_ROW = re.compile(r"^\|\s*\**\s*(?:Request URL|URL|Endpoint|Адрес|Путь)\s*\**\s*\|(.+)$", re.I)
_PARAM_HEAD = re.compile(r"^\|\s*(?:Parameter|Param|Параметр|Имя параметра|Field|Name)\s*\|", re.I)
_TYPE_COL = re.compile(r"^(?:Format|Type|Тип|Формат|Data type|Тип данных)$", re.I)
_DESC_COL = re.compile(r"^(?:Description|Описание|Logic|Логика|Назначение)$", re.I)
_IDENT = re.compile(r"^`?([A-Za-z_][\w.\[\]]*)`?$")
_STATUS_LINE = re.compile(r"^\s*(?:#{1,6}\s*|\*\*|\|\s*)?([1-5]\d\d)\b\.?\**\s*(.*)$")
_STATUS_ANY = re.compile(r"\b([1-5]\d\d)\b")
_API_SECTION = re.compile(r"\bAPI\b|REST|статус|ответ|response|код\w* ответ|ошибк", re.I)
_READ = re.compile(r"\b(чита\w*|чтени\w*|показ\w*|отображ\w*|видн\w*|получ\w*|просм\w*)", re.I)
_WRITE = re.compile(r"\b(сохран\w*|измен\w*|зада[её]т|задать|задаёт|включа\w*|выключа\w*|удал\w*|созда\w*|обновл\w*)", re.I)
_WRITE_NAME = re.compile(r"save|update|set[A-Z_]|create|delete|remove|add|put|edit", re.I)
_READ_NAME = re.compile(r"\bget|list|read|fetch|find|search|/[a-z]+$", re.I)
_STOP = {"котор", "этого", "также", "чтобы", "долже", "должн", "систе", "может", "между", "после", "перед", "будет",
         "всего", "более", "менее", "только", "любой", "каждо", "через"}


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-zа-яё]{4,}", text.lower().replace("ё", "е")) if w[:5] not in _STOP}


def _cells(line: str) -> list[str]:
    return [c.strip().strip("*").strip() for c in line.strip().strip("|").split("|")]


def _sections(doc):
    """[(lineno, text, section)] — раздел по ближайшему заголовку Markdown."""
    sec, out = "", []
    for ln in doc.lines:
        m = _HEAD.match(ln.text)
        if m:
            sec = m.group(2)
        out.append((ln.lineno, ln.text, sec))
    return out


def extract(doc, rv) -> dict:
    lines = _sections(doc)
    nodes: dict[str, dict] = {}

    def node(nid, typ, label, quote, line, **kw):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "type": typ, "label": label, "quote": quote, "line": line, **kw}
        return nodes[nid]

    accs = []
    for rr in rv.req_results:
        r = rr.req
        if r.kind == "acceptance" or re.search(r"критери\w* при[её]мк|acceptance", r.section or "", re.I):
            accs.append(r)
            node(r.rid, "acceptance", r.doc_id or r.rid, clip_quote(r.text, 80), r.line_start)
        elif r.kind == "requirement":
            node(r.rid, "requirement", r.doc_id or r.rid, clip_quote(r.text, 80), r.line_start)
    # поля экрана — в разделах об интерфейсе
    for no, text, sec in lines:
        if not _UI_SECTION.search(sec or "") or _HEAD.match(text):
            continue
        for m in _UI_EL.finditer(text):
            label = m.group(2) or m.group(1).lower()
            if m.group(2) is None and not re.match(r"перекл|чекбокс|флаж", m.group(1), re.I):
                continue  # кнопка или поле без названия — не узел (переключатель на экране обычно один)
            node(f"UI:{label.lower()}", "ui_field" if _INPUT.match(m.group(1)) else "ui_action", label, m.group(0), no,
                 kind=m.group(1).lower())
    # методы API: «POST /path» в тексте или строки таблицы «REST type | GET» + «Request URL | /path» в одном разделе
    verb_by_sec: dict[str, tuple] = {}
    for no, text, sec in lines:
        for m in _INLINE_METHOD.finditer(text):
            node(f"API:{m.group(1)} {m.group(2)}", "api_method", f"{m.group(1)} {m.group(2)}", m.group(0), no,
                 verb=m.group(1), path=m.group(2))
        if vm := _VERB_ROW.match(text):
            verb_by_sec[sec] = (vm.group(1).upper(), no, text.strip())
    for no, text, sec in lines:
        um = _URL_ROW.match(text)
        if um and sec in verb_by_sec:
            verb = verb_by_sec[sec][0]
            for pm in _PATH.finditer(um.group(1)):
                path = pm.group(1)
                node(f"API:{verb} {path}", "api_method", f"{verb} {path}", path, no, verb=verb, path=path)
    # параметры: таблицы с колонкой Parameter / Параметр; тип — колонка Format / Type
    hdr, in_resp = None, False
    for no, text, sec in lines:
        if _PARAM_HEAD.match(text):
            hdr = [c.lower() for c in _cells(text)]
            in_resp = bool(re.search(r"ответ|response", sec or "", re.I))
            continue
        if hdr is None:
            continue
        if not text.strip().startswith("|"):
            hdr = None
            continue
        cells = _cells(text)
        if set("".join(cells)) <= set(":- "):
            continue
        m = _IDENT.match(cells[0]) if cells else None
        if not m:
            continue
        ti = next((i for i, h in enumerate(hdr) if _TYPE_COL.match(h)), None)
        di = [i for i, h in enumerate(hdr) if _DESC_COL.match(h)]
        typ = cells[ti] if ti is not None and ti < len(cells) else ""
        desc = " ".join(cells[i] for i in di if i < len(cells))
        name = m.group(1)
        node(f"P:{'resp' if in_resp else 'req'}:{name}", "api_param", name, cells[0], no, datatype=typ.strip("`"),
             description=desc, direction="response" if in_resp else "request")
    # HTTP-статусы: строки-заголовки / жирные строки, начинающиеся с кода, в разделах об API
    st: dict[str, dict] = {}
    for i, (no, text, sec) in enumerate(lines):
        m = _STATUS_LINE.match(text)
        if not m or not (_API_SECTION.search(sec or "") or _HEAD.match(text) or text.lstrip().startswith("**")):
            continue
        code, rest = m.group(1), m.group(2).strip(" .*—-")
        if text.lstrip().startswith("|"):
            continue
        s = st.setdefault(code, {"line": no, "quote": text.strip()[:80], "described": False, "example": False})
        if len(re.findall(r"[а-яёa-z]{3,}", rest.lower())) >= 3:
            s["described"] = True
        for _no2, t2, _s2 in lines[i + 1:i + 7]:  # пример ответа: блок кода или JSON сразу под строкой статуса
            if _STATUS_LINE.match(t2) and not t2.strip().startswith("{"):
                break
            if t2.strip().startswith(("```", "{")):
                s["example"] = True
                break
    for no, text, sec in lines:  # v13+: таблица статусов «| 403 | когда возвращается | тело |»
        if text.lstrip().startswith("|"):
            cells = _cells(text)
            if cells and re.fullmatch(r"[1-5]\d\d", cells[0]):
                s = st.setdefault(cells[0], {"line": no, "quote": text.strip()[:80], "described": False, "example": False})
                s["described"] = s["described"] or any(len(re.findall(r"[а-яёa-z]{3,}", c.lower())) >= 2 for c in cells[1:])
                s["example"] = s["example"] or any("{" in c for c in cells[1:])
    for no, text, sec in lines:  # «Если результат 200 или 201 — успешный»: код упомянут в тексте
        if _API_SECTION.search(sec or "") and not _STATUS_LINE.match(text):
            for m in _STATUS_ANY.finditer(text):
                if re.search(r"(?:результат|код|статус|status|HTTP|ответ)[^.;]{0,30}?\b" + m.group(1), text, re.I):
                    st.setdefault(m.group(1), {"line": no, "quote": m.group(1), "described": False, "example": False,
                                               "mention": text.strip()})
    for code, s in sorted(st.items()):
        node(f"HTTP:{code}", "http_status", code, s["quote"], s["line"], described=s["described"], example=s["example"],
             mention=s.get("mention", ""))
    return {"nodes": nodes, "accs": accs, "lines": lines}


def build(rv) -> dict:
    """Граф {nodes, edges, gaps}; замечания-разрывы добавляются в rv.set_findings (или связываются с найденными)."""
    doc = rv.doc
    ex = extract(doc, rv)
    nodes, accs = ex["nodes"], ex["accs"]
    edges: list[dict] = []

    def edge(a, b, kind, why):
        edges.append({"from": a, "to": b, "kind": kind, "why": why})

    reqs = {rr.req.rid: rr.req for rr in rv.req_results if nodes.get(rr.req.rid, {}).get("type") == "requirement"}
    rules = {rid: r for rid, r in reqs.items() if r.doc_id} or reqs
    # v13+: приёмка — для функциональных правил (НФТ проверяются измерением), как в depth.acceptance_coverage
    func = {rid: r for rid, r in rules.items() if re.search(r"функциональн|функционалдық", r.section or "", re.I)
            and not re.search(r"нефункциональн|функционалдық емес", r.section or "", re.I)}
    rules = func or rules
    raw_lines = {ln.lineno: ln.text for ln in doc.lines}
    # правило ↔ пример приёмки
    covered = set()
    for a in accs:
        sa = _stems(a.text)
        a_raw = " ".join(raw_lines.get(n, "") for n in range(a.line_start, a.line_end + 1)) + " " + \
            " ".join((a.extra or {}).get("refs", []) if isinstance(a.extra, dict) else [])
        for rid, r in rules.items():
            if r.doc_id and re.search(rf"(?<![\w-]){re.escape(r.doc_id.rstrip('.'))}(?![\w])", a_raw):
                edge(rid, a.rid, DOC_EDGE, f"в строке приёмки указан {r.doc_id}")
                covered.add(rid)
            elif len(_stems(r.text) & sa) >= 3:
                edge(rid, a.rid, CODE_EDGE, "общие термины правила и примера: "
                     + ", ".join(sorted(_stems(r.text) & sa)[:4]))
                covered.add(rid)
    ui = [n for n in nodes.values() if n["type"] in ("ui_field", "ui_action")]
    params = [n for n in nodes.values() if n["type"] == "api_param"]
    methods = [n for n in nodes.values() if n["type"] == "api_method"]
    # требование ↔ поле экрана (название поля в тексте требования)
    for n in ui:
        st = _stems(n["label"])
        for rid, r in reqs.items():
            if n["label"].lower() in r.text.lower():
                edge(rid, n["id"], DOC_EDGE, f"требование называет «{n['label']}»")
            elif st and st <= _stems(r.text):
                edge(rid, n["id"], CODE_EDGE, "общие термины требования и элемента экрана")
    # поле экрана ↔ параметр API (по описанию параметра; для переключателей — признак включения)
    linked_ui = set()
    for n in ui:
        if n["type"] != "ui_field":
            continue
        st = _stems(n["label"])
        for k, syn in _UI_SYNONYMS.items():
            if k in st:
                st |= syn
        for p in params:
            ps = _stems(p.get("description", "")) | _stems(p["label"])
            if st & ps:
                edge(n["id"], p["id"], CODE_EDGE, "поле экрана ↔ описание параметра: " + ", ".join(sorted(st & ps)[:3]))
                linked_ui.add(n["id"])
    # операция ↔ метод: чтение — GET или имя get/list; запись — POST/PUT/PATCH/DELETE или имя save/update/…
    def op(m):
        name = m.get("path", "")
        if _WRITE_NAME.search(name):
            return "write"
        if m["verb"] == "GET":
            return "read"
        return "write"
    ops = {"read": [m for m in methods if op(m) == "read"], "write": [m for m in methods if op(m) == "write"]}
    need: dict[str, tuple] = {}
    for rid, r in reqs.items():
        for kind, rx in (("read", _READ), ("write", _WRITE)):
            if (mm := rx.search(r.text)) and kind not in need:
                need[kind] = (rid, mm.group(0), r.text)
            if mm:
                for m in ops[kind]:
                    edge(rid, m["id"], CODE_EDGE, f"операция «{mm.group(0)}» ↔ метод {'чтения' if kind == 'read' else 'записи'}")
    for no, text, sec in ex["lines"]:  # интеграция и UI: «приложение читает и сохраняет настройки»
        if re.search(r"интеграц|\bUI\b|экран|дизайн", sec or "", re.I):
            for kind, rx in (("read", _READ), ("write", _WRITE)):
                if (mm := rx.search(text)) and kind not in need:
                    need[kind] = ("DOC", mm.group(0), text.strip())
    gaps: list[dict] = []
    if methods:  # разрывы «операция без метода» — только если в документе вообще есть спецификация API
        for kind, label in (("read", "чтения"), ("write", "записи")):
            if kind in need and not ops[kind]:
                rid, verb, text = need[kind]
                have = ", ".join(m["label"] for m in methods)
                gaps.append({"type": "operation_without_method", "node": rid, "quote": _quote_for(rid, verb, text, rv),
                             "problem": f"Операция «{verb}» описана в документе, но метода {label} в спецификации API нет "
                                        f"(есть только: {have}).",
                             "fix": f"Добавить метод {label} (путь, HTTP-метод, параметры, ответ) или указать, каким "
                                    "существующим методом выполняется операция.",
                             "severity": "major", "criterion": "set_complete",
                             "link": [r"метод\w*", r"чтени|получени|GET" if kind == "read" else r"запис|сохранени|изменени|POST|PUT"]})
    if params:
        for n in ui:
            if n["type"] == "ui_field" and n["id"] not in linked_ui:
                gaps.append({"type": "ui_field_without_param", "node": n["id"], "quote": n["quote"],
                             "problem": f"Поле экрана «{n['label']}» не связано ни с одним параметром API — непонятно, "
                                        "откуда берётся и куда сохраняется значение.",
                             "fix": "Указать параметр API (запроса или ответа), который соответствует полю, или пометить "
                                    "поле как вычисляемое на клиенте.", "severity": "minor", "criterion": "set_complete",
                             "link": [re.escape(n["label"].lower()[:5]), r"параметр"]})
        untyped = [p for p in params if not p.get("datatype") or p["datatype"] in ("—", "-")]
        if untyped:
            gaps.append({"type": "param_without_type", "node": untyped[0]["id"], "quote": untyped[0]["quote"],
                         "problem": "Параметры без типа: " + ", ".join(p["label"] for p in untyped[:8]) + ".",
                         "fix": "Указать тип и формат каждого параметра (string, integer, boolean; длина, диапазон).",
                         "severity": "minor", "criterion": "set_complete", "link": [r"тип\w*", r"параметр"]})
    statuses = [n for n in nodes.values() if n["type"] == "http_status"]
    bare = [n for n in statuses if not n["described"] and not n["example"]]
    if bare:
        n0 = bare[0]
        q = n0["quote"] if not n0.get("mention") else n0["mention"]
        gaps.append({"type": "status_without_description", "node": n0["id"], "quote": q,
                     "problem": "HTTP-статусы упомянуты без описания и без примера ответа: "
                                + ", ".join(n["label"] for n in bare) + " — клиент не знает, когда они возвращаются и что в теле.",
                     "fix": "Для каждого статуса — условие, при котором он возвращается, и пример тела ответа.",
                     "severity": "major" if len(bare) >= 2 else "minor", "criterion": "set_complete",
                     "link": [r"|".join(n["label"] for n in bare), r"статус|код\w* ответ|описан|пример"]})
    if accs:
        unc = [rid for rid in rules if rid not in covered]
        if unc and len(unc) < len(rules):  # приёмка есть, но часть правил без примеров
            r0 = rules[unc[0]]
            gaps.append({"type": "rule_without_acceptance", "node": unc[0], "quote": clip_quote(r0.text, 60),
                         "problem": "Правила без критерия приёмки: " + ", ".join(rules[r].doc_id or r for r in unc[:8]) + ".",
                         "fix": "Добавить к каждому правилу пример «исходные условия → действие → ожидаемый результат».",
                         "severity": "minor", "criterion": "set_validatable", "link": [r"приёмк|приемк", r"правил|пример"]})
    _link_or_add(rv, gaps)
    return {"nodes": list(nodes.values()), "edges": edges, "gaps": gaps,
            "stats": {"nodes": _count(nodes.values(), "type"), "edges": _count(edges, "kind"), "gaps": len(gaps),
                      "new_findings": sum(1 for g in gaps if g.get("new")),
                      "linked": sum(1 for g in gaps if not g.get("new"))}}


def _count(items, key) -> dict:
    out: dict[str, int] = {}
    for x in items:
        out[x[key]] = out.get(x[key], 0) + 1
    return out


def _quote_for(rid, verb, text, rv) -> str:
    """Дословная цитата вокруг глагола операции (не длиннее ~80 символов)."""
    i = text.lower().find(verb.lower())
    s = max(text.rfind(". ", 0, i) + 2 if text.rfind(". ", 0, i) >= 0 else 0, i - 60, 0)
    if s and text[s - 1] != " " and " " in text[s:i]:
        s = text.index(" ", s) + 1
    q = clip_quote(text[s:], 80)
    return q if quote_in(q, rv.doc.text) else clip_quote(text, 60)


def _link_or_add(rv, gaps: list[dict]) -> None:
    """Не дублировать найденное: разрыв связывается с замечанием, в тексте которого есть все ключи разрыва;
    иначе — новое замечание к набору (источник «трассировка (код)»)."""
    for g in gaps:
        keys = [re.compile(k, re.I) for k in g.pop("link")]
        hit = next((f for f in rv.set_findings if all(k.search(f.problem) for k in keys)), None)
        if hit is None:
            hit = next((f for rr in rv.req_results for f in rr.findings if all(k.search(f.problem) for k in keys)), None)
        if hit is not None:
            g["_finding"], g["new"] = hit, False
            continue
        q = g["quote"]
        rid = g["node"] if g["node"] in {rr.req.rid for rr in rv.req_results} else "DOC"
        src = next((rr.req.text for rr in rv.req_results if rr.req.rid == rid), rv.doc.text)
        if not quote_in(q, src):
            rid, src = "DOC", rv.doc.text
            if not quote_in(q, src):
                g["new"], g["skipped"] = False, "цитата не найдена дословно — замечание не создано"
                continue
        f = SetFinding("gap", g["criterion"], [SetRef(rid, q)], g["problem"], g["severity"], g["fix"], "трассировка (код)")
        rv.set_findings.append(f)
        g["_finding"], g["new"] = f, True


def finding_id(rv, f) -> str:
    for i, x in enumerate(rv.set_findings, 1):
        if x is f:
            return f"S-{i:02d}"
    for rr in rv.req_results:
        for n, x in enumerate(rr.findings, 1):
            if x is f:
                return f"{rr.req.rid}.{n}"
    return ""


def to_json(rv) -> dict:
    tr = getattr(rv, "traceability", None) or {}
    if not tr:
        return {}
    gaps = []
    for g in tr["gaps"]:
        f = g.get("_finding")
        gaps.append({k: v for k, v in g.items() if not k.startswith("_")} | {"finding": finding_id(rv, f) if f else ""})
    return {"nodes": tr["nodes"], "edges": tr["edges"], "gaps": gaps, "stats": tr["stats"]}


TYPE_RU = {"requirement": "требования", "acceptance": "критерии приёмки", "ui_field": "поля экрана",
           "ui_action": "действия экрана", "api_method": "методы API", "api_param": "параметры API",
           "http_status": "HTTP-статусы"}


def report_md(rv) -> list[str]:
    tr = to_json(rv)
    if not tr:
        return []
    st = tr["stats"]
    w = ["### Трассировка (граф, построен кодом без модели)", "",
         "Узлы: " + " · ".join(f"{TYPE_RU.get(k, k)} — {v}" for k, v in st["nodes"].items()) + ". Связи: "
         + " · ".join(f"{k} — {v}" for k, v in st["edges"].items()) + ".", ""]
    methods = [n for n in tr["nodes"] if n["type"] == "api_method"]
    if methods:
        w.append("Методы API: " + ", ".join(f"`{n['label']}`" for n in methods) + ".")
        w.append("")
    if tr["gaps"]:
        w += ["| Разрыв | Где | Замечание |", "|---|---|---|"]
        for g in tr["gaps"]:
            mark = (f"новое [{g['finding']}](#{g['finding'].lower()})" if g.get("new") else
                    f"уже найдено: [{g['finding']}](#{g['finding'].lower()})" if g.get("finding") else "—")
            w.append(f"| {g['problem'][:180].replace('|', '/')} | {g['node']} | {mark} |")
        w.append("")
    else:
        w += ["Разрывов трассировки не найдено.", ""]
    return w
