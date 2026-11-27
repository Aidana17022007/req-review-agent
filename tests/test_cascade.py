"""v9: каскад моделей — быстрая проверяет всё, сильная — подозрительные требования и проходы по набору (mock)."""
import json
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent.parent


class Fake:
    def __init__(self, name, results):
        from req_review.llm import LLMStats

        self.provider, self.model, self.label = "fake", name, f"fake / {name}"
        self.stats, self.results, self.tasks, self.max_retries, self.temperature = LLMStats(), results, [], 3, 0.0

    def generate_json(self, system, prompt, *, task="", context=None):
        self.tasks.append(task)
        self.stats.calls += 1
        return {"results": self.results} if task == "check" else {"findings": []}


def test_only_suspicious_requirements_go_to_strong_model():
    from req_review.cascade import CascadeLLM

    fast = Fake("fast", [{"id": "R-1", "findings": []},
                         {"id": "R-2", "findings": [{"severity": "major", "problem": "быстрая"}]},
                         {"id": "R-3", "findings": [], "test": {"possible": False}}])
    strong = Fake("strong", [{"id": "R-1", "findings": [{"severity": "minor", "problem": "сильная"}]},
                             {"id": "R-2", "findings": [{"severity": "critical", "problem": "сильная"}]},
                             {"id": "R-3", "findings": [{"severity": "major", "problem": "сильная"}]}])
    c = CascadeLLM(fast, strong)
    reqs = [NS(rid=f"R-{i}") for i in (1, 2, 3, 4)]
    out = c.generate_json("s", "p", task="check", context={"reqs": reqs, "hints": {"R-4": ["правило"]}})
    by = {r["id"]: r for r in out["results"]}
    assert by["R-1"]["findings"] == []  # не подозрительное — ответ быстрой модели
    assert by["R-2"]["findings"][0]["problem"] == "сильная" and by["R-3"]["findings"][0]["problem"] == "сильная"
    assert c.strong_reqs == {"R-2", "R-3", "R-4"}  # R-4: сработало правило, а быстрая модель его пропустила
    c.generate_json("s", "p", task="set", context={})  # набор — сразу сильной
    assert fast.tasks == ["check"] and strong.tasks == ["check", "set"]
    assert c.stats.calls == 3 and c.passport()["calls"] == {"fast": 1, "strong": 2}
    c.temperature = 0.4
    assert fast.temperature == strong.temperature == 0.4


def test_clean_batch_never_calls_strong_model():
    from req_review.cascade import CascadeLLM

    fast, strong = Fake("fast", [{"id": "R-1", "findings": [{"severity": "minor"}]}]), Fake("strong", [])
    c = CascadeLLM(fast, strong)
    c.generate_json("s", "p", task="check", context={"reqs": [NS(rid="R-1")], "hints": {}})
    assert strong.tasks == [] and c.passport()["strong_reqs"] == 0


def test_pipeline_cascade_passport_and_report_line(tmp_path, monkeypatch):
    from req_review.pipeline import Options, run

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MIN_INTERVAL", "0")
    out = tmp_path / "report.md"
    run(str(ROOT / "tests" / "fixtures" / "sample_requirements.md"), str(out),
        Options(cascade="mock-fast,mock-strong", html=False, xlsx=False, jira=False, pdf=False), log=lambda m: None)
    cc = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["passport"]["cascade"]
    assert 0 < cc["strong_reqs"] <= cc["checked_reqs"] and cc["calls"]["fast"] > 0 and cc["calls"]["strong"] > 0
    assert "| Каскад моделей |" in out.read_text(encoding="utf-8")
    assert "каскад:" in (tmp_path / "report.log").read_text(encoding="utf-8")


def test_cascade_needs_two_models():
    import pytest

    from req_review.cascade import build_cascade

    with pytest.raises(ValueError, match="две модели"):
        build_cascade("одна")
