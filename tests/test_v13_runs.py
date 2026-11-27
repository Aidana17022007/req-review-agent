"""v13: --runs N (стабильность), ансамбль разных провайдеров, реакция на исправления, независимая проверка, --strong."""
import copy
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))
REAL = ROOT / "bench" / "real" / "notifications.md"


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MIN_INTERVAL", "0")


def test_runs_3_marks_stability_and_writes_runs_json(tmp_path, mock_env):
    from req_review.pipeline import Options, run

    out = tmp_path / "r.md"
    run(str(REAL), str(out), Options(runs=3, html=False, xlsx=False, jira=False, pdf=False), log=lambda m: None)
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    rn = data["passport"]["runs"]
    assert rn["n"] == 3 and rn["temperatures"] == [0.0, 0.4, 0.8] and len(rn["findings_per_run"]) == 3
    fs = [f for r in data["requirements"] for f in r["findings"]] + data["set_findings"]
    assert fs and all(f["stability"] == "3 из 3" for f in fs)  # mock детерминирован — всё устойчиво
    runs = json.loads((tmp_path / "r_runs.json").read_text(encoding="utf-8"))
    from stability import evaluate_runs, md

    s = evaluate_runs(runs)
    assert s["n"] == 3 and s["recall_min"] == s["recall_max"] and "Стабильность" in md(s, "x")
    assert "Стабильность (3 прогона" in out.read_text(encoding="utf-8")


def test_default_run_has_no_runs_field(tmp_path, mock_env):
    from req_review.pipeline import Options, run

    out = tmp_path / "r.md"
    run(str(REAL), str(out), Options(html=False, xlsx=False, jira=False, pdf=False), log=lambda m: None)
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert "runs" not in data["passport"] and not (tmp_path / "r_runs.json").exists()
    assert all(f["stability"] == "" for r in data["requirements"] for f in r["findings"])


def test_mark_counts_unstable(mock_env):
    from req_review.llm import build_llm_from_env
    from req_review.pipeline import Options, review_document
    from req_review.stability import mark

    rv = review_document(REAL, build_llm_from_env(), Options(), log=lambda m: None)
    other = copy.deepcopy(rv)
    for rr in other.req_results:  # во втором прогоне модель «не нашла» замечания к требованиям
        rr.findings = []
    info = mark(rv, [other])
    n_req = sum(len(rr.findings) for rr in rv.req_results)
    assert info["n"] == 2 and info["unstable"] == n_req and info["stable"] == len(rv.set_findings)
    assert all(f.stability == "1 из 2" for rr in rv.req_results for f in rr.findings)


def test_model_env_switches_provider_for_cross_provider_ensemble(monkeypatch):
    from req_review.ensemble import model_env

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "g-main")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with model_env("openai:deepseek-chat"):
        assert os.environ["LLM_PROVIDER"] == "openai" and os.environ["OPENAI_MODEL"] == "deepseek-chat"
    assert os.environ["LLM_PROVIDER"] == "gemini" and "OPENAI_MODEL" not in os.environ
    with model_env("g-other"):  # без провайдера — как раньше: модель текущего провайдера
        assert os.environ["GEMINI_MODEL"] == "g-other" and os.environ["LLM_PROVIDER"] == "gemini"
    assert os.environ["GEMINI_MODEL"] == "g-main"


def test_transitions_pairs_and_compare(mock_env):
    import transitions

    from req_review.llm import build_llm_from_env

    man = transitions.build()
    assert sum(len(m["fixed"]) for m in man["docs"].values()) >= 20
    fx = man["docs"]["fx"]
    after = (ROOT / fx["after"]).read_text(encoding="utf-8")
    assert "сразу после списания тенге" in after and "в кратчайшие сроки" not in after  # дефект FX-06 исправлен
    assert "круглосуточно" in after  # неисправленный дефект набора остался
    res = transitions.run({"docs": {"fx": fx}}, build_llm_from_env())
    t = res["total"]
    assert t["fixed"] == 3 and t["gone_of_found"] == t["was_found"] and t["new_false"] == 0
    assert "Реакция на исправления" in transitions.md(res)


def test_verify_findings_blind_and_human_table(tmp_path, mock_env, monkeypatch):
    import verify_findings as vf

    from req_review.llm import build_llm_from_env

    rep = json.loads((ROOT / "reports" / "requirements-report.json").read_text(encoding="utf-8"))
    items = vf.items_of(rep)
    assert items and all("severity" in i and i["severity"] != "minor" for i in items)
    seen = []
    llm = build_llm_from_env()
    orig = llm.generate_json

    def spy(system, prompt, **kw):
        seen.append(prompt)
        return orig(system, prompt, **kw)

    monkeypatch.setattr(llm, "generate_json", spy)
    vf.verify(items, llm)
    assert all('"severity"' not in p and "LLM" not in p for p in seen)  # проверяющий не видит вывод агента
    assert {i["model_verdict"] for i in items} <= {"да", "нет", "спорно"}
    path = tmp_path / "h.md"
    vf.write_human(items, path)
    k = items[0]["key"]
    t = path.read_text(encoding="utf-8").splitlines()
    t = [ln.rstrip(" |") + " | нет: надумано |" if ln.startswith(f"| {k} ") else ln for ln in t]
    path.write_text("\n".join(t), encoding="utf-8")
    vf.write_human(items, path)  # пересборка сохраняет ручной вердикт
    human = vf.load_human(path)
    assert human[k] == "нет"
    s = vf.summary(items, human)
    assert s["human_checked"] == 1 and s["human_confirmed_share"] == 0 and s["model_checked"] == len(items)


def test_strong_requires_strong_model(tmp_path, monkeypatch, capsys):
    from req_review.cli import main

    monkeypatch.delenv("STRONG_MODEL", raising=False)
    rc = main([str(REAL), str(tmp_path / "r.md"), "--env", str(tmp_path / "x.env"), "--strong", "--quiet"])
    assert rc == 2 and "STRONG_MODEL" in capsys.readouterr().err


def test_strong_passport_line(tmp_path, mock_env):
    from req_review.pipeline import Options, run

    out = tmp_path / "r.md"
    run(str(REAL), str(out), Options(strong="openrouter:some-model", html=False, xlsx=False, jira=False, pdf=False),
        log=lambda m: None)
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["passport"]["strong"]["model"] == "openrouter:some-model"
    assert "| Сильная модель |" in out.read_text(encoding="utf-8")
