"""v13: комплаенс и безопасность (правила) и стоимость прогона — на выдуманных мини-ТЗ."""
import pytest

from req_review.checker import ReqResult, ReviewResult
from req_review.compliance import report_md, run, to_json
from req_review.cost import estimate, line
from req_review.reader import read_document
from req_review.splitter import split_requirements
from req_review.verify import quote_in


def _rv(tmp_path, text):
    p = tmp_path / "tz.md"
    p.write_text(text, encoding="utf-8")
    doc = read_document(p)
    sp = split_requirements(doc)
    return ReviewResult(doc=doc, split=sp, req_results=[ReqResult(req=r) for r in sp.requirements], set_findings=[], dropped=[])


BAD = """# Переводы по номеру телефона (выдуманный пример)

## Функциональные требования
- **П-1.** Система должна показывать получателю номер карты отправителя в push-уведомлении.
- **П-2.** Система должна записывать в журнал запросов код подтверждения и токен сессии.
- **П-3.** Система должна сохранять CVV карты для повторных переводов.
- **П-4.** Система должна запрашивать одноразовый код по желанию клиента.
- **П-5.** Система должна выполнять перевод на сумму до 500 000 тенге.
- **П-6.** Система должна запрашивать ИИН получателя из государственной базы.
"""

GOOD = """# Переводы по номеру телефона (выдуманный пример)

## Функциональные требования
- **П-1.** Система должна показывать получателю номер карты отправителя маскированным: первые 6 и последние 4 цифры.
- **П-2.** Система не записывает в журнал коды подтверждения и токены сессии.
- **П-4.** Система должна запрашивать одноразовый код для каждого перевода.
- **П-5.** Система должна выполнять перевод на сумму до 500 000 тенге.
- **П-6.** Система должна запрашивать ИИН получателя из государственной базы после согласия клиента.
- **П-7.** Система должна записывать в журнал аудита каждый перевод: клиент, сумма, время.
"""


def test_compliance_rules_fire_on_bad_tz(tmp_path):
    rv = _rv(tmp_path, BAD)
    rv.compliance = run(rv)
    c = {x["id"]: x for x in to_json(rv)["checks"]}
    for cid in ("pii_unmasked", "secrets_in_logs", "card_storage", "optional_auth", "no_audit", "no_consent"):
        assert c[cid]["status"] == "fired", cid
        assert c[cid]["finding"].startswith("S-") and c[cid]["new"]
    assert c["no_auth"]["status"] == "passed"  # подтверждение описано (П-4), хотя и необязательное
    assert c["card_storage"]["where"] == ["П-3"] and "PCI DSS" in c["card_storage"]["norm"]
    for f in rv.set_findings:
        assert f.source == "комплаенс (правило)" and "Норма:" in f.problem
        assert all(quote_in(r.quote, rv.doc.text) for r in f.refs)
    sev = {f.problem.split(" ")[0]: f.severity for f in rv.set_findings}
    assert "critical" in sev.values()
    md = "\n".join(report_md(rv))
    assert "### Комплаенс и безопасность" in md and "не юридическое заключение" in md


def test_compliance_silent_on_fixed_tz(tmp_path):
    rv = _rv(tmp_path, GOOD)
    rv.compliance = run(rv)
    c = to_json(rv)
    assert c["fired"] == 0 and rv.set_findings == []
    assert {x["status"] for x in c["checks"]} <= {"passed", "not_applicable"}


def test_compliance_links_existing_finding(tmp_path):
    from req_review.checker import SetFinding, SetRef

    rv = _rv(tmp_path, BAD)
    rv.set_findings.append(SetFinding("gap", "set_complete", [SetRef("DOC", "ИИН")], "Не описан журнал аудита операций.",
                                      "major", "", "LLM"))
    rv.compliance = run(rv)
    c = {x["id"]: x for x in to_json(rv)["checks"]}
    assert c["no_audit"]["finding"] == "S-01" and c["no_audit"]["new"] is False


PRICES = {"usd_kzt": 500, "models": {"gemini / gemini-": {"free_tier": True, "note": "бесплатно"},
                                     "openai / deepseek-chat": {"input_per_1m": 1.0, "output_per_1m": 2.0, "checked": "2026-11-27"},
                                     "openrouter /": {"input_per_1m": None, "output_per_1m": None}}}


def test_cost_estimate():
    free = estimate("gemini / gemini-3.8-flash", 100_000, 20_000, 12, PRICES)
    assert free["usd"] == 0 and free["free_tier"] and line(free).startswith("0 ₸")
    paid = estimate("openai / deepseek-chat", 1_000_000, 500_000, 10, PRICES)
    assert paid["usd"] == pytest.approx(2.0) and paid["kzt"] == 1000.0 and paid["per_call_usd"] == pytest.approx(0.2)
    assert "2026-11-27" in line(paid)
    none = estimate("openrouter / some-model", 1, 1, 1, PRICES)
    assert none["usd"] is None and "не указана" in line(none)  # цену не выдумываем
    assert "нет в config/prices.yaml" in estimate("claude / x", 1, 1, 1, PRICES)["note"]


def test_passport_has_cost_and_compliance(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    from req_review.pipeline import Options
    from req_review.pipeline import run as run_pipeline

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MIN_INTERVAL", "0")
    src = tmp_path / "bad.md"
    src.write_text(BAD, encoding="utf-8")
    out = tmp_path / "r.md"
    run_pipeline(str(src), str(out), Options(html=False, xlsx=False, jira=False, pdf=False), log=lambda m: None)
    data = json.loads(Path(out.with_suffix(".json")).read_text(encoding="utf-8"))
    assert data["passport"]["cost"]["free_tier"] and data["compliance"]["fired"] >= 5
    md = out.read_text(encoding="utf-8")
    assert "Стоимость прогона (оценка)" in md and md.index("### Комплаенс") < md.index("## 5.")
