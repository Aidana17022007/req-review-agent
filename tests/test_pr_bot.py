"""v10: бот-ревьюер требований в Pull Request — комментарий «было → стало» и шлюз качества."""
import json
from pathlib import Path

import yaml

from req_review.cli import main as cli

ROOT = Path(__file__).parent.parent
FIX = ROOT / "tests" / "fixtures" / "sample_requirements.md"


def _load_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("pr_comment", ROOT / "scripts" / "pr_comment.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(tmp_path, name, text, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "rules")
    src = tmp_path / f"{name}.md"
    src.write_text(text, encoding="utf-8")
    out = tmp_path / name / "report.md"
    assert cli([str(src), str(out), "--env", str(tmp_path / "x.env"), "--quiet", "--no-xlsx", "--no-jira", "--no-html"]) == 0
    return out.with_suffix(".json")


def test_pr_comment_new_fixed_verdict_and_gate(tmp_path, monkeypatch):
    base = FIX.read_text(encoding="utf-8")
    # в PR: FR-02 исправили (убрали «быстро»), добавили требование с заглушкой TBD — новый критичный дефект
    pr = base.replace("Система должна быстро проверять наличие получателя", "Система должна за 2 секунды проверять наличие получателя")
    pr = pr.replace("- **FR-03.**", "- **FR-99.** Лимит переводов для новых клиентов: TBD.\n- **FR-03.**", 1)
    old_j, new_j = _run(tmp_path, "base", base, monkeypatch), _run(tmp_path, "pr", pr, monkeypatch)
    m = _load_script()
    old, new = json.loads(old_j.read_text(encoding="utf-8")), json.loads(new_j.read_text(encoding="utf-8"))
    added, fixed = m.diff(old, new)
    assert any(f["label"] == "FR-99" and f["severity"] == "critical" for f in added)
    assert any(f["label"] == "FR-02" for f in fixed)
    assert not any(f["label"] == "FR-02" for f in added)  # сдвиг строк не даёт ложных «новых»
    text, gate = m.build(new, old, "docs/requirements.md", "https://example.org/run/1", rules_only=True)
    assert text.startswith(m.MARKER) and gate
    assert "| Критичных дефектов |" in text and "Новые дефекты" in text and "Исправлены" in text
    assert "FR-99" in text and "строка" in text and "только детерминированные правила" in text and "⛔" in text
    assert len(text.splitlines()) <= m.MAX_LINES
    out = tmp_path / "c.md"
    rc = m.main(["--new", str(new_j), "--old", str(old_j), "--doc", "docs/requirements.md", "--out", str(out), "--gate"])
    assert rc == 1 and out.read_text(encoding="utf-8").startswith(m.MARKER)


def test_pr_comment_without_changes_passes_gate(tmp_path, monkeypatch):
    j = _run(tmp_path, "same", FIX.read_text(encoding="utf-8"), monkeypatch)
    m = _load_script()
    d = json.loads(j.read_text(encoding="utf-8"))
    text, gate = m.build(d, d, "docs/requirements.md")
    assert not gate and "Новых дефектов нет" in text and "Исправлены" not in text
    assert m.main(["--new", str(j), "--old", str(j), "--doc", "x.md", "--out", str(tmp_path / "c.md"), "--gate"]) == 0


def test_pr_comment_new_document(tmp_path, monkeypatch):
    j = _run(tmp_path, "fresh", FIX.read_text(encoding="utf-8"), monkeypatch)
    m = _load_script()
    text, gate = m.build(json.loads(j.read_text(encoding="utf-8")), None, "docs/new.md")
    assert "Документ новый" in text and len(text.splitlines()) <= m.MAX_LINES


def test_requirements_review_workflow_is_valid():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "requirements-review.yml").read_text(encoding="utf-8"))
    assert wf["permissions"] == {"contents": "read", "pull-requests": "write"}
    steps = " ".join(str(s.get("run", "")) for s in wf["jobs"]["review"]["steps"])
    assert "scripts/pr_comment.py" in steps and "reqlens-pr-review" in steps and "LLM_PROVIDER=rules" in steps
    assert "secrets.GEMINI_API_KEY" in (ROOT / ".github" / "workflows" / "requirements-review.yml").read_text(encoding="utf-8")
