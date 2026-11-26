"""AI-ассистент Studio: отвечает на вопросы по готовому отчёту.

Частые вопросы («Почему R-006 критичное?», «Что исправить первым?») разбираются детерминированно по report.json —
без обращения к модели и без расхода квоты. Остальное, если модель доступна, уходит в LLM с компактной выжимкой отчёта.
Ссылки на требования в ответе — токены [[R-006]] / [[S-01]]; интерфейс превращает их в кнопки перехода.
"""
from __future__ import annotations

import json
import re

from ..criteria import criterion_name, criterion_ref

ORDER = {"critical": 0, "major": 1, "minor": 2, "ok": 3}
SEV = {"critical": "критичное", "major": "существенное", "minor": "незначительное", "ok": "без замечаний"}
SEV_ADJ = {"critical": "критичный", "major": "существенный", "minor": "незначительный"}
KIND = {"contradiction": "противоречие", "duplicate": "дублирование", "terminology": "терминология", "gap": "пропуск",
        "dependency": "зависимость", "structure": "структура", "other": "прочее"}

SYSTEM = (
    "Ты — AI-ассистент ReqLens, помогаешь аналитику разобраться в отчёте о проверке требований "
    "(ISO/IEC/IEEE 29148, IEEE 830). Отвечай по-русски, кратко (до 8 предложений или пунктов), только по данным отчёта "
    "из сообщения пользователя; если данных нет — так и скажи. Ссылаясь на требование или замечание к набору, "
    "пиши его ID отчёта в двойных квадратных скобках: [[R-006]], [[S-01]]. "
    'Верни только JSON: {"answer": "текст ответа"}'
)


def _worst(r: dict) -> str:
    return min((f["severity"] for f in r["findings"]), key=ORDER.get, default="ok")


def _lbl(r: dict) -> str:
    return f"[[{r['rid']}]]" + (f" ({r['doc_id']})" if r.get("doc_id") else "")


