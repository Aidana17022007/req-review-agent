"""Сравнение с «голой» моделью: ответ модели оценивается тем же кодом, что и ReqLens."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "bench"))


def _mod():
    spec = importlib.util.spec_from_file_location("baseline_eval", ROOT / "bench" / "baseline_eval.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class FakeLLM:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def generate_json(self, system, prompt, *, task="", context=None):
        self.calls.append((system, prompt))
        return self.answer


def test_prompt_is_bare_and_filled():
    m = _mod()
    llm = FakeLLM({"defects": [{"ids": ["PAY-01"], "criterion": "verifiable"}]})
    out = m.ask(llm, "ТЕКСТ ДОКУМЕНТА")
    system, prompt = llm.calls[0]
    assert "{criteria}" not in system and "verifiable:" in system and "set_consistent:" in system
    assert prompt.endswith("ТЕКСТ ДОКУМЕНТА") and out == [{"ids": ["PAY-01"], "criterion": "verifiable"}]
    assert m.ask(FakeLLM({"oops": 1}), "x") == [] and m.ask(FakeLLM([{"ids": ["A"]}, "мусор"]), "x") == [{"ids": ["A"]}]


def test_answer_scored_by_benchmark_code():
    m = _mod()
    from run import evaluate

    truth = {"defects": [
        {"type": "vague", "ids": ["PAY-01"], "criteria": ["verifiable"], "level": "requirement"},
        {"type": "tbd", "ids": ["PAY-02"], "criteria": ["complete"], "level": "requirement"},
        {"type": "contradiction", "ids": ["PAY-03", "PAY-04"], "criteria": ["set_consistent"], "level": "set"}],
        "clean_ids": ["PAY-09"]}
    defects = [
        {"ids": ["pay 01"], "criterion": "verifiable", "severity": "critical", "quote": "быстро"},  # ID нормализуется
        {"ids": ["PAY-02"], "criterion": "unambiguous", "severity": "major"},  # не тот критерий — не засчитан
        {"ids": ["PAY-04", "PAY-03"], "criterion": "set_consistent", "severity": "critical"},
        {"ids": ["PAY-09"], "criterion": "complete", "severity": "major"},  # к чистому — ложное
        {"ids": ["PAY-09"], "criterion": "conforming", "severity": "minor"},  # minor к чистому не штрафуется
        {"criterion": "set_complete", "severity": "weird"},
    ]
    rv = m.as_review(defects, {"PAY-01", "PAY-02", "PAY-03", "PAY-04", "PAY-09"})
    ev = evaluate(rv, truth, "payments")
    assert [r["found"] for r in ev["rows"]] == [True, False, True]
    assert ev["fp"] == 1 and ev["tp_findings"] == 1
    rep = m.as_report_json(rv)
    assert len(rep["requirements"]) == 5 and len(rep["set_findings"]) == 2


def test_quote_rate_counts_only_verbatim():
    m = _mod()
    text = "Система должна быстро проверять получателя."
    ok, n = m.quote_rate([{"quote": "быстро проверять"}, {"quote": "моментально находить"}, {"quote": ""}], text)
    assert (ok, n) == (1, 2)


def test_section_renders_and_replaces(tmp_path, monkeypatch):
    m = _mod()
    a = {"bench": {"recall": 0.5, "precision": 1.0, "f1": 0.67, "tp": 1, "total": 2, "fp_on_clean": 0, "clean": 1},
         "organizers": {"found": 20, "total": 26, "critical_found": 5, "critical_total": 7, "findings": 27}}
    res = {"docs": ["payments"], "A_rules": a, "C_reqlens": {**a, "bench": {**a["bench"], "model": "m", "version": "v"}},
           "B_bare": {"bench": {**a["bench"], "model": "g"}, "organizers": {**a["organizers"], "model": "g"},
                      "quotes_verbatim": [3, 4]}}
    text = m.section(res)
    assert text.startswith(m.SECTION) and "75 %" in text and "| F1 | 67 % | 67 % | 67 % |" in text
    monkeypatch.setattr(m, "HERE", tmp_path)
    (tmp_path / "RESULTS.md").write_text("# Итог\n\n" + m.SECTION + "\n\nстарое\n\n## Другое\n\nостаётся\n", encoding="utf-8")
    m.write_section(text)
    out = (tmp_path / "RESULTS.md").read_text(encoding="utf-8")
    assert out.count(m.SECTION) == 1 and "старое" not in out and "остаётся" in out


def test_saved_results_if_present():
    p = ROOT / "bench" / "baseline" / "results.json"
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        assert set(d) >= {"A_rules", "B_bare", "C_reqlens"} and d["C_reqlens"]["organizers"]["found"] >= 26
