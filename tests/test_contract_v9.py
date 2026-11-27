"""Контракт v9 (SCHEMA 2.4): фикстура tests/fixtures/report_v9.json — по ней человек 2 делает интерфейс.

Проверяется форма полей answers / decisions / questions[].qid и связность ссылок: каждый закрытый ответом ID есть в
вопросе, цитата ответа — дословная подстрока ответа, закрытое замечание лежит в rejected с closed_by, решения
ссылаются на существующие требования и строки документа."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = json.loads((ROOT / "tests" / "fixtures" / "report_v9.json").read_text(encoding="utf-8"))
REQS = {r["rid"]: r for r in D["requirements"]}
TYPES = {"concrete", "evasive", "contradictory"}


def test_schema_version_and_question_ids():
    assert D["schema_version"] == "2.4"
    qids = [q["qid"] for q in D["questions"]]
    assert qids == [f"Q-{i:02d}" for i in range(1, len(qids) + 1)]
    for q in D["questions"]:
        assert isinstance(q["closes"], list)
        assert all(re.fullmatch(r"(R-\d{3}\.\d+|S-\d{2})", c) for c in q["closes"]), q


def test_answers_shape_and_rules():
    a = D["answers"]
    assert set(a) == {"source", "items", "before", "after"} and "/" not in a["source"]
    qs = {q["qid"]: q for q in D["questions"]}
    closed = {r["closed_by"] for r in D["rejected"] if r.get("closed_by")}
    for it in a["items"]:
        assert set(it) == {"qid", "question", "answer", "type", "closes", "quote", "note"}
        assert it["type"] in TYPES and it["qid"] in qs and it["question"] == qs[it["qid"]]["text"]
        assert it["quote"] and it["quote"] in it["answer"]  # ничего не закрывается без дословной цитаты ответа
        if it["type"] == "concrete":
            assert it["closes"] and set(it["closes"]) <= set(qs[it["qid"]]["closes"]) and it["qid"] in closed
        else:
            assert it["closes"] == [] and it["qid"] not in closed
    assert {t for t in (i["type"] for i in a["items"])} == TYPES  # в фикстуре есть все три типа
    for side in ("before", "after"):
        assert set(a[side]) == {"critical", "major", "readiness", "verdict"}
        assert set(a[side]["verdict"]) == {"development", "testing"}
    # противоречивый ответ → новое замечание набора с цитатой ответа
    contra = [i["qid"] for i in a["items"] if i["type"] == "contradictory"]
    for qid in contra:
        f = next(f for f in D["set_findings"] if f.get("source") == f"ответ {qid}")
        ans = next(i["answer"] for i in a["items"] if i["qid"] == qid)
        assert any(v["rid"] == qid and v["quote"] in ans for v in f["values"])


def test_closed_findings_are_in_rejected():
    for r in D["rejected"]:
        if r.get("closed_by"):
            assert r["reason"] == f"закрыто ответом {r['closed_by']}" and r["where"] in REQS


def test_decisions_shape_and_links():
    lines = (ROOT / "tests" / "fixtures" / "sample_requirements.md").read_text(encoding="utf-8").splitlines()
    assert 0 < len(D["decisions"]) <= 8
    for i, dec in enumerate(D["decisions"], 1):
        assert set(dec) == {"id", "title", "where", "impact", "options", "source_ids", "wording"}
        assert dec["id"] == f"D-{i:02d}" and dec["wording"] in ("код", "модель")
        assert 2 <= len(dec["options"]) <= 3 and dec["source_ids"] and dec["impact"]
        for w in dec["where"]:
            r = REQS[w["rid"]]
            assert w["doc_id"] == r["doc_id"] and w["line"] == r["line_start"]
            assert r["doc_id"] in lines[w["line"] - 1]  # строка исходного документа


def test_passport_log_and_docs_describe_contract():
    assert D["passport"]["log"].endswith(".log")
    schema = (ROOT / "docs" / "SCHEMA.md").read_text(encoding="utf-8")
    api = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    for field in ("answers.items[].type", "decisions[].where[]", "questions[].qid", "rejected[].closed_by", "passport.log"):
        assert field in schema, field
    for ep in ("POST /api/v1/runs/{rid}/answers", "GET /api/v1/example", "DEMO_UPLOADS_PER_IP", "`limit`"):
        assert ep in api, ep
