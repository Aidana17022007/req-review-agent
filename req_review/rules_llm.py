"""Режим «только правила»: прогон без языковой модели — когда квота API исчерпана или нет сети.

Замечания дают только детерминированные проверки агента (rules.py: размытые слова, плейсхолдеры, TBD;
numbers.py: числовые конфликты; правила API и набора в checker.py). Модель не вызывается, данные никуда
не уходят. Это не mock: в замечаниях нет эвристических «[mock]»-находок и намеренных ошибок для тестов,
но и смысловых противоречий, которые находит модель, здесь не будет — паспорт отчёта это указывает.
"""
from __future__ import annotations

import json

from .llm import BaseLLM


class RulesOnlyLLM(BaseLLM):
    provider = "rules"
    model = "только правила"

    def __init__(self):
        super().__init__(min_interval=0, max_retries=0)

    @property
    def label(self) -> str:
        return "без модели / только детерминированные правила"

    def generate_json(self, system, prompt, *, task: str = "", context: dict | None = None) -> dict:
        # без кэша, ретраев и счётчика обращений: в паспорте «обращений к модели» должно остаться 0
        return json.loads(self._call(system, prompt, task=task, context=context or {}))

    @staticmethod
    def _coverage(context) -> list[dict]:
        """Область покрыта, если её ключевое слово есть в тексте (цитата — дословная строка документа, ≤ 160 символов);
        раньше без модели все области считались непокрытыми — ложная тревога на любом полном ТЗ."""
        doc = context.get("doc")
        lines = [ln.text.strip() for ln in getattr(doc, "lines", [])] if doc is not None else []
        out = []
        for a in context.get("areas", []) or []:
            kws = [k.lower() for k in a.get("keywords", []) if k]
            hit = next((ln for ln in lines if ln and any(k in ln.lower() for k in kws)), None)
            if hit:
                low = hit.lower()
                k = next(k for k in kws if k in low)
                i = low.index(k)
                q = hit[max(0, i - 60): i + 80].strip()
                out.append({"id": a["id"], "status": "covered", "quotes": [q], "comment": "найдено ключевое слово (без модели)"})
            else:
                out.append({"id": a["id"], "status": "missing", "quotes": [], "comment": ""})
        return out

    def _call(self, system, prompt, *, task, context):
        if task == "check":
            out = []
            for r in context.get("reqs", []):
                findings = [{"criterion": h.criterion, "quote": h.quote, "problem": h.problem,
                             "severity": h.severity, "fix": h.fix}
                            for h in context.get("hints", {}).get(r.rid, []) if h.severity != "minor"]
                out.append({"id": r.rid, "findings": findings, "dismissed": []})
            return json.dumps({"results": out}, ensure_ascii=False)
        if task in ("set", "crosscheck"):
            return json.dumps({"findings": []}, ensure_ascii=False)
        if task == "extras":  # v13+: без модели — покрытие областей доменного чек-листа по ключевым словам
            return json.dumps({"coverage": self._coverage(context), "synonyms": []}, ensure_ascii=False)
        if task == "critic":
            return json.dumps({"verdicts": [{"n": it["n"], "verdict": "keep", "reason": "правило"}
                                            for it in context.get("items", [])]}, ensure_ascii=False)
        return "{}"
