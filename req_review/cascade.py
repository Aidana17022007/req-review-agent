"""v9: каскад моделей — быстрая модель проверяет всё, сильная — только подозрительное.

`--cascade fast,strong` (или LLM_CASCADE): пакеты требований (задача "check") сначала проверяет быстрая модель.
Если в пакете есть подозрительные требования — существенное или критичное замечание, тест составить невозможно,
сработало правило агента — тот же пакет проверяет сильная модель, и для подозрительных требований берётся её ответ.
Проходы по набору (противоречия, полнота, узкие проходы), критик, ответы аналитика и повестка решений — сразу
сильной моделью: участники противоречий выявляются именно там. В паспорте — сколько требований ушло на сильную модель
и обращения каждой модели.
"""
from __future__ import annotations

from .llm import LLMStats

FAST_TASKS = {"check", "split"}  # остальное — сильной моделью


class CascadeLLM:
    def __init__(self, fast, strong):
        self.fast, self.strong = fast, strong
        self.provider = fast.provider
        self.model = f"{fast.model} → {strong.model}"
        self.stats = LLMStats()
        self.strong_reqs: set[str] = set()
        self.checked_reqs: set[str] = set()
        self.fallback_models: list[str] = []

    @property
    def label(self) -> str:
        return f"{self.fast.label} + {self.strong.label} (каскад)"

    # температура и повторы — обеим моделям (самосогласованность меняет температуру на время прохода)
    @property
    def temperature(self):
        return getattr(self.fast, "temperature", None)

    @temperature.setter
    def temperature(self, v):
        for m in (self.fast, self.strong):
            if hasattr(m, "temperature"):
                m.temperature = v

    @property
    def max_retries(self):
        return self.fast.max_retries

    @max_retries.setter
    def max_retries(self, v):
        self.fast.max_retries = self.strong.max_retries = v

    def _sync(self) -> None:
        a, b = self.fast.stats, self.strong.stats
        for k in ("calls", "cached", "retries", "prompt_tokens", "output_tokens"):
            setattr(self.stats, k, getattr(a, k) + getattr(b, k))
        self.stats.switches = list(a.switches) + list(b.switches)
        self.stats.errors = list(a.errors) + list(b.errors)

    @staticmethod
    def suspicious(data: dict, context: dict | None) -> set[str]:
        """ID требований пакета, которые стоит перепроверить сильной моделью."""
        out = set()
        hints = (context or {}).get("hints") or {}
        for item in (data or {}).get("results", []) or []:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("id", "")).strip()
            sev = {str(f.get("severity", "")).lower() for f in item.get("findings", []) or [] if isinstance(f, dict)}
            test = item.get("test") or {}
            if sev & {"major", "critical"} or (isinstance(test, dict) and test.get("possible") is False) or hints.get(rid):
                out.add(rid)
        for r in (context or {}).get("reqs", []) or []:  # правило сработало, а модель требование пропустила
            if hints.get(r.rid) and r.rid not in {str(i.get("id", "")).strip() for i in (data or {}).get("results", []) or []
                                                    if isinstance(i, dict)}:
                out.add(r.rid)
        return out

    def generate_json(self, system: str, prompt: str, *, task: str = "", context: dict | None = None) -> dict:
        try:
            if task not in FAST_TASKS:
                return self.strong.generate_json(system, prompt, task=task, context=context)
            first = self.fast.generate_json(system, prompt, task=task, context=context)
            if task != "check":
                return first
            self.checked_reqs |= {r.rid for r in (context or {}).get("reqs", []) or []}
            sus = self.suspicious(first, context)
            if not sus:
                return first
            second = self.strong.generate_json(system, prompt, task=task, context=context)
            self.strong_reqs |= sus
            by_strong = {str(i.get("id", "")).strip(): i for i in (second or {}).get("results", []) or [] if isinstance(i, dict)}
            merged = []
            seen = set()
            for item in (first or {}).get("results", []) or []:
                rid = str(item.get("id", "")).strip() if isinstance(item, dict) else ""
                merged.append(by_strong.get(rid, item) if rid in sus else item)
                seen.add(rid)
            merged += [i for rid, i in by_strong.items() if rid in sus and rid not in seen]
            return {**(first or {}), "results": merged}
        finally:
            self._sync()

    def passport(self) -> dict:
        return {"fast": self.fast.label, "strong": self.strong.label, "strong_reqs": len(self.strong_reqs),
                "checked_reqs": len(self.checked_reqs),
                "calls": {"fast": self.fast.stats.calls, "strong": self.strong.stats.calls}}


def build_cascade(spec: str):
    """«fast,strong» → CascadeLLM; модели — того же провайдера, что в .env."""
    from .ensemble import model_env, parse
    from .llm import build_llm_from_env

    models = parse(spec)
    if not models:
        raise ValueError("Каскад: укажите две модели через запятую — быстрая,сильная (например gemini-3.5-flash-lite,gemini-3.8-flash)")
    with model_env(models[0]):
        fast = build_llm_from_env()
    with model_env(models[1]):
        strong = build_llm_from_env()
    return CascadeLLM(fast, strong)
