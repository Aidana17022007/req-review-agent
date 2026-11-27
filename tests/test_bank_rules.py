"""v10: чек-лист банка в YAML — правила банка без кода (--rules / REQLENS_RULES)."""
import json
from pathlib import Path

import pytest

from req_review.bank_rules import RulesError, load_rules
from req_review.cli import main as cli
from req_review.llm import build_llm_from_env
from req_review.pipeline import Options, review_document
from req_review.verify import quote_in

ROOT = Path(__file__).parent.parent


def _review(path, monkeypatch, rules="fintech"):
    monkeypatch.setenv("LLM_PROVIDER", "rules")
    return review_document(str(path), build_llm_from_env(), Options(rules=rules, critic=False), log=lambda m: None)


def _hits(rv) -> set:
    """{(id правила, ID требования)} — все срабатывания правил банка в прогоне."""
    by = {rr.req.rid: rr.req for rr in rv.req_results}
    out = set()
    for rr in rv.req_results:
        for f in rr.findings:
            if "правило банка" in f.source:
                assert quote_in(f.quote, rr.req.text), (f.source, f.quote)  # цитата дословная
                out |= {(s.split(": ")[1], rr.req.doc_id) for s in f.source.split(" + ") if s.startswith("правило банка")}
    for f in rv.set_findings:
        if f.kind == "bank_rule":
            for r in f.refs:
                assert quote_in(r.quote, by[r.req_id].text), (f.source, r.quote)
            out.add((f.source.split(": ")[1], "DOC"))
    return out


