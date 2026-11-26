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
        if task == "critic":
            return json.dumps({"verdicts": [{"n": it["n"], "verdict": "keep", "reason": "правило"}
                                            for it in context.get("items", [])]}, ensure_ascii=False)
        return "{}"
