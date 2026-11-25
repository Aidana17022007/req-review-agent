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
            out.append({"id": r.rid, "findings": findings, "dismissed_hints": dismissed, "suggested_rewrite": ""})
        return {"results": out}

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
