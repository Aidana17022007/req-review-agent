"""v12: исправленная редакция ТЗ после ответов (`<отчёт>_revised.md`), варианты а/б, «Кратко» (mock, без сети)."""
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from req_review import revised as rev
from req_review.answers import parse_answers, template_md

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "tests" / "fixtures" / "sample_requirements.md"


@pytest.fixture(scope="module")
def run_letter(tmp_path_factory):
    from req_review.pipeline import Options, run

    saved = {k: os.environ.get(k) for k in ("LLM_PROVIDER", "LLM_MIN_INTERVAL")}
    os.environ.update(LLM_PROVIDER="mock", LLM_MIN_INTERVAL="0")
    d = tmp_path_factory.mktemp("revised")
    opts = dict(html=False, xlsx=False, jira=False, pdf=False)
    ctx0 = run(str(DOC), str(d / "r0" / "report.md"), Options(**opts), log=lambda m: None)
    tpl = (d / "r0" / "report_answers_template.md").read_text(encoding="utf-8")
    s01 = next(q.qid for q in ctx0.questions if q.rid == "S-01")  # противоречие лимитов 500 000 / 300 000
    answers = {"Q-01": "Проверка получателя — не дольше 2 секунд для 95 % запросов при нагрузке до 200 запросов в секунду.",
               "Q-03": "Уточним с командой безопасности после пилота.", s01: "б"}
    for qid, a in answers.items():
        tpl = re.sub(rf"(### {qid}\..*?\nОтвет: )", lambda m, a=a: m.group(1) + a, tpl, count=1, flags=re.S)
    (d / "answers.md").write_text(tpl, encoding="utf-8")
    run(str(DOC), str(d / "r1" / "report.md"), Options(**opts, answers=str(d / "answers.md")), log=lambda m: None)
    data = json.loads((d / "r1" / "report.json").read_text(encoding="utf-8"))
    yield d, data, s01, tpl
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_template_has_letter_options_for_contradiction(run_letter):
    _d, _data, s01, tpl = run_letter
    block = tpl.split(f"### {s01}.")[1].split("\n### ")[0]
    assert "*Варианты (можно ответить буквой):*" in block
    assert re.search(r"- а\) 500 000 тенге", block) and re.search(r"- б\) 300 000 тенге", block) and "- в) свой ответ" in block


def test_letter_answer_parsed_to_option_and_concrete(run_letter):
    _d, data, s01, tpl = run_letter
    p = parse_answers(tpl)
    assert p[s01]["option"] == "б" and p[s01]["answer"].startswith("300 000 тенге")
    item = next(i for i in data["answers"]["items"] if i["qid"] == s01)
    assert item["type"] == "concrete" and "300 000" in item["quote"]


def test_letter_with_comment_and_own_answer():
    tpl = ("### Q-01. R-001 — X\n\n*Варианты (можно ответить буквой):*\n- а) 3 попытки\n- б) 5 попыток\n- в) свой ответ\n\n"
           "Ответ: б, но только для новых клиентов\n\n### Q-02. R-002 — Y\n\n- а) да\n- б) нет\n- в) свой ответ\n\nОтвет: в\n")
    p = parse_answers(tpl)
    assert p["Q-01"]["answer"] == "5 попыток. но только для новых клиентов" and p["Q-01"]["option"] == "б"
    assert "Q-02" not in p  # «в) свой ответ» без самого ответа — вопрос остаётся без ответа


