"""v10: оценка экономии времени — строки документа ÷ норма ручного ревью; подписана как оценка."""
import json
from pathlib import Path

from req_review.cli import main as cli
from req_review.pipeline import time_estimate

FIX = Path(__file__).parent / "fixtures" / "sample_requirements.md"


class _Doc:
    def __init__(self, n):
        self.lines = [type("L", (), {"text": "строка"})() for _ in range(n)] + [type("L", (), {"text": "  "})()]


def test_formula_and_env_norm(monkeypatch):
    monkeypatch.delenv("REVIEW_LINES_PER_HOUR", raising=False)
    te = time_estimate(_Doc(120), 90)
    assert te == {"doc_lines": 120, "lines_per_hour": 40, "norm_source": "по умолчанию", "manual_hours": 3.0,
                  "agent_minutes": 1.5, "estimate": True}  # пустые строки не считаются
    monkeypatch.setenv("REVIEW_LINES_PER_HOUR", "60")
    assert time_estimate(_Doc(120), 90)["manual_hours"] == 2.0
    monkeypatch.setenv("REVIEW_LINES_PER_HOUR", "сорок")
    assert time_estimate(_Doc(120), 1)["lines_per_hour"] == 40 and time_estimate(_Doc(120), 1)["agent_minutes"] == 0.1


def test_report_shows_estimate_and_method(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "rules")
    monkeypatch.delenv("REVIEW_LINES_PER_HOUR", raising=False)
    out = tmp_path / "o" / "r.md"
    assert cli([str(FIX), str(out), "--env", str(tmp_path / "x.env"), "--quiet", "--no-xlsx", "--no-jira", "--no-html"]) == 0
    md = out.read_text(encoding="utf-8")
    assert md.count("| Экономия времени (оценка) | ручное ревью ≈") == 2  # паспорт и «Сводка»
    assert "**Экономия времени (оценка, не замер):**" in md and "REVIEW_LINES_PER_HOUR" in md
    te = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["passport"]["time_estimate"]
    assert te["estimate"] is True and te["lines_per_hour"] == 40 and te["manual_hours"] > 0
