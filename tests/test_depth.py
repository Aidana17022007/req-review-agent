"""v5 «Глубина»: CRUD-полнота API, контракт интеграции, учёт строк, покрытие приёмкой, вердикты, провайдеры."""
import glob
import json
from pathlib import Path

import pytest

from req_review.depth import integration_contract, line_coverage, missing_read_method
from req_review.reader import read_document
from req_review.splitter import split_requirements
from req_review.verify import quote_in

ROOT = Path(__file__).parent.parent
CLEAN = [str(ROOT / "tests" / "fixtures" / "sample_requirements.md")] + sorted(glob.glob(str(ROOT / "bench" / "docs" / "*.md"))) + \
    sorted(glob.glob(str(ROOT / "bench" / "out" / "*.md")))

API_DOC = """# Уведомления

## Дизайн процесса UI
На экране видны переключатель, текущий порог и сумма за месяц.

## Функциональные требования
- **Ф-1.** Клиент задаёт порог от 1 000 до 1 000 000 ₸.

## Требования к интеграции
Приложение читает и сохраняет настройки через REST API. Повторная доставка события процессинга не меняет итог.

## Нефункциональные требования
Сервис передаёт push в течение минуты после получения события от процессинга.

## Часть B. REST API

### Общие параметры

| Поле | Значение |
| :--- | :--- |
| **Description** | Сохранение порога. Функциональные требования: чтение порога |
| **REST type** | POST |
| **Request URL** | `/alerts/saveLimit` |
"""


