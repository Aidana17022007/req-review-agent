"""Офлайн-заглушка LLM для тестов и демонстрации без ключа (LLM_PROVIDER=mock).

Отвечает детерминированно на основе эвристик. Отчёт, сформированный в этом режиме,
помечается как тестовый и НЕ подходит для сдачи.
"""
from __future__ import annotations

import json
import re

from .llm import BaseLLM
from .splitter import MODAL_RE

_WORD = re.compile(r"[a-zа-яё]{5,}", re.IGNORECASE)
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


class MockLLM(BaseLLM):
    provider = "mock"
    model = "mock-heuristic"

    def __init__(self):
        super().__init__(min_interval=0, max_retries=0)

    def _call(self, system, prompt, *, task, context):
        if task == "check":
            return json.dumps(self._check(context), ensure_ascii=False)
        if task == "set":
            return json.dumps(self._set(context), ensure_ascii=False)
        if task == "gaps":  # проход полноты: одно подтверждаемое замечание и одна «галлюцинация» для проверки верификатора
            r = context["reqs"][0]
            return json.dumps({"findings": [
                {"check": "terms", "type": "gap", "criterion": "set_comprehensible",
                 "refs": [{"id": r.rid, "quote": " ".join(r.text.split()[:5])}],
                 "problem": "[mock] Термин в требовании не определён.", "severity": "minor", "fix": "[mock] Добавить определение."},
                {"check": "edge", "type": "gap", "refs": [{"id": "DOC", "quote": "этой фразы нет в документе"}],
                 "problem": "[mock] выдуманный пропуск", "severity": "major", "fix": "—"}]}, ensure_ascii=False)
        if task.startswith("focus_"):  # v6: узкий проход — одно подтверждаемое замечание и одна «галлюцинация»
            r = context["reqs"][-1]
            return json.dumps({"findings": [
                {"check": task, "type": "gap", "criterion": "set_validatable",
                 "refs": [{"id": r.rid, "quote": " ".join(r.text.split()[:4])}],
                 "problem": f"[mock] {task}: поведение не определено.", "severity": "major", "fix": "[mock] Дописать."},
                {"check": task, "type": "gap", "refs": [{"id": "DOC", "quote": "такой фразы в документе нет"}],
                 "problem": "[mock] выдуманный пропуск", "severity": "major", "fix": "—"}]}, ensure_ascii=False)
        if task == "crosscheck":
            return json.dumps({"findings": []}, ensure_ascii=False)
        if task == "critic":
            items = context["items"]
            return json.dumps({"verdicts": [{"n": it["n"], "verdict": "drop" if "[mock]" in it["problem"] and it["severity"] == "minor" else "keep",
                                             "reason": "[mock] оценка критика"} for it in items]}, ensure_ascii=False)
        if task == "extras":
            return json.dumps(self._extras(context), ensure_ascii=False)
        if task == "split":
            doc = context["doc"]
            reqs = [{"doc_id": None, "quote": l.text.strip()} for l in doc.lines if MODAL_RE.search(l.text)]
            return json.dumps({"requirements": reqs}, ensure_ascii=False)
        return "{}"

    def _check(self, ctx):
        out = []
        for r in ctx["reqs"]:
            findings, dismissed = [], []
            for h in ctx["hints"][r.rid]:
                if h.severity == "minor":
                    dismissed.extend(h.terms or [h.term])
                    continue
                findings.append({"criterion": h.criterion, "quote": h.quote,
                                 "problem": f"[mock] {h.problem}", "severity": h.severity, "fix": h.fix})
            if not _NUM.search(r.text) and re.search(r"время|скорост|производит|доступност|отклик", r.text, re.I):
                findings.append({"criterion": "verifiable", "quote": " ".join(r.text.split()[:6]),
                                 "problem": "[mock] Нефункциональное требование без числового значения.",
                                 "severity": "critical", "fix": "Добавить числовой порог и метод измерения."})
            # намеренная «галлюцинация» — должна быть отброшена верификатором
            if r.rid.endswith("1"):
                findings.append({"criterion": "correct", "quote": "этой фразы нет в документе",
                                 "problem": "[mock] выдуманное замечание", "severity": "major", "fix": "-"})
            vague = next((h for h in ctx["hints"][r.rid] if h.criterion in ("verifiable", "complete") and h.severity == "critical"), None)
            if vague:
                test = {"possible": False, "reason": "[mock] нет объективного критерия приёмки", "blocker_quote": vague.quote, "gherkin": ""}
            else:
                gh = (f"Дано система в рабочем состоянии\nКогда выполняется сценарий {r.doc_id or r.rid}\n"
                      f"Тогда {' '.join(r.text.split()[:12])}")
                scen = [{"title": f"{r.doc_id or r.rid}: основной сценарий", "gherkin": gh}]
                num = _NUM.search(r.text)
                if num:  # граничный сценарий для требований с порогом
                    scen.append({"title": f"{r.doc_id or r.rid}: граничное значение {num.group(0)}",
                                 "gherkin": f"Дано значение на границе {num.group(0)}\nКогда выполняется сценарий {r.doc_id or r.rid}\n"
                                            f"Тогда система ведёт себя согласно порогу {num.group(0)}"})
                test = {"possible": True, "scenarios": scen, "reason": "", "blocker_quote": ""}
            rewrite = ""
            if findings:
                # mock-«исправление»: убрать маркеры размытых формулировок из текста
                t = r.text.strip()
                for h in ctx["hints"][r.rid]:
                    for term in (h.terms or [h.term]):
                        t = re.sub(r"\s*,?\s*" + re.escape(term), "", t, flags=re.I)
                t = re.sub(r"\s{2,}", " ", t).strip(" ,.")
                if t and t != r.text.strip(" ."):
                    rewrite = t + "."
            ears = "event" if re.search(r"\b(после|когда|при)\b", r.text, re.I) else ("unwanted" if re.search(r"\bесли\b", r.text, re.I) else "ubiquitous")
            out.append({"id": r.rid, "ears": ears, "findings": findings, "dismissed_hints": dismissed,
                        "suggested_rewrite": rewrite, "test": test})
        return {"results": out}

    def _extras(self, ctx):
        doc_text = ctx["doc"].text
        cov = []
        for a in ctx.get("areas", []):
            hit = None
            for kw in a.get("keywords", []):
                m = re.search(r"[^\n]{0,30}" + re.escape(kw) + r"[^\n]{0,30}", doc_text, re.I)
                if m:
                    hit = m.group(0).strip()
                    break
            cov.append({"id": a["id"], "status": "covered" if hit else "missing", "quotes": [hit] if hit else [],
                        "comment": "[mock] найдено ключевое слово" if hit else "[mock] упоминаний не найдено"})
        syn = []
        low = doc_text.lower()
        groups = [["клиент", "пользователь", "абонент"], ["перевод", "операция", "транзакция"]]
        for g in groups:
            present = [w for w in g if w in low]
            if len(present) >= 2:
                syn.append({"terms": present, "preferred": present[0], "problem": "[mock] разные термины для одного понятия"})
        return {"coverage": cov, "synonyms": syn}

    def _set(self, ctx):
        reqs = ctx["reqs"]
        findings = []
        for i in range(len(reqs)):
            for j in range(i + 1, len(reqs)):
                a, b = reqs[i], reqs[j]
                wa = {w.lower() for w in _WORD.findall(a.text)}
                wb = {w.lower() for w in _WORD.findall(b.text)}
                na = set(_NUM.findall(re.sub(r"(?<=\d) (?=\d{3})", "", a.text)))
                nb = set(_NUM.findall(re.sub(r"(?<=\d) (?=\d{3})", "", b.text)))
                if len(wa & wb) >= 3 and na and nb and na != nb:
                    findings.append({
                        "type": "contradiction", "criterion": "set_consistent",
                        "refs": [{"id": a.rid, "quote": a.text[:60]}, {"id": b.rid, "quote": b.text[:60]}],
                        "problem": f"[mock] Требования об одном и том же задают разные значения: {sorted(na)} и {sorted(nb)}.",
                        "severity": "critical", "fix": "Согласовать значение и оставить его в одном требовании."})
        if not any(re.search(r"ошибк|сбо|недоступ", r.text, re.I) for r in reqs) and reqs:
            findings.append({"type": "gap", "criterion": "set_complete",
                             "refs": [{"id": reqs[0].rid, "quote": reqs[0].text[:50]}],
                             "problem": "[mock] Не описано поведение системы при ошибках и сбоях.",
                             "severity": "major", "fix": "Добавить требования к обработке ошибок."})
        return {"findings": findings}
