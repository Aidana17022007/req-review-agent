"""v13+ A10: verify, doctor, журнал runs/ и повтор, --fail-on, итог в 5 строк, откат на правила (код 3)."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REAL = ROOT / "bench" / "real" / "notifications.md"
FIX = ROOT / "tests" / "fixtures" / "sample_requirements.md"


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MIN_INTERVAL", "0")


def _run(tmp_path, *extra, src=REAL, name="r.md"):
    from req_review.cli import main

    out = tmp_path / name
    rc = main([str(src), str(out), "--env", str(tmp_path / "x.env"), "--quiet", "--no-xlsx", "--no-jira", "--no-html", *extra])
    return rc, out


def test_verify_ok_on_fresh_report_and_detects_tampering(tmp_path, mock_env, capsys):
    from req_review.cli import main

    rc, out = _run(tmp_path)
    assert rc == 0
    rep = out.with_suffix(".json")
    data = json.loads(rep.read_text(encoding="utf-8"))
    assert data["passport"]["verify"]["ok"] and data["passport"]["verify"]["sha_ok"]
    assert main(["verify", str(rep), str(REAL)]) == 0
    assert "✅ verify" in capsys.readouterr().out
    # подменённая цитата → код 4
    bad = json.loads(rep.read_text(encoding="utf-8"))
    r = next(r for r in bad["requirements"] if r["findings"])
    r["findings"][0]["quote"] = "этой фразы нет в документе"
    p1 = tmp_path / "bad_quote.json"
    p1.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    assert main(["verify", str(p1), str(REAL)]) == 4
    assert "цитата не найдена" in capsys.readouterr().out
    # другой файл на входе → SHA не совпадает → код 4
    other = tmp_path / "other.md"
    other.write_text(REAL.read_text(encoding="utf-8") + "\nдобавленная строка\n", encoding="utf-8")
    assert main(["verify", str(rep), str(other)]) == 4
    assert "SHA-256 входа не совпадает" in capsys.readouterr().out
    assert main(["verify", str(tmp_path / "нет.json"), str(REAL)]) == 2


def test_doctor_does_not_print_key(tmp_path, monkeypatch, capsys):
    from req_review.cli import main

    secret = "AIzaSy-SECRET-should-not-appear-123456"
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    assert main(["doctor", "--env", str(tmp_path / "x.env")]) == 0
    out = capsys.readouterr().out
    assert "ключ: задан" in out and secret not in out and secret[:10] not in out
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert main(["doctor", "--env", str(tmp_path / "x.env")]) == 2


def test_doctor_live_on_mock(tmp_path, mock_env, capsys):
    from req_review.cli import main

    assert main(["doctor", "--live", "--env", str(tmp_path / "x.env")]) == 0
    assert "модель ответила" in capsys.readouterr().out


def test_journal_written_and_replay_gives_same_findings(tmp_path, mock_env):
    rc, out = _run(tmp_path)
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    run_dir = Path(data["passport"]["journal"])
    assert run_dir.parent == tmp_path / "runs" and (run_dir / "run.json").exists()
    calls = (run_dir / "calls.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(calls) == data["passport"]["calls"] and calls
    rec = json.loads(next((run_dir / "calls").glob("*.json")).read_text(encoding="utf-8"))
    assert {"system", "prompt", "response", "task"} <= set(rec)
    rc2, out2 = _run(tmp_path, "--replay", str(run_dir), "--no-journal", name="r2.md")
    d2 = json.loads(out2.with_suffix(".json").read_text(encoding="utf-8"))
    assert rc2 == 0 and d2["passport"]["calls"] == 0 and "повтор" in d2["passport"]["mode"]
    strip = lambda d: [(r["rid"], [(f["criterion"], f["quote"]) for f in r["findings"]]) for r in d["requirements"]]  # noqa: E731
    assert strip(d2) == strip(data) and [f["problem"] for f in d2["set_findings"]] == [f["problem"] for f in data["set_findings"]]


def test_replay_missing_call_is_error(tmp_path):
    from req_review.journal import ReplayLLM
    from req_review.llm import LLMError

    (tmp_path / "calls").mkdir()
    r = ReplayLLM(tmp_path)
    with pytest.raises(LLMError, match="нет в журнале"):
        r.generate_json("s", "p", task="check")


def test_fail_on_blocker_and_partial(tmp_path, mock_env):
    assert _run(tmp_path, "--fail-on", "blocker", src=FIX)[0] == 1  # в тестовом ТЗ есть критичные
    assert _run(tmp_path, "--fail-on", "partial", src=FIX, name="p.md")[0] == 1
    assert _run(tmp_path, src=FIX, name="n.md")[0] == 0


def test_five_line_summary(tmp_path, mock_env, capsys):
    from req_review.cli import main

    main([str(FIX), str(tmp_path / "r.md"), "--env", str(tmp_path / "x.env"), "--no-xlsx", "--no-jira", "--no-html"])
    out = capsys.readouterr().out
    i = out.index("── Итог ──")
    lines = out[i:].splitlines()[1:6]
    assert [ln[:2] for ln in lines] == ["1.", "2.", "3.", "4.", "5."] and "Вердикт" in lines[0] and "Файлы" in lines[4]


def test_model_unavailable_falls_back_to_rules_with_code_3(tmp_path, monkeypatch):
    import req_review.mock_llm as mm
    from req_review.llm import LLMError

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MIN_INTERVAL", "0")

    def boom(self, *a, **k):
        raise LLMError("модель недоступна (тест)")

    monkeypatch.setattr(mm.MockLLM, "generate_json", boom)
    import req_review.pipeline as pl

    orig = pl.review_document

    def strict(path, llm, *a, **k):  # модель падает «по-настоящему» — без внутренней обработки ошибки
        if getattr(llm, "provider", "") == "mock":
            raise LLMError("модель недоступна (тест)")
        return orig(path, llm, *a, **k)

    monkeypatch.setattr(pl, "review_document", strict)
    rc, out = _run(tmp_path, src=FIX)
    assert rc == 3 and out.exists()
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert "правила" in data["passport"]["mode"]
    monkeypatch.setenv("REQLENS_FALLBACK_RULES", "0")
    assert _run(tmp_path, src=FIX, name="r2.md")[0] == 4
