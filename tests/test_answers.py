"""v9: ответы аналитика → перепроверка (mock, без сети).

Конкретный ответ закрывает связанные замечания (они уходят в rejected с причиной «закрыто ответом Q-xx»), уклончивый и
противоречивый — нет; противоречивый добавляет замечание набора с дословной цитатой ответа; цитаты — подстроки ответов."""
import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "tests" / "fixtures" / "sample_requirements.md"
ANSWERS = {
    "Q-01": "Проверка получателя — не дольше 2 секунд для 95 % запросов при нагрузке до 200 запросов в секунду.",
    "Q-02": "Способы подтверждения: только одноразовый код из SMS или push-уведомление. Биометрия не используется.",
    "Q-03": "Уточним с командой безопасности после пилота.",
}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    from req_review.pipeline import Options, run

    saved = {k: os.environ.get(k) for k in ("LLM_PROVIDER", "LLM_MIN_INTERVAL")}
    os.environ.update(LLM_PROVIDER="mock", LLM_MIN_INTERVAL="0")
    d = tmp_path_factory.mktemp("answers")
    opts = dict(html=False, xlsx=False, jira=False, pdf=False)
    ctx0 = run(str(DOC), str(d / "r0" / "report.md"), Options(**opts), log=lambda m: None)
    tpl = (d / "r0" / "report_answers_template.md").read_text(encoding="utf-8")
    s01 = next(q.qid for q in ctx0.questions if q.rid == "S-01")  # противоречие лимитов 500 000 / 300 000
    answers = {**ANSWERS, s01: "Максимальная сумма одной операции — 700 000 тенге."}
    for qid, a in answers.items():
        tpl = re.sub(rf"(### {qid}\..*?\nОтвет: )", lambda m, a=a: m.group(1) + a, tpl, count=1, flags=re.S)
    (d / "answers.md").write_text(tpl, encoding="utf-8")
    ctx1 = run(str(DOC), str(d / "r1" / "report.md"), Options(**opts, answers=str(d / "answers.md")), log=lambda m: None)
    data = json.loads((d / "r1" / "report.json").read_text(encoding="utf-8"))
    md = (d / "r1" / "report.md").read_text(encoding="utf-8")
    yield ctx0, ctx1, data, md, s01, answers, d
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_template_lists_every_question_with_id_and_closes(runs):
    ctx0, *_rest, d = runs
    tpl = (d / "r0" / "report_answers_template.md").read_text(encoding="utf-8")
    assert len(re.findall(r"^### Q-\d{2}\.", tpl, re.M)) == len(ctx0.questions) > 0
    assert "*Закроет замечания:* R-002.1" in tpl and "<!-- reqlens: R-002 verifiable -->" in tpl


def test_concrete_closes_evasive_and_contradictory_do_not(runs):
    ctx0, ctx1, data, md, s01, answers, _ = runs
    items = {i["qid"]: i for i in data["answers"]["items"]}
    assert items["Q-01"]["type"] == "concrete" and items["Q-01"]["closes"] == ["R-002.1"]
    assert items["Q-02"]["type"] == "concrete" and items["Q-02"]["closes"] == ["R-006.1"]
    assert items["Q-03"]["type"] == "evasive" and items["Q-03"]["closes"] == []
    assert items[s01]["type"] == "contradictory" and items[s01]["closes"] == []
    for qid, it in items.items():  # ничего не закрывается без дословной цитаты ответа
        assert it["quote"] and it["quote"] in answers[qid] and it["answer"] == answers[qid]
    closed = {r["closed_by"]: r for r in data["rejected"] if r.get("closed_by")}
    assert set(closed) == {"Q-01", "Q-02"} and closed["Q-01"]["reason"] == "закрыто ответом Q-01"
    r002 = next(r for r in data["requirements"] if r["rid"] == "R-002")
    assert r002["findings"] == []  # закрытое замечание ушло из активных
    r006 = next(r for r in data["requirements"] if r["rid"] == "R-006")
    assert [f["criterion"] for f in r006["findings"]] == ["verifiable"]  # уклончивый ответ оставил второе открытым
    assert "Ответ Q-03 уклончивый" in r006["findings"][0]["critic_note"]
    assert items["Q-03"]["note"].startswith("Остаётся открытым")  # mock-«модель» назвала его конкретным — правила поправили


def test_contradictory_answer_adds_finding_with_quote(runs):
    _ctx0, _ctx1, data, _md, s01, answers, _d = runs
    f = next(f for f in data["set_findings"] if f["source"] == f"ответ {s01}")
    assert f["criterion"] == "set_consistent" and f["severity"] == "critical"
    assert any(v["rid"] == s01 and v["quote"] in answers[s01] for v in f["values"])
    s01_still = [x for x in data["set_findings"] if x["source"] != f"ответ {s01}" and "500" in x["problem"]]
    assert s01_still  # исходное противоречие осталось открытым