def test_revised_changed_grounded_and_open_placeholder(run_letter):
    d, data, s01, _tpl = run_letter
    r = data["answers"]["revised"]
    r002 = next(c for c in r["changed"] if c["rid"] == "R-002")
    assert "не дольше 2 секунд" in r002["after"] and r002["source"] == "ответ" and r002["qids"] == ["Q-01"]
    assert r002["fixes"] == ["R-002.1"] and r002["before"] in (DOC.read_text(encoding="utf-8"))
    for c in r["changed"]:  # mock-«модель» вписывает 999 во второй элемент — код отклоняет
        assert "999" not in c["after"] and rev.grounded(c["after"], c["before"], " ".join(c["quotes"]))
    ev = next(o for o in r["open"] if o["qid"] == "Q-03")
    assert ev["placeholder"].startswith("[уточнить: Q-03") and ev["placeholder"] in ev["text"]
    md = (d / "r1" / "report_revised.md").read_text(encoding="utf-8")
    for h in ("## Изменённые требования", "## Новые требования", "## Новые критерии приёмки", "## Осталось уточнить"):
        assert h in md
    assert "**Было:**" in md and "**Стало:**" in md and "*Устраняет:* R-002.1 · *по ответу* Q-01: «" in md
    assert all(a["gherkin"].startswith("Дано") for a in r["acceptance"]) and r["acceptance"]
    assert all(x["source"] == "предложение агента" for x in r["suggestions"])


def test_summary_and_brief_before_section_1(run_letter):
    d, data, _s01, _tpl = run_letter
    s = data["answers"]["summary"]
    assert {"blockers_total", "blockers_closed", "open_before", "open_after"} <= set(s)
    assert 0 < s["blockers_closed"] <= s["blockers_total"] and s["open_after"] < s["open_before"]
    md = (d / "r1" / "report.md").read_text(encoding="utf-8")
    assert md.index("## Кратко") < md.index("## 1. Паспорт прогона")
    assert f"Закрыто блокеров: {s['blockers_closed']} из {s['blockers_total']}." in md
    assert "→ закрыт ответом Q-01: «Проверка получателя" in md
    heads = re.findall(r"^## (\d)\. ", md, re.M)
    assert heads == ["1", "2", "3", "4", "5", "6"]


def test_new_requirement_gets_new_id():
    rr = NS(req=NS(rid="R-001", doc_id="Ф-1", text="Клиент включает кэшбэк."), findings=[], rewrite="", answered=[])
    rv = NS(req_results=[rr])
    q = NS(qid="Q-01", rid="S-01", refs=[], text="Каким методом клиент читает историю?", severity="critical")
    item = NS(qid="Q-01", type="concrete", closes=["S-01"], quote="Метод GET /cashback/history", question=q.text)
    closed = [{"id": "S-01", "qid": "Q-01", "criterion": "set_complete", "severity": "critical",
               "problem": "Нет метода чтения истории кэшбэка", "quote": item.quote}]
    p = rev.plan(rv, [q], {"items": [item]}, closed)
    out = rev.write(rv, p, llm=None, log=lambda m: None)
    assert [a["id"] for a in out["added"]] == ["NEW-01"] and out["added"][0]["from"] == "Q-01"
    assert "GET /cashback/history" in out["added"][0]["text"] and out["changed"] == []


def test_grounded_ignores_ids_but_catches_invented_numbers():
    assert rev.grounded("По R-002 и Q-01: не дольше 2 секунд", "не дольше 2 секунд")
    assert not rev.grounded("не дольше 3 секунд", "быстро", "в течение 2 секунд")


def test_agent_suggestions_skip_broken_phrases():
    ok = NS(req=NS(rid="R-1", doc_id="", text="Система должна списывать комиссию при необходимости."),
            rewrite="Система должна списывать комиссию.", findings=[1])
    bad = NS(req=NS(rid="R-2", doc_id="", text="Система должна обеспечивать защиту от мошенничества."),
             rewrite="Система должна от мошенничества.", findings=[1])
    got = rev.agent_suggestions(NS(req_results=[ok, bad]), set())
    assert [g["rid"] for g in got] == ["R-1"] and got[0]["source"] == "предложение агента"


def test_template_without_options_unchanged():
    q = NS(qid="Q-01", ref="R-001", section="S", rid="R-001", criterion="verifiable", refs=[], text="?", closes=["R-001.1"],
           severity="critical")
    assert "Варианты" not in template_md([q], "T")