def _doc(tmp_path, text, name="d.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    d = read_document(p)
    return d, split_requirements(d)


def _quotes_ok(found, split, doc):
    by = {r.rid: r.text for r in split.requirements}
    return all(quote_in(x.quote, by.get(x.req_id, doc.text)) for f in found for x in f.refs)


def test_missing_read_method_and_contradictory_purpose(tmp_path):
    doc, s = _doc(tmp_path, API_DOC)
    found = missing_read_method(s.requirements, doc)
    kinds = sorted((f.kind, f.severity) for f in found)
    assert kinds == [("contradiction", "major"), ("gap", "critical")]
    gap = next(f for f in found if f.kind == "gap")
    assert "/alerts/saveLimit" in gap.problem and "чтени" in gap.problem
    assert _quotes_ok(found, s, doc)


def test_read_method_present_is_not_flagged(tmp_path):
    text = API_DOC.replace("| **Request URL** | `/alerts/saveLimit` |",
                           "| **Request URL** | `/alerts/saveLimit` и `/alerts/getLimit` |").replace(
        "Сохранение порога. Функциональные требования: чтение порога", "Сохранение порога")
    doc, s = _doc(tmp_path, text)
    assert missing_read_method(s.requirements, doc) == []


def test_integration_contract_gap_and_described_contract(tmp_path):
    doc, s = _doc(tmp_path, API_DOC)
    found = integration_contract(s.requirements, doc)
    assert len(found) == 1 and found[0].severity == "critical" and "контракт события" in found[0].problem
    assert _quotes_ok(found, s, doc)
    described = API_DOC + "\n## Контракт события\nСобытие процессинга содержит поля: cardId, operationId, type, amount, ts.\n"
    doc2, s2 = _doc(tmp_path, described, "d2.md")
    assert integration_contract(s2.requirements, doc2) == []


@pytest.mark.parametrize("path", CLEAN)
def test_new_rules_have_no_false_positives_on_bench_and_fixtures(path):
    doc = read_document(path)
    s = split_requirements(doc)
    assert missing_read_method(s.requirements, doc) == []
    assert integration_contract(s.requirements, doc) == []


@pytest.mark.parametrize("path", CLEAN)
def test_every_line_is_accounted(path):
    doc = read_document(path)
    lc = line_coverage(doc, split_requirements(doc).requirements)
    assert lc["total"] > 0 and lc["accounted"] + len(lc["uncovered"]) == lc["total"]
    assert lc["percent"] >= 95, lc["uncovered"]
    assert all(e["reason"] and e["lines"] > 0 for e in lc["excluded"])


def test_report_json_23_fields_and_markdown(tmp_path, monkeypatch):
    from req_review.cli import main

    monkeypatch.setenv("LLM_PROVIDER", "rules")
    src = tmp_path / "api.md"
    src.write_text(API_DOC + "\n## Критерии приемки\n\n| Исходные условия | Действие | Ожидаемый результат |\n| :--- | :--- | :--- |\n"
                   "| Порог 50 000 ₸ | Задать порог 1 000 ₸ | Порог 1 000 ₸ сохранён |\n", encoding="utf-8")
    out = tmp_path / "r.md"
    assert main([str(src), str(out), "--env", str(tmp_path / "x.env"), "--quiet", "--no-xlsx", "--no-jira"]) == 0
    d = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert d["schema_version"] == "2.3"
    assert d["line_coverage"]["percent"] == 100
    assert d["criteria_matrix"]["criteria"] and len(d["criteria_matrix"]["rows"]) == len(d["requirements"])
    assert d["acceptance_coverage"]["percent"] is not None
    st = d["review_stats"]
    assert st["proposed"] == st["confirmed"] + st["rejected"] + st["unconfirmed_quotes"]
    assert d["verdict"]["development"] == "нельзя" and d["verdict"]["testing"] in ("нельзя", "с оговорками")
    assert d["fix_plan"] and d["fix_plan"][0]["severity"] == "critical"
    md = out.read_text(encoding="utf-8")
    for marker in ("Учтено строк документа", "Самопроверка", "| Разработка | Тестирование |", "Приложение. Учёт строк документа"):
        assert marker in md, marker


def test_readiness_excludes_requirements_blocked_by_set_findings(tmp_path, monkeypatch):
    from req_review.cli import main

    monkeypatch.setenv("LLM_PROVIDER", "rules")
    out = tmp_path / "r.md"
    assert main([str(ROOT / "tests" / "fixtures" / "sample_requirements.md"), str(out), "--env", str(tmp_path / "x.env"),
                 "--quiet", "--no-xlsx", "--no-jira"]) == 0
    d = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    blocked = {r["req_id"] for f in d["set_findings"] if f["severity"] in ("critical", "major") for r in f["refs"]}
    ready_ok = {r["rid"] for r in d["requirements"] if r["rid"] not in blocked and
                not any(f["severity"] in ("critical", "major") for f in r["findings"])}
    assert d["scores"]["readiness"] <= round(100 * len(ready_ok) / len(d["requirements"]))


class _Resp:
    def __init__(self, status, data=None, text="", headers=None):
        self.status_code, self._data, self.text, self.headers = status, data, text, headers or {}

    def json(self):
        return self._data


def test_anthropic_provider_request_and_errors(monkeypatch):
    import req_review.llm as llm_mod
    from req_review.llm import AnthropicLLM, LLMFatalError

    sent = {}

    def ok(url, json=None, headers=None, timeout=None):
        sent.update(url=url, body=json, headers=headers)
        return _Resp(200, {"content": [{"type": "text", "text": '{"results": []}'}], "stop_reason": "end_turn",
                           "usage": {"input_tokens": 11, "output_tokens": 7}})

    monkeypatch.setenv("LLM_CACHE", "0")
    monkeypatch.setattr(llm_mod.requests, "post", ok)
    llm = AnthropicLLM(api_key="test-key", model="claude-opus-5-5", max_retries=0)
    assert llm.generate_json("система", "вопрос", task="check") == {"results": []}
    assert sent["url"].endswith("/v1/messages") and sent["headers"]["x-api-key"] == "test-key"
    assert sent["headers"]["anthropic-version"] and sent["body"]["model"] == "claude-opus-5-5"
    assert sent["body"]["messages"][0]["content"] == "вопрос" and "JSON" in sent["body"]["system"]
    assert llm.stats.prompt_tokens == 11 and llm.stats.output_tokens == 7 and llm.label == "anthropic / claude-opus-5-5"

    monkeypatch.setattr(llm_mod.requests, "post", lambda *a, **k: _Resp(401, text='{"error":"invalid x-api-key"}'))
    with pytest.raises(LLMFatalError):
        AnthropicLLM(api_key="bad", model="m", max_retries=0).generate_json("s", "p")


def test_provider_selection(monkeypatch):
    from req_review.llm import AnthropicLLM, OpenAICompatLLM, build_llm_from_env, default_provider

    for k in ("LLM_PROVIDER", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CLAUDE_API_KEY", "k")
    assert default_provider() == "anthropic" and isinstance(build_llm_from_env(), AnthropicLLM)
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    llm = build_llm_from_env()
    assert isinstance(llm, OpenAICompatLLM) and llm.provider == "openrouter" and "openrouter.ai" in llm.base_url
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    llm = build_llm_from_env()
    assert llm.provider == "ollama" and "11434" in llm.base_url
    from req_review.web.live import provider_status

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    st = provider_status()
    assert st["provider"] == "anthropic" and st["key_ok"] and st["key_name"] == "CLAUDE_API_KEY" and "k" not in st.values()


def test_completeness_pass_keeps_only_confirmed_quotes(tmp_path, monkeypatch):
    from req_review.cli import main

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    out = tmp_path / "r.md"
    assert main([str(ROOT / "tests" / "fixtures" / "sample_requirements.md"), str(out), "--env", str(tmp_path / "x.env"),
                 "--quiet", "--no-xlsx", "--no-jira"]) == 0
    d = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    gaps = [f for f in d["set_findings"] if f["source"] == "LLM (проход полноты)"]
    assert len(gaps) == 1 and gaps[0]["kind"] == "terminology" and gaps[0]["criterion"] == "set_comprehensible"
    assert any(x["quote"] == "этой фразы нет в документе" for x in d["dropped"])  # выдуманная цитата отброшена
    monkeypatch.setenv("REQLENS_GAPS", "0")
    assert main([str(ROOT / "tests" / "fixtures" / "sample_requirements.md"), str(out), "--env", str(tmp_path / "x.env"),
                 "--quiet", "--no-xlsx", "--no-jira"]) == 0
    d = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert not [f for f in d["set_findings"] if f["source"] == "LLM (проход полноты)"]