def test_before_after_report_section_and_fixed_document(runs):
    ctx0, ctx1, data, md, *_rest, d = runs
    b, a = data["answers"]["before"], data["answers"]["after"]
    assert b["critical"] == sum(f.severity == "critical" for rr in ctx0.rv.req_results for f in rr.findings) + \
        sum(f.severity == "critical" for f in ctx0.rv.set_findings)
    assert a["critical"] == b["critical"] - 2 + 1  # закрыто 2 критичных, добавлено «ответ противоречив»
    assert "### Ответы аналитика" in md and "| Q-01 | конкретный |" in md and "**Было → стало**" in md
    assert md.index("## 6. Итог") < md.index("### Ответы аналитика")  # 6 разделов ТЗ на месте
    fixed = (d / "r1" / "report_requirements_fixed.md").read_text(encoding="utf-8")
    # v12: значение из ответа вписано в формулировку требования (не дописка «Уточнено ответом»), источник — в сноске
    assert "первую букву фамилии. Проверка получателя — не дольше 2 секунд" in fixed and "ответ аналитика Q-01" in fixed
    assert (d / "r1" / "report_revised.md").exists()
    assert data["schema_version"] == "2.5" and data["passport"]["answers"]["closed"] == 2


def test_default_run_has_no_answers_field(runs):
    ctx0, *_rest, d = runs
    data0 = json.loads((d / "r0" / "report.json").read_text(encoding="utf-8"))
    assert "answers" not in data0 and all(q["qid"] for q in data0["questions"])


def test_rules_classifier_cases():
    from types import SimpleNamespace as NS

    from req_review.answers import classify_rules, parse_answers

    q = NS(rid="R-001", qid="Q-01", text="?")
    rv = NS(set_findings=[])
    assert classify_rules(q, "TBD, уточним позже", rv)[0] == "evasive"
    assert classify_rules(q, "Не более 3 попыток в сутки", rv)[0] == "concrete"
    assert classify_rules(q, "Обсудим на следующей неделе", rv)[0] == "evasive"
    assert parse_answers("### Q-01. x\n\nОтвет: \n\n### Q-02. y\nОтвет: 5 секунд\n") == {"Q-02": {"answer": "5 секунд", "key": None}}


def test_missing_or_empty_answers_file_is_a_clear_error(tmp_path):
    from req_review.pipeline import _apply_answers

    p = tmp_path / "a.md"
    p.write_text("# пусто\n\nОтвет: \n", encoding="utf-8")
    with pytest.raises(ValueError, match="нет ни одного ответа"):
        _apply_answers(None, None, str(p), print)
    with pytest.raises(FileNotFoundError):
        _apply_answers(None, None, str(tmp_path / "нет.md"), print)


def test_organizers_example_answers_classified_as_documented():
    """examples/answers/organizers_answers.md: 10 ответов (6 конкретных, 2 уклончивых, 2 противоречивых) — правила агента
    на вопросах отчёта для сдачи дают ровно те типы, что записаны в examples/answers/README.md."""
    from types import SimpleNamespace as NS

    from req_review.answers import classify_rules, parse_answers

    d = json.loads((ROOT / "reports" / "requirements-report.json").read_text(encoding="utf-8"))
    rv = NS(req_results=[NS(req=NS(rid=r["rid"], text=r["text"])) for r in d["requirements"]],
            set_findings=[NS(criterion=f["criterion"], values=f.get("values") or []) for f in d["set_findings"]])
    refs = {f"S-{i:02d}": sorted({r["req_id"] for r in f["refs"] if r["req_id"] != "DOC"}) for i, f in enumerate(d["set_findings"], 1)}
    qs = {f"Q-{i:02d}": NS(qid=f"Q-{i:02d}", rid=q["rid"], criterion=q["criterion"], text=q["text"], refs=refs.get(q["rid"], []))
          for i, q in enumerate(d["questions"], 1)}
    parsed = parse_answers((ROOT / "examples" / "answers" / "organizers_answers.md").read_text(encoding="utf-8"))
    readme = (ROOT / "examples" / "answers" / "README.md").read_text(encoding="utf-8")
    expected = {m[0]: m[1] for m in re.findall(r"^\| (Q-\d{2}) \|[^|]*\|[^|]*\| (\w+) \|", readme, re.M)}
    ru = {"concrete": "конкретный", "evasive": "уклончивый", "contradictory": "противоречивый"}
    assert len(parsed) == 10 and len(expected) == 10
    got = {qid: ru[classify_rules(qs[qid], v["answer"], rv)[0]] for qid, v in parsed.items()}
    assert got == expected
    assert sorted(got.values()).count("конкретный") == 6 and list(got.values()).count("противоречивый") == 2
    for v in parsed.values():  # метки шаблона: ID требования или критерий + затронутые требования
        assert v["key"] and (v["key"][0].startswith("R-") or v["key"][2])


def test_label_mismatch_is_unknown_not_another_question():
    """Метка шаблона не нашлась в новом прогоне → ответ «неизвестный», а не привязка к чужому вопросу с тем же Q-xx."""
    from types import SimpleNamespace as NS

    from req_review.answers import _resolve

    qs = [NS(qid="Q-01", rid="R-005", ref="R-005", criterion="complete", refs=[]),
          NS(qid="Q-02", rid="S-01", ref="S-01", criterion="set_consistent", refs=["R-003", "R-011"])]
    parsed = {"Q-01": {"answer": "a", "key": ("R-011", "correct", "")},       # такого вопроса нет
              "Q-07": {"answer": "b", "key": ("S-27", "set_consistent", "R-003,R-011")},  # S-27 → теперь S-01
              "Q-09": {"answer": "c", "key": ("S-30", "set_consistent", "R-003,R-011")},  # тот же вопрос второй раз
              "Q-02": {"answer": "d", "key": None}}  # без метки — по номеру
    pairs, unknown = _resolve(qs, parsed)
    assert [(q.qid, a) for q, a, _opt in pairs] == [("Q-02", "b")] and unknown == ["Q-01", "Q-09", "Q-02"]