class Assistant:
    def __init__(self, data: dict):
        self.d = data
        self.reqs = data["requirements"]
        self.by_rid = {r["rid"]: r for r in self.reqs}
        self.by_doc = {r["doc_id"].lower(): r for r in self.reqs if r.get("doc_id")}
        self.sets = {f"S-{i:02d}": f for i, f in enumerate(data.get("set_findings", []), 1)}
        # схема 2.2 (RAG): основания замечаний — дословные фрагменты базы знаний с источником
        self.has_basis = any(f.get("basis") for r in self.reqs for f in r["findings"]) or any(f.get("basis") for f in self.sets.values())
        self._extra: list[dict] = []  # дополнительные источники ответа (фрагменты документа и базы знаний)

    # ------------------------------------------------------------ разбор вопроса
    def refs_in(self, q: str) -> list[str]:
        out = []
        for m in re.finditer(r"\b[RrРр]-?\s?(\d{1,4})\b", q):
            rid = f"R-{int(m.group(1)):03d}"
            if rid in self.by_rid and rid not in out:
                out.append(rid)
        for m in re.finditer(r"\b[SsЅ]-?(\d{1,3})\b", q):
            sid = f"S-{int(m.group(1)):02d}"
            if sid in self.sets and sid not in out:
                out.append(sid)
        low = q.lower()
        for did, r in self.by_doc.items():
            if re.search(r"(?<![\w-])" + re.escape(did) + r"(?![\w-])", low) and r["rid"] not in out:
                out.append(r["rid"])
        return out

    def answer(self, q: str, llm_factory=None) -> dict:
        q = (q or "").strip()[:500]
        low = q.lower().replace("ё", "е")
        has = lambda *ws: any(w in low for w in ws)  # noqa: E731
        refs = self.refs_in(q)
        if not q or has("привет", "помощ", "что ты умеешь", "что умеешь", "help"):
            return self._reply(self.help())
        if self.has_basis and has("норм", "основан", "стандарт", "пункт", "опира"):
            if refs:
                return self._reply("\n\n".join(self.basis_for(x) for x in refs[:3]))
        if self.has_basis and has("закон", "персональн", "регулятор", "норматив"):
            return self._reply(self.law_violations("персональн" if "персональн" in low else ""))
        if refs:
            parts = [self.explain_set(x) if x.startswith("S-") else self.explain_req(x, low) for x in refs[:3]]
            return self._reply("\n\n".join(parts))
        if has("первым", "первую очередь", "приоритет", "с чего начать", "начать с", "самое важное", "срочно"):
            return self._reply(self.priorities())
        if has("противореч", "конфликт"):
            return self._reply(self.set_kind("contradiction", "Противоречия"))
        if has("дубл", "повтор"):
            return self._reply(self.set_kind("duplicate", "Дубликаты"))
        if has("тест", "gherkin", "проверяем"):
            return self._reply(self.tests())
        if has("готов", "начинать", "можно ли", "вердикт", "итог"):
            return self._reply(self.verdict())
        if has("вопрос", "уточн", "аналитик", "заказчик"):
            return self._reply(self.questions())
        if has("балл", "оценк", "score", "рейтинг"):
            return self._reply(self.score())
        if has("финтех", "домен", "полнот", "чек-лист", "чеклист"):
            return self._reply(self.domain())
        if has("термин", "глоссар"):
            return self._reply(self.glossary())
        if has("критичн", "худш", "плох", "проблемн"):
            return self._reply(self.by_severity("critical"))
        if has("сколько", "сводк", "статист", "обзор", "кратко"):
            return self._reply(self.summary())
        if llm_factory is not None:
            got = self.ask_llm(q, llm_factory)
            if got:
                return got
        return self._reply("Я пока не понял вопрос. " + self.help(), source="подсказка")

    def _reply(self, text: str, source: str = "отчёт") -> dict:
        extra, self._extra = self._extra, []
        refs = []
        def keep(m):
            x = m.group(1)
            if x in self.by_rid or x in self.sets:
                refs.append(x)
                return f"[[{x}]]"
            return x
        text = re.sub(r"\[\[([^\]]{1,20})\]\]", keep, text)
        refs = list(dict.fromkeys(refs))
        # источники ответа: требования (переход в отчёт), фрагменты документа (строка), фрагменты базы знаний (карточка с URL)
        sources = [{"type": "req", "id": x, "label": (self.by_rid[x].get("doc_id") or x) if x in self.by_rid else x} for x in refs]
        seen = set()
        for x in extra:
            key = (x["type"], x.get("line"), x.get("source"), x.get("clause"))
            if key not in seen:
                seen.add(key)
                sources.append(x)
        return {"answer": text, "refs": refs, "source": source, "suggest": self.suggest(), "sources": sources[:12]}

    # ------------------------------------------------------------ источники (RAG 2.2)
    def _cite_line(self, r: dict, f: dict | None = None) -> None:
        span = (f or {}).get("span") or {}
        line = span.get("line") or r.get("line_start")
        if line:
            self._extra.append({"type": "line", "line": int(line), "rid": r["rid"],
                                "text": ((f or {}).get("quote") or r["text"])[:160]})

    def _cite_basis(self, f: dict) -> None:
        for b in f.get("basis") or []:
            if b.get("quote") and b.get("source"):
                self._extra.append({"type": "kb", "kind": b.get("kind", "standard"), "source": b["source"], "clause": b.get("clause", ""),
                                    "quote": b["quote"][:300], "url": b.get("url", "") if str(b.get("url", "")).startswith("https://") else "",
                                    "paraphrase": bool(b.get("paraphrase"))})

    def basis_for(self, x: str) -> str:
        """На какую норму опирается замечание к требованию (или к набору)."""
        if x.startswith("S-"):
            f = self.sets[x]
            self._cite_basis(f)
            bs = f.get("basis") or []
            return (f"[[{x}]] опирается на: " + "; ".join(f"{b['source']}" + (f", {b['clause']}" if b.get("clause") else "") for b in bs) + "."
                    if bs else f"Для [[{x}]] основание в базе знаний не найдено.")
        r = self.by_rid[x]
        if not r["findings"]:
            return f"{_lbl(r)}: замечаний нет — ссылаться не на что."
        lines = [f"{_lbl(r)} — основания замечаний:"]
        for f in sorted(r["findings"], key=lambda f: ORDER[f["severity"]])[:4]:
            self._cite_line(r, f)
            bs = f.get("basis") or []
            self._cite_basis(f)
            src = "; ".join(f"{b['source']}" + (f", {b['clause']}" if b.get("clause") else "") for b in bs) or "основание в базе знаний не найдено"
            lines.append(f"• {criterion_name(f['criterion'])} ({SEV_ADJ[f['severity']]}): «{f['quote'][:80]}» → {src}")
        lines.append("Цитаты норм — в карточках источников ниже; дословный текст закона открывается по ссылке.")
        return "\n".join(lines)

    def law_violations(self, topic: str = "") -> str:
        """Какие требования нарушают нормы закона (по основаниям вида «закон РК»)."""
        hits = []
        for r in self.reqs:
            for f in r["findings"]:
                laws = [b for b in f.get("basis") or [] if b.get("kind") == "law" and (not topic or topic in (b.get("source", "") + b.get("clause", "")).lower())]
                if laws:
                    hits.append((r, f, laws))
        for sid, f in self.sets.items():
            laws = [b for b in f.get("basis") or [] if b.get("kind") == "law" and (not topic or topic in (b.get("source", "") + b.get("clause", "")).lower())]
            if laws:
                hits.append((None, f | {"_sid": sid}, laws))
        if not hits:
            return "Замечаний с основанием в законах РК" + (" о персональных данных" if topic else "") + " не найдено."
        lines = [f"Замечаний с опорой на закон{' о персональных данных' if topic else ''}: {len(hits)}."]
        for r, f, laws in hits[:8]:
            for b in laws:
                self._cite_basis({"basis": [b]})
            who = _lbl(r) if r else f"[[{f['_sid']}]] (набор)"
            if r:
                self._cite_line(r, f)
            lines.append(f"• {who} — {criterion_name(f['criterion'])}: {f['problem'][:160]} → {laws[0]['source']}"
                         + (f", {laws[0]['clause']}" if laws[0].get("clause") else ""))
        return "\n".join(lines)

    # ------------------------------------------------------------ ответы по отчёту
    def help(self) -> str:
        return ("Я отвечаю по данным этого отчёта. Спросите, например:\n• «Почему R-006 критичное?»\n• «Что исправить первым?»\n"
                "• «Какие есть противоречия?»\n• «Сколько требований тестируемо?»\n• «Можно ли начинать разработку?»")

    def suggest(self) -> list[str]:
        worst = sorted(self.reqs, key=lambda r: (ORDER[_worst(r)], r["score"]))
        out = []
        if worst and _worst(worst[0]) != "ok":
            out.append(f"Почему {worst[0]['rid']} {SEV[_worst(worst[0])]}?")
        out += ["Что исправить первым?", "Можно ли начинать разработку?"]
        if self.has_basis and worst and worst[0]["findings"]:
            out.insert(1, f"На какую норму опирается замечание к {worst[0]['rid']}?")
            if any(b.get("kind") == "law" for r in self.reqs for f in r["findings"] for b in f.get("basis") or []):
                out.insert(2, "Какие требования нарушают закон о персональных данных?")
        if any(f["kind"] == "contradiction" for f in self.sets.values()):
            out.append("Какие есть противоречия?")
        out.append("Сколько требований тестируемо?")
        return out[:5]

    def explain_req(self, rid: str, low: str) -> str:
        r = self.by_rid[rid]
        w = _worst(r)
        head = f"{_lbl(r)} — {SEV[w]}, балл {r['score']}/100."
        if "критичн" in low and w != "critical":
            head += f" Критичных замечаний у него нет — худшее: {SEV[w]}." if w != "ok" else " Замечаний нет — оно не критичное."
        lines = [head, f"Формулировка: «{r['text'][:220]}{'…' if len(r['text']) > 220 else ''}»"]
        if r["findings"]:
            lines.append("Почему:")
            for f in sorted(r["findings"], key=lambda f: ORDER[f["severity"]])[:4]:
                self._cite_line(r, f)
                self._cite_basis(f)
                lines.append(f"• {criterion_name(f['criterion'])} ({criterion_ref(f['criterion'])}) — {SEV_ADJ[f['severity']]}: "
                             f"«{f['quote'][:90]}» — {f['problem'][:220]}")
        t = r.get("test") or {}
        if t.get("possible") is False:
            lines.append(f"Тест-проба: приёмочный тест составить невозможно — {t.get('reason', '')}"
                         + (f" (мешает «{t['blocker']}»)." if t.get("blocker") else "."))
        elif t.get("possible") is True:
            lines.append("Тест-проба: приёмочный сценарий составлен — см. раздел «Тесты».")
        links = [f for f in self.sets.items() if any(x["req_id"] == rid for x in f[1].get("refs", []))]
        for sid, f in links[:3]:
            others = [x["req_id"] for x in f["refs"] if x["req_id"] not in (rid, "DOC")]
            lines.append(f"Связь [[{sid}]]: {KIND.get(f['kind'], f['kind'])}" + (f" с {', '.join('[[' + o + ']]' for o in others)}" if others else "")
                         + f" — {f['problem'][:160]}")
        if r["findings"]:
            top = min(r["findings"], key=lambda f: ORDER[f["severity"]])
            lines.append(f"Что сделать: {top['fix']}")
        if r.get("rewrite") and r["findings"]:
            lines.append(f"Предложенная формулировка: «{r['rewrite']}»")
        return "\n".join(lines)

    def explain_set(self, sid: str) -> str:
        f = self.sets[sid]
        refs = ", ".join(f"[[{x['req_id']}]]" for x in f.get("refs", []) if x["req_id"] in self.by_rid) or "документ"
        return (f"[[{sid}]] — {KIND.get(f['kind'], f['kind'])}, {SEV[f['severity']]} ({criterion_name(f['criterion'])}). "
                f"Затрагивает: {refs}.\n{f['problem']}\nКак исправить: {f['fix']}")

    def priorities(self) -> str:
        items = []
        for sid, f in self.sets.items():
            if f["severity"] != "minor":
                items.append((ORDER[f["severity"]] * 2, f"[[{sid}]] {KIND.get(f['kind'], f['kind'])}: {f['fix']}"))
        for r in self.reqs:
            if not r["findings"]:
                continue
            f = min(r["findings"], key=lambda f: ORDER[f["severity"]])
            if f["severity"] != "minor":
                # внутри одной тяжести — сначала требования с меньшим баллом
                items.append((ORDER[f["severity"]] * 2 + 1 + r["score"] / 1000, f"{_lbl(r)} — {criterion_name(f['criterion'])}: {f['fix']}"))
        if not items:
            return "Обязательных исправлений нет: критичных и существенных замечаний не найдено."
        items.sort(key=lambda x: x[0])
        return "Исправить в первую очередь (сначала критичные и противоречия набора):\n" + "\n".join(
            f"{i}. {t}" for i, (_, t) in enumerate(items[:6], 1))

    def set_kind(self, kind: str, title: str) -> str:
        fs = [(sid, f) for sid, f in self.sets.items() if f["kind"] == kind]
        if not fs:
            return f"{title} между требованиями не найдены."
        return f"{title}: {len(fs)}.\n" + "\n".join(
            f"• [[{sid}]] ({SEV[f['severity']]}): " + " ↔ ".join(f"[[{x['req_id']}]]" for x in f["refs"] if x["req_id"] in self.by_rid)
            + f" — {f['problem'][:180]}" for sid, f in fs[:6])

    def tests(self) -> str:
        ok = [r for r in self.reqs if (r.get("test") or {}).get("possible") is True]
        bad = [r for r in self.reqs if (r.get("test") or {}).get("possible") is False]
        s = self.d["scores"]["tests"]
        out = f"Тестируемо {s['ok']} из {s['total']} требований."
        if bad:
            out += "\nНельзя составить приёмочный тест:\n" + "\n".join(f"• {_lbl(r)} — {r['test'].get('reason', '')}" for r in bad[:6])
        elif ok:
            out += " Для всех проверенных требований сценарии составлены — скачайте tests.feature в разделе «Тесты»."
        return out

    def counts(self) -> dict:
        fs = [f for r in self.reqs for f in r["findings"]] + list(self.sets.values())
        return {k: sum(1 for f in fs if f["severity"] == k) for k in ("critical", "major", "minor")}

    def verdict(self) -> str:
        c, sc = self.counts(), self.d["scores"]
        if c["critical"]:
            v = f"Начинать разработку нельзя: {c['critical']} критичных дефектов — по затронутым требованиям нельзя составить тесты и критерии приёмки."
        elif c["major"]:
            v = "Можно начинать условно: критичных дефектов нет, но существенные замечания нужно закрыть до написания тест-кейсов."
        else:
            v = "Можно начинать разработку и тестирование: критичных и существенных дефектов нет."
        return f"{v}\nБалл документа {sc['document']}/100, готовность к разработке {sc['readiness']}%."

    def score(self) -> str:
        sc = self.d["scores"]
        worst = sorted(self.reqs, key=lambda r: r["score"])[:3]
        return (f"Балл документа — {sc['document']}/100, балл набора — {sc['set']}/100, готовность — {sc['readiness']}%.\n"
                "Балл требования — 100 минус штрафы за нарушенные критерии (каждый критерий учитывается один раз, по худшему замечанию); "
                "формулы — в разделе «Экспорт → Методика оценки».\nНиже всего: "
                + ", ".join(f"{_lbl(r)} — {r['score']}" for r in worst) + ".")

    def questions(self) -> str:
        qs = self.d.get("questions", [])
        if not qs:
            return "Вопросов аналитику нет: существенных неопределённостей не найдено."
        def ref(q):
            m = re.search(r"\b(R-\d+|S-\d+)\b", q["ref"])
            return f"[[{m.group(1)}]]" if m else q["ref"]
        return f"Вопросов аналитику: {len(qs)} (полный список и экспорт в .md — раздел «Исправления»). Главные:\n" + "\n".join(
            f"• {ref(q)}: {q['text'][:200]}" for q in sorted(qs, key=lambda q: ORDER.get(q["severity"], 3))[:4])

    def domain(self) -> str:
        d = self.d.get("domain")
        if not d:
            return "Доменный чек-лист отключён — запустите проверку с доменом «Финтех»."
        miss = [a for a in d.get("areas", []) if a.get("status") == "missing"]
        part = [a for a in d.get("areas", []) if a.get("status") == "partial"]
        cov = round(100 * sum(1 if a["status"] == "covered" else 0.5 if a["status"] == "partial" else 0 for a in d["areas"]) / max(1, len(d["areas"])))
        out = f"Покрытие финтех-чек-листа ≈{cov}%."
        if miss:
            out += "\nНе покрыто: " + "; ".join(a["title"] for a in miss[:6]) + "."
        if part:
            out += "\nЧастично: " + "; ".join(a["title"] for a in part[:6]) + "."
        return out

    def glossary(self) -> str:
        g = self.d.get("glossary")
        if not g:
            return "Глоссарий не построен."
        syn = g.get("synonyms", [])
        undef = [t["term"] for t in g.get("terms", []) if not t.get("defined")]
        out = f"Терминов в глоссарии: {len(g.get('terms', []))}."
        if syn:
            out += "\nРазнобой терминов: " + "; ".join(" / ".join(s["terms"]) + f" → «{s['preferred']}»" for s in syn[:4]) + "."
        if undef:
            out += "\nНе определены: " + ", ".join(undef[:8]) + "."
        return out

    def by_severity(self, sev: str) -> str:
        rs = [r for r in self.reqs if _worst(r) == sev]
        if not rs:
            return f"Требований с худшим статусом «{SEV[sev]}» нет."
        return f"Требования со статусом «{SEV[sev]}»: {len(rs)}.\n" + "\n".join(
            f"• {_lbl(r)} — балл {r['score']}: {criterion_name(min(r['findings'], key=lambda f: ORDER[f['severity']])['criterion'])}"
            for r in sorted(rs, key=lambda r: r["score"])[:8])

    def summary(self) -> str:
        c, sc = self.counts(), self.d["scores"]
        clean = sum(1 for r in self.reqs if not r["findings"])
        return (f"Требований: {len(self.reqs)}, без замечаний: {clean}. Замечаний: критичных {c['critical']}, существенных {c['major']}, "
                f"незначительных {c['minor']}. Балл {sc['document']}/100, готовность {sc['readiness']}%, "
                f"тестируемо {sc['tests']['ok']} из {sc['tests']['total']}.")

    # ------------------------------------------------------------ свободный вопрос — к модели
    def context(self) -> str:
        reqs = [{"id": r["rid"], "doc_id": r.get("doc_id"), "text": r["text"][:220], "score": r["score"], "status": _worst(r),
                 "findings": [{"criterion": criterion_name(f["criterion"]), "severity": f["severity"], "problem": f["problem"][:160],
                               "fix": f["fix"][:120]} for f in r["findings"][:4]],
                 "testable": (r.get("test") or {}).get("possible")} for r in self.reqs[:120]]
        sets = [{"id": sid, "kind": f["kind"], "severity": f["severity"], "refs": [x["req_id"] for x in f["refs"]], "problem": f["problem"][:200]}
                for sid, f in self.sets.items()]
        sc = self.d["scores"]
        return json.dumps({"document": self.d.get("passport", {}).get("document"), "score": sc["document"], "readiness": sc["readiness"],
                           "tests": sc["tests"], "requirements": reqs, "set_findings": sets}, ensure_ascii=False)[:60000]

    def ask_llm(self, q: str, llm_factory) -> dict | None:
        try:
            llm = llm_factory()
            if getattr(llm, "provider", "") == "mock":
                return None
            # Чат не должен «висеть» минутами на ретраях 429/503 (как полный прогон): одна попытка, короткий таймаут
            llm.max_retries = 1
            llm.min_interval = 0
            llm.timeout = 25.0
            data = llm.generate_json(SYSTEM, f"ДАННЫЕ ОТЧЁТА (JSON):\n{self.context()}\n\nВОПРОС: {q}", task="assistant")
            text = str((data or {}).get("answer", "")).strip()
            return self._reply(text, source="модель") if text else None
        except Exception as e:  # лимит API, нет ключа — отвечаем подсказкой, а не ошибкой
            from .live import classify_error

            kind = classify_error(str(e))
            note = {"quota": "Лимит API исчерпан — свободные вопросы временно недоступны.",
                    "key": "Ключ модели не настроен — свободные вопросы недоступны."}.get(kind, "Модель сейчас недоступна.")
            return self._reply(f"{note} Я по-прежнему отвечаю на типовые вопросы по отчёту.\n\n{self.help()}", source="подсказка")
