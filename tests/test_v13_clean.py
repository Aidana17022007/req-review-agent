"""v13+ A8: чистые ТЗ — ноль ложных тревог (правила и mock), судья не удаляет, а понижает спорные противоречия."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))

MINI = """# Мини-ТЗ (выдуманное): Смена ПИН-кода карты

## 1. Назначение и рамки
Функция позволяет держателю сменить ПИН-код карты в приложении. Вне рамок: восстановление забытого ПИН-кода.

## 2. Термины
- **Держатель** — клиент банка с активной картой, вошедший в приложение.

## 3. Функциональные требования

| ID | Требование | Приоритет |
| :--- | :--- | :--- |
| PIN-01 | Новый ПИН-код — 4 цифры; ПИН из одинаковых цифр (1111) не принимается. | Высокий |
| PIN-02 | Смена подтверждается одноразовым кодом из SMS; после 3 неверных вводов смена отклоняется. | Высокий |
| PIN-03 | Новый ПИН-код действует не позднее 1 минуты после подтверждения. | Высокий |

## 4. Нефункциональные требования

| ID | Требование | Приоритет |
| :--- | :--- | :--- |
| PNF-01 | Журнал аудита записывает каждую смену ПИН-кода: держатель, время, результат; журнал хранится 5 лет; сам ПИН-код в журнал не записывается. | Высокий |
| PNF-02 | Данные передаются только по TLS версии 1.2 и выше. | Высокий |

## 5. Критерии приёмки

| Требование | Исходные условия | Действие | Ожидаемый результат |
| :--- | :--- | :--- | :--- |
| PIN-01 | Экран смены | Ввести 1111 | ПИН-код не принят |
| PIN-02 | Код отправлен | Ввести неверный код 3 раза | Смена отклонена |
| PIN-03 | Код верный | Подтвердить | Новый ПИН-код действует через 1 минуту или раньше |
"""


@pytest.mark.parametrize("provider", ["rules", "mock"])
def test_clean_mini_tz_has_no_critical_and_verdict_not_no(tmp_path, monkeypatch, provider):
    from req_review.llm import build_llm_from_env
    from req_review.pipeline import Options, review_document

    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv("LLM_MIN_INTERVAL", "0")
    p = tmp_path / "mini.md"
    p.write_text(MINI, encoding="utf-8")
    rv = review_document(p, build_llm_from_env(), Options(), log=lambda m: None)
    fs = [f for rr in rv.req_results for f in rr.findings] + list(rv.set_findings)
    assert not [f for f in fs if f.severity == "critical"], [f.problem for f in fs if f.severity == "critical"]
    assert rv.depth["verdict"]["development"] != "нельзя"
    if provider == "rules":
        assert not [f for f in fs if f.severity == "major"], [f.problem for f in fs if f.severity == "major"]


def test_acceptance_rows_with_rule_ids_are_references_not_duplicates(tmp_path):
    from req_review.reader import read_document
    from req_review.splitter import split_requirements

    p = tmp_path / "mini.md"
    p.write_text(MINI, encoding="utf-8")
    s = split_requirements(read_document(p))
    acc = [r for r in s.requirements if r.kind == "acceptance"]
    assert len(acc) == 3 and not s.duplicate_ids
    assert all(r.doc_id is None and r.extra.get("refs") for r in acc)
    assert acc[0].extra["refs"] == ["PIN-01"] and "Ввести 1111" in acc[0].text


def test_all_clean_documents_rules_zero_critical_and_major():
    import clean_eval

    from req_review.rules_llm import RulesOnlyLLM

    res = clean_eval.evaluate(clean_eval.docs(), RulesOnlyLLM(), "fast", log=lambda m: None)
    t = res["total"]
    assert t["docs"] >= 16 and t["critical"] == 0 and t["major"] == 0 and t["verdict_no"] == 0 and t["goal_met"]
    assert any(r["doc"] == "deposit_kk" for r in res["rows"])  # казахский документ — тоже чистый


def test_paraphrases_keep_numbers_ids_and_messages():
    sys.path.insert(0, str(ROOT / "bench" / "clean"))
    import re

    import paraphrase

    for q in paraphrase.build():
        src = (ROOT / "bench" / "clean" / q.name).read_text(encoding="utf-8")
        new = q.read_text(encoding="utf-8")
        assert src != new
        ids = lambda t: re.findall(r"\b[A-ZА-Я]{1,4}-\d{2}\b", t)  # noqa: E731
        nums = lambda t: re.findall(r"\d[\d  ,]*", t)  # noqa: E731
        msgs = lambda t: re.findall(r"«[^»]*»", t)  # noqa: E731
        assert ids(src) == ids(new) and sorted(nums(src)) == sorted(nums(new)) and msgs(src) == msgs(new), q.name


def test_judge_downgrades_llm_contradiction_instead_of_dropping(tmp_path):
    from req_review.checker import ReqResult, ReviewResult, SetFinding, SetRef
    from req_review.critic import run_critic
    from req_review.llm import BaseLLM
    from req_review.reader import read_document
    from req_review.splitter import split_requirements

    p = tmp_path / "mini.md"
    p.write_text(MINI, encoding="utf-8")
    doc = read_document(p)
    s = split_requirements(doc)
    rv = ReviewResult(doc=doc, split=s, req_results=[ReqResult(req=r) for r in s.requirements], dropped=[], set_findings=[
        SetFinding("contradiction", "set_consistent", [SetRef(s.requirements[0].rid, "4 цифры")], "Ложное противоречие.",
                   "critical", "", "LLM (перекрёстная проверка)"),
        SetFinding("gap", "set_complete", [SetRef(s.requirements[0].rid, "4 цифры")], "Надуманный пропуск.", "major", "", "LLM")])

    class Judge(BaseLLM):
        provider, model = "fake", "judge"

        def _call(self, system, prompt, *, task, context):
            import json
            return json.dumps({"verdicts": [{"n": it["n"], "verdict": "drop", "reason": "противоречия нет: условия разные"}
                                            for it in context["items"]]})

        def _cache_path(self, system, prompt):
            return None

    run_critic(rv, Judge(), log=lambda m: None, only_critical=True)
    con = [f for f in rv.set_findings if f.kind == "contradiction"]
    assert len(con) == 1 and con[0].severity == "minor" and con[0].critic_note.startswith("Судья сомневается")
    gap = [f for f in rv.set_findings if f.problem == "Надуманный пропуск."]
    assert len(gap) == 1 and gap[0].severity == "major"  # в fast судья смотрит только критичные и противоречия