def _write(tmp_path, text, name="r.rules.yaml"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


RULE = """rules:
  - id: T-1
    title: Сумма без валюты
    severity: major
    criterion: complete
    when: 'сумм\\w*'
    require: ['тенге']
    message: нет валюты
    fix: указать валюту
"""


def test_example_set_is_valid():
    rs = load_rules("fintech")
    assert 8 <= len(rs.rules) <= 12 and len({r.id for r in rs.rules}) == len(rs.rules)
    assert all(r.reason for r in rs.rules if not r.enabled)  # выключенные — с причиной


def test_rule_fires_with_verbatim_quote_and_skips_unrelated(tmp_path, monkeypatch):
    doc = _write(tmp_path, "# Т\n\n## Требования\n\n- **FR-01.** Система должна принимать перевод на сумму до 500 000.\n"
                 "- **FR-02.** Система должна принимать перевод на сумму до 500 000 тенге.\n"
                 "- **FR-03.** Система должна показывать историю операций за 30 дней.\n", "doc.md")
    rv = _review(doc, monkeypatch, str(_write(tmp_path, RULE)))
    fs = {rr.req.doc_id: [f for f in rr.findings if f.source == "правило банка: T-1"] for rr in rv.req_results}
    assert len(fs["FR-01"]) == 1 and quote_in(fs["FR-01"][0].quote, "Система должна принимать перевод на сумму до 500 000.")
    assert fs["FR-01"][0].criterion == "complete" and fs["FR-01"][0].severity == "major"
    assert not fs["FR-02"] and not fs["FR-03"]  # валюта есть / when не подходит
    row = rv.bank_rules["rules"][0]
    assert row["applicable"] == 2 and row["hits"] == 1 and row["status"] == "fired"


def test_when_section_and_forbid(tmp_path, monkeypatch):
    rules = _write(tmp_path, """rules:
  - id: NFR-1
    title: Размытое слово в НФТ
    severity: critical
    criterion: verifiable
    when: {section: 'нефункц'}
    forbid: ['удобн\\w*']
    message: оценочное слово
    fix: метрика
""")
    doc = _write(tmp_path, "# Т\n\n## Функциональные требования\n\n- **FR-01.** Система должна показывать удобный список.\n\n"
                 "## Нефункциональные требования\n\n- **NFR-01.** Интерфейс должен быть удобным.\n", "doc.md")
    rv = _review(doc, monkeypatch, str(rules))
    hit = {rr.req.doc_id for rr in rv.req_results for f in rr.findings if "NFR-1" in f.source}
    assert hit == {"NFR-01"}  # FR-01 — не в разделе НФТ, правило к нему не применяется


def test_zero_false_positives_on_benchmark_docs(monkeypatch):
    """Чистые документы бенчмарка: правила формулировок молчат. Единственное срабатывание — CR-13 (push без срока
    доставки): по стандарту банка это настоящий пропуск, бенчмарк такие пропуски не размечает. Документы с внедрёнными
    дефектами: каждое срабатывание приходится на дефект из bench/ground_truth.json. Новое срабатывание = тест падает
    (проверить вручную и либо поправить правило, либо добавить сюда с причиной)."""
    expected = {
        "bench/docs/cards.md": set(), "bench/docs/cashback.md": set(), "bench/docs/deposit_kk.md": set(),
        "bench/docs/onboarding.md": set(), "bench/docs/payments.md": set(), "bench/real/notifications.md": set(),
        "bench/docs/credit.md": {("BR-06", "CR-13")},
        # внедрены: CB-09 «без задержек» вместо 5 минут
        "bench/out/cashback_seeded.md": {("BR-06", "CB-09")},
        # CR-13 «и/или», CNF-01 субъективная оценка, CR-11 «длительный срок» вместо 5 лет — срока хранения ПДн нет
        "bench/out/credit_seeded.md": {("BR-06", "CR-13"), ("BR-08", "CNF-01"), ("BR-05", "DOC")},
        # ON-12 «и/или», ONF-03 субъективная оценка, ONF-02 без «удаляться через 90 дней»
        "bench/out/onboarding_seeded.md": {("BR-06", "ON-12"), ("BR-08", "ONF-03"), ("BR-05", "DOC")},
        "bench/out/payments_seeded.md": {("BR-08", "NFR-06")},  # субъективная оценка
        "bench/out/deposit_kk_seeded.md": set(),
        # учебный документ с дефектами: уведомление без канала и срока, перевод без идемпотентности и без отказов,
        # номер телефона и биометрия без срока хранения
        "tests/fixtures/sample_requirements.md": {("BR-06", "FR-07"), ("BR-03", "DOC"), ("BR-09", "DOC"),
                                                  ("BR-05", "DOC")},
    }
    gt = json.loads((ROOT / "bench" / "ground_truth.json").read_text(encoding="utf-8"))["documents"]
    for path, exp in expected.items():
        hits = _hits(_review(ROOT / path, monkeypatch))
        assert hits == exp, (path, hits)
        if "/out/" in path:
            seeded = {i for d in gt[Path(path).stem.replace("_seeded", "")]["defects"] for i in d["ids"]}
            assert all(rid in seeded for _, rid in hits if rid != "DOC"), (path, hits)


def test_organizers_doc_not_worse(monkeypatch):
    """Чек-лист только добавляет замечания: результат real_eval на документе организаторов не хуже прогона без него."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("real_eval", ROOT / "bench" / "real_eval.py")
    re_ = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(re_)
    doc = ROOT / "bench" / "real" / "notifications.md"
    base, with_rules = _review(doc, monkeypatch, rules=""), _review(doc, monkeypatch)

    def n(rv):
        return sum(len(rr.findings) for rr in rv.req_results) + len(rv.set_findings)

    assert n(with_rules) >= n(base)
    final = json.loads((ROOT / "reports" / "requirements-report.json").read_text(encoding="utf-8"))
    ev = re_.evaluate(final)
    assert ev["found"] >= 26  # отчёт для сдачи (модель) — 26/26; правила банка его не уменьшают


@pytest.mark.parametrize("bad,msg", [
    (RULE.replace("complete", "fast_enough"), "неизвестный критерий «fast_enough»"),
    (RULE.replace("'сумм\\w*'", "'сумм(\\w*'"), "битая регулярка"),
    (RULE.replace("major", "huge"), "severity «huge»"),
    (RULE.replace("    message: нет валюты\n", ""), "не заполнены поля: message"),
    (RULE.replace("    fix: указать валюту\n", "    fix: x\n    colour: red\n"), "неизвестные поля: colour"),
    (RULE + RULE.replace("rules:\n", ""), "повторяются id: T-1"),
    (RULE.replace("    require: ['тенге']\n", ""), "хотя бы одно из полей"),
    (RULE + "    enabled: false\n", "укажите причину"),
    ("rules: [\n  - id: x", "ошибка YAML"),
])
def test_validation_errors_are_readable(tmp_path, bad, msg):
    with pytest.raises(RulesError) as e:
        load_rules(str(_write(tmp_path, bad)))
    assert msg in str(e.value)


def test_cli_reports_bad_rules_without_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "rules")
    bad = _write(tmp_path, RULE.replace("complete", "fast_enough"))
    rc = cli([str(ROOT / "tests" / "fixtures" / "sample_requirements.md"), str(tmp_path / "o" / "r.md"),
              "--env", str(tmp_path / "x.env"), "--rules", str(bad), "--quiet"])
    out = capsys.readouterr()
    assert rc == 2 and "Ошибка в чек-листе банка" in out.out + out.err and "Traceback" not in out.out + out.err
    assert load_rules is not None
    with pytest.raises(RulesError):
        load_rules(str(tmp_path / "missing.rules.yaml"))


def test_report_section_and_json_field(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "rules")
    out = tmp_path / "o" / "r.md"
    assert cli([str(ROOT / "tests" / "fixtures" / "sample_requirements.md"), str(out), "--env", str(tmp_path / "x.env"),
                "--rules", "fintech", "--quiet", "--no-xlsx", "--no-jira", "--no-html"]) == 0
    md = out.read_text(encoding="utf-8")
    assert "### Чек-лист банка" in md and "BR-06" in md and "правило банка: BR-06" in md
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    br = data["bank_rules"]
    assert data["schema_version"] == "2.5" and br["total"] == 10 and br["fired"] == 4 and br["disabled"] == 1
    assert {r["status"] for r in br["rules"]} <= {"fired", "passed", "not_applicable", "disabled"}
    # без --rules поведение прежнее: поля нет, подраздела нет
    out2 = tmp_path / "p" / "r.md"
    assert cli([str(ROOT / "tests" / "fixtures" / "sample_requirements.md"), str(out2), "--env", str(tmp_path / "x.env"),
                "--quiet", "--no-xlsx", "--no-jira", "--no-html"]) == 0
    assert "bank_rules" not in json.loads(out2.with_suffix(".json").read_text(encoding="utf-8"))
    assert "Чек-лист банка" not in out2.read_text(encoding="utf-8")


def test_env_variable_enables_rules(tmp_path, monkeypatch):
    monkeypatch.setenv("REQLENS_RULES", "fintech")
    rv = _review(ROOT / "tests" / "fixtures" / "sample_requirements.md", monkeypatch, rules="")
    assert rv.bank_rules and rv.bank_rules["fired"] == 4
