"""v5 «Глубина»: CRUD-полнота API, контракт интеграции, учёт строк, покрытие приёмкой, вердикты, провайдеры."""
import glob
import json
from pathlib import Path

import pytest

from req_review.depth import (
    acceptance_preconditions,
    api_codes_and_body,
    completeness_rules,
    integration_contract,
    limit_vs_exception,
    line_coverage,
    message_texts,
    missing_default,
    missing_read_method,
    nfr_metric,
    refund_edges,
    session_lifecycle,
    state_after_error,
    template_unfilled,
    undefined_terms,
    unit_mix,
)
from req_review.reader import read_document
from req_review.splitter import split_requirements
from req_review.verify import quote_in

ROOT = Path(__file__).parent.parent
CLEAN = [str(ROOT / "tests" / "fixtures" / "sample_requirements.md")] + sorted(glob.glob(str(ROOT / "bench" / "docs" / "*.md"))) + \
    sorted(glob.glob(str(ROOT / "bench" / "out" / "*.md"))) + sorted(glob.glob(str(ROOT / "bench" / "out" / "*.docx")))

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
    assert completeness_rules(s.requirements, doc) == []


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


REAL = ROOT / "bench" / "real" / "notifications.md"


def test_completeness_rules_on_organizers_document():
    """Документ организаторов: каждое правило полноты срабатывает ровно один раз, цитаты дословные."""
    doc = read_document(REAL)
    s = split_requirements(doc)
    for fn in (nfr_metric, state_after_error, message_texts, acceptance_preconditions, template_unfilled, unit_mix,
               limit_vs_exception, session_lifecycle, missing_default, refund_edges, undefined_terms):
        found = fn(s.requirements, doc)
        assert len(found) == 1, fn.__name__
        assert _quotes_ok(found, s, doc), fn.__name__
    assert "перцентил" in nfr_metric(s.requirements, doc)[0].problem
    pre = acceptance_preconditions(s.requirements, doc)[0].problem
    assert "включено ли уведомление" in pre and "отправлялся ли push" in pre
    tpl = template_unfilled(s.requirements, doc)[0]
    assert tpl.severity == "minor" and "согласующих" in tpl.problem and "версия" in tpl.problem


def test_nfr_with_percentile_and_load_is_not_flagged(tmp_path):
    bad = "# Д\n\n## Нефункциональные требования\n- **НФТ-1.** Сервис отвечает в течение 2 секунд.\n"
    good = bad.replace("в течение 2 секунд", "для 95 % запросов в течение 2 секунд при нагрузке 100 rps")
    d1, s1 = _doc(tmp_path, bad, "a.md")
    d2, s2 = _doc(tmp_path, good, "b.md")
    assert len(nfr_metric(s1.requirements, d1)) == 1 and _quotes_ok(nfr_metric(s1.requirements, d1), s1, d1)
    assert nfr_metric(s2.requirements, d2) == []


def test_message_text_given_is_not_flagged(tmp_path):
    bad = "# Д\n\n## UI\nПри ошибке ввода сообщение появляется под полем.\n"
    good = "# Д\n\n## UI\nПри ошибке ввода под полем появляется сообщение «Введите сумму от 1 000 ₸».\n"
    d1, s1 = _doc(tmp_path, bad, "a.md")
    d2, s2 = _doc(tmp_path, good, "b.md")
    assert len(message_texts(s1.requirements, d1)) == 1
    assert message_texts(s2.requirements, d2) == []


def test_state_after_500_described_is_not_flagged(tmp_path):
    text = API_DOC + "\n### Статусы\n**500.** Ответ в случае внутренней ошибки сервера.\n"
    d1, s1 = _doc(tmp_path, text, "a.md")
    d2, s2 = _doc(tmp_path, text + "При ответе 500 настройка не сохраняется, изменение откатывается.\n", "b.md")
    assert len(state_after_error(s1.requirements, d1)) == 1 and _quotes_ok(state_after_error(s1.requirements, d1), s1, d1)
    assert state_after_error(s2.requirements, d2) == []


def test_acceptance_with_full_preconditions_is_not_flagged(tmp_path):
    head = ("# Д\n\n## Функциональные требования\n- **Ф-1.** По умолчанию уведомление выключено. Максимум один push за месяц.\n\n"
            "## Критерии приемки\n\n| Исходные условия | Действие | Ожидаемый результат |\n| :--- | :--- | :--- |\n")
    bad = head + "| Расходы 48 500 ₸, порог 50 000 ₸ | Покупка 1 500 ₸ | Один push |\n"
    good = head + "| Уведомление включено, push в этом месяце не отправлялся, расходы 48 500 ₸ | Покупка 1 500 ₸ | Один push |\n"
    d1, s1 = _doc(tmp_path, bad, "a.md")
    d2, s2 = _doc(tmp_path, good, "b.md")
    assert len(acceptance_preconditions(s1.requirements, d1)) == 1
    assert acceptance_preconditions(s2.requirements, d2) == []


def test_filled_template_is_not_flagged(tmp_path):
    text = ("# Д\n\n### Ревью\n| Проверка | Отметка |\n| :--- | :--- |\n| Покрытие | Да |\n\n### Блок согласующих\n\n"
            "| Подразделение | ФИО ответственного | Подпись |\n| :--- | :--- | :--- |\n| ДИТ | Иванов И. И. | есть |\n")
    d, s = _doc(tmp_path, text)
    assert template_unfilled(s.requirements, d) == []
    empty = text.replace("| ДИТ | Иванов И. И. | есть |", "| | | |")
    d2, s2 = _doc(tmp_path, empty, "e.md")
    assert len(template_unfilled(s2.requirements, d2)) == 1


def test_api_codes_and_body_on_organizers_document():
    doc = read_document(REAL)
    s = split_requirements(doc)
    found = api_codes_and_body(s.requirements, doc)
    assert sorted(f.kind for f in found) == ["contradiction", "gap"] and _quotes_ok(found, s, doc)
    assert "201" in next(f for f in found if f.kind == "gap").problem


def test_api_described_code_and_body_are_not_flagged(tmp_path):
    text = API_DOC + ("\n### Ответ\nЕсли результат 200 — успешный.\n\n### Статусы\n**200.** Успех.\n**400.** Ошибка.\n"
                      "\n#### Request body\n* **Content-Type:** `application/json`.\n* Тело: `{\"amount\": 50000}`.\n")
    d, s = _doc(tmp_path, text)
    assert api_codes_and_body(s.requirements, d) == []


def test_unit_mix_same_unit_is_not_flagged(tmp_path):
    d, s = _doc(tmp_path, "# Д\n\n## Данные\nХранить сумму покупки в тиынах и порог в тиынах.\n")
    assert unit_mix(s.requirements, d) == []
    d2, s2 = _doc(tmp_path, "# Д\n\n## Данные\nХранить сумму покупки в тиынах и порог в тенге.\n", "b.md")
    assert len(unit_mix(s2.requirements, d2)) == 1


def test_critic_merges_duplicates_and_calibrates(tmp_path):
    """Критик (deep): дубль из другого прохода объединяется с целью → rejected «дубль S-01», серьёзность — наибольшая,
    источник — оба прохода; калибровка повышает LLM-замечание, но не понижает правило."""
    from req_review.checker import ReviewResult, SetFinding, SetRef
    from req_review.critic import run_critic
    from req_review.llm import BaseLLM

    doc, s = _doc(tmp_path, API_DOC)
    rule = SetFinding("gap", "set_complete", [SetRef("DOC", "Сохранение порога")], "Нет метода чтения.", "critical", "Добавить GET.", "правило")
    dup = SetFinding("gap", "set_complete", [SetRef("DOC", "читает и сохраняет")], "API не позволяет прочитать порог.", "major",
                     "Добавить метод.", "LLM (проход полноты)")
    other = SetFinding("gap", "set_validatable", [SetRef("DOC", "в течение минуты")], "НФТ без перцентиля.", "minor", "—", "LLM")
    low = SetFinding("structure", "set_complete", [SetRef("DOC", "Сохранение порога")], "Шаблон.", "major", "—", "правило")
    from req_review.checker import Finding, ReqResult

    r0 = s.requirements[0]
    req_f = Finding(r0.rid, "complete", r0.text[:10], "Нет метода чтения (к требованию).", "major", "—", "LLM")
    rv = ReviewResult(doc=doc, split=s, req_results=[ReqResult(r0, [req_f])], set_findings=[rule, dup, other, low], dropped=[])

    class Fake(BaseLLM):
        provider, model = "fake", "fake"

        def generate_json(self, system, prompt, *, task="", context=None):
            assert "merge" in system
            # n=1 — замечание к требованию (идёт первым), n=2..5 — замечания набора
            return {"verdicts": [{"n": 1, "verdict": "merge", "into": 2, "reason": "к требованию — не объединяется"},
                                 {"n": 2, "verdict": "keep", "severity": "critical"},
                                 {"n": 3, "verdict": "merge", "into": 2, "reason": "та же проблема"},
                                 {"n": 4, "verdict": "keep", "severity": "major"},
                                 {"n": 5, "verdict": "keep", "severity": "minor"}]}

    run_critic(rv, Fake(), log=lambda *a: None)
    assert [f.problem for f in rv.set_findings] == ["Нет метода чтения.", "НФТ без перцентиля.", "Шаблон."]
    assert rv.set_findings[0].source == "правило+LLM (проход полноты)" and rv.set_findings[0].confidence == "high"
    assert rv.set_findings[1].severity == "major"  # калибровка повысила LLM-замечание
    assert rv.set_findings[2].severity == "major"  # правило калибровкой не понижается
    assert rv.req_results[0].findings == [req_f]  # замечание к требованию осталось на месте
    rej = [r for r in rv.rejected if r.get("duplicate_of")]
    assert len(rej) == 1 and rej[0]["reason"].startswith("дубль S-01") and rv.critic_merged == 1


def test_recover_uncovered_lines_adds_only_verified_requirements(tmp_path):
    """«Дорезка»: строка вне нарезки уходит модели; добавляется только требование с цитатой из этих строк."""
    from req_review.depth import recover_uncovered
    from req_review.llm import BaseLLM

    text = ("# Д\n\n## Требования\n\n### Функциональные требования\n- **Ф-1.** Система должна хранить порог.\n\n"
            "### Экран\nКнопка «Сохранить» неактивна, пока сумма вне диапазона.\n")
    doc, s = _doc(tmp_path, text)
    before = line_coverage(doc, s.requirements)["uncovered"]
    assert any("неактивна" in u["text"] for u in before)

    class Fake(BaseLLM):
        provider, model = "fake", "fake"

        def generate_json(self, system, prompt, *, task="", context=None):
            assert task == "split" and "неактивна" in prompt
            return {"requirements": [{"doc_id": None, "quote": "Кнопка «Сохранить» неактивна, пока сумма вне диапазона."},
                                     {"doc_id": None, "quote": "Система должна отправлять SMS каждый час."}]}

    n0 = len(s.requirements)
    info = recover_uncovered(doc, s, Fake(), log=lambda *a: None)
    assert info == {"uncovered_before": len(before), "recovered": 1}
    added = s.requirements[n0:]
    assert len(added) == 1 and added[0].extra.get("recovered") and quote_in(added[0].text, doc.text)
    assert line_coverage(doc, s.requirements)["uncovered"] == [u for u in before if "неактивна" not in u["text"]]


def test_fix_plan_items_have_example_formulation(tmp_path):
    """План исправлений: пример берётся из переписанного требования, затем из шаблона kb/patterns, затем из рекомендации."""
    from req_review.checker import Finding, ReqResult, ReviewResult, SetFinding, SetRef
    from req_review.depth import fix_plan

    doc, s = _doc(tmp_path, API_DOC)
    r1, r2 = s.requirements[0], s.requirements[1]
    rr1 = ReqResult(r1, [Finding(r1.rid, "unambiguous", r1.text[:10], "Неоднозначно.", "critical", "Уточнить.", "LLM")],
                    rewrite="Клиент задаёт целый порог от 1 000 до 1 000 000 ₸ включительно.")
    rr2 = ReqResult(r2, [Finding(r2.rid, "verifiable", r2.text[:10], "Непроверяемо.", "critical", "Уточнить.", "LLM")],
                    rewrite_pattern={"id": "p1", "title": "Событие", "template": "Когда <событие>, система должна <действие>."})
    sf = SetFinding("gap", "set_complete", [SetRef("DOC", "REST type")], "Нет метода чтения.", "critical",
                    "Добавить метод чтения (например, GET /alerts/limit?cardId=…): ответ — порог.", "правило")
    rv = ReviewResult(doc=doc, split=s, req_results=[rr1, rr2], set_findings=[sf], dropped=[])
    plan = {tuple(it["ids"]): it for it in fix_plan(rv)}
    assert plan[("S-01",)]["example"] == "GET /alerts/limit?cardId=…" and plan[("S-01",)]["example_source"] == "из рекомендации"
    assert plan[(r1.rid,)]["example"].startswith("Клиент задаёт") and plan[(r1.rid,)]["example_source"] == f"переписанное {r1.rid}"
    assert plan[(r2.rid,)]["example_source"].startswith("шаблон kb/patterns")


def test_limit_vs_exception_names_both_rules():
    doc = read_document(REAL)
    s = split_requirements(doc)
    f = limit_vs_exception(s.requirements, doc)[0]
    assert f.severity == "critical" and f.kind == "contradiction" and "Ф-3" in f.problem and "Ф-4" in f.problem
    assert len({r.req_id for r in f.refs}) == 2


def test_limit_with_explicit_precedence_or_without_exception(tmp_path):
    base = "# Д\n\n## Функциональные требования\n- **Ф-1.** Клиент получает не более одного push за месяц.\n"
    d1, s1 = _doc(tmp_path, base + "- **Ф-2.** Смена порога вызывает push независимо от истории.\n", "a.md")
    d2, s2 = _doc(tmp_path, base + "- **Ф-2.** Клиент задаёт порог.\n", "b.md")
    assert len(limit_vs_exception(s1.requirements, d1)) == 1
    assert limit_vs_exception(s2.requirements, d2) == []


def test_session_lifecycle_described_is_not_flagged(tmp_path):
    text = API_DOC + "| **Authorization** | Bearer, сессия владельца карты |\n"
    d1, s1 = _doc(tmp_path, text, "a.md")
    d2, s2 = _doc(tmp_path, text + "\nСрок действия токена — 15 минут; при истёкшем токене метод возвращает 401.\n", "b.md")
    assert len(session_lifecycle(s1.requirements, d1)) == 1 and _quotes_ok(session_lifecycle(s1.requirements, d1), s1, d1)
    assert session_lifecycle(s2.requirements, d2) == []


def test_missing_default_described_is_not_flagged(tmp_path):
    base = "# Д\n\n## Функциональные требования\n- **Ф-1.** Клиент задаёт порог от 1 000 до 1 000 000 ₸.\n"
    d1, s1 = _doc(tmp_path, base, "a.md")
    d2, s2 = _doc(tmp_path, base + "- **Ф-2.** По умолчанию порог равен 50 000 ₸.\n", "b.md")
    assert len(missing_default(s1.requirements, d1)) == 1
    assert missing_default(s2.requirements, d2) == []


def test_real_eval_counts_and_writes_results_section(tmp_path, monkeypatch):
    """real_eval: дефект засчитывается по тексту проблемы; раздел в RESULTS.md заменяется, а не дублируется."""
    import sys

    sys.path.insert(0, str(ROOT / "bench"))
    import real_eval

    rep = {"passport": {"model": "m", "agent_version": "v"}, "requirements": [],
           "set_findings": [{"problem": "В API нет метода чтения настроек", "fix": ""},
                            {"problem": "Не описан контракт события процессинга", "fix": ""}]}
    res = real_eval.evaluate(rep)
    found = {r["id"] for r in res["rows"] if r["found"]}
    assert {"N14", "N15"} <= found and res["total"] == 26
    monkeypatch.setattr(real_eval, "HERE", tmp_path)
    (tmp_path / "RESULTS.md").write_text("# Бенчмарк\n", encoding="utf-8")
    real_eval.write_section([("v5", res)])
    real_eval.write_section([("v5", res)])
    text = (tmp_path / "RESULTS.md").read_text(encoding="utf-8")
    assert text.startswith("# Бенчмарк") and text.count(real_eval.SECTION) == 1 and "| **Найдено** |" in text


def test_refund_edges_described_is_not_flagged(tmp_path):
    base = ("# Д\n\n## Функциональные требования\n- **Ф-1.** Возврат уменьшает расходы месяца исходной покупки.\n"
            "- **Ф-2.** При достижении порога клиент получает push.\n")
    d1, s1 = _doc(tmp_path, base, "a.md")
    d2, s2 = _doc(tmp_path, base + "- **Ф-3.** Частичный возврат уменьшает расходы на сумму возврата; push не отзывается.\n", "b.md")
    assert len(refund_edges(s1.requirements, d1)) == 1 and _quotes_ok(refund_edges(s1.requirements, d1), s1, d1)
    assert refund_edges(s2.requirements, d2) == []


def test_model_answers_off_schema_do_not_crash(tmp_path):
    """Ответ модели не по схеме (ссылки и замечания строками) не роняет прогон: строки-ссылки разбираются,
    строки-замечания пропускаются, цитаты по-прежнему проверяются."""
    from req_review.checker import norm_refs
    from req_review.depth import completeness_pass
    from req_review.llm import BaseLLM

    assert norm_refs("R-003: «Сохранение порога»") == [{"id": "R-003", "quote": "Сохранение порога"}]
    assert norm_refs({"id": "DOC", "quote": "x"}) == [{"id": "DOC", "quote": "x"}]
    assert norm_refs(None) == []
    doc, s = _doc(tmp_path, API_DOC)

    class Fake(BaseLLM):
        provider, model = "fake", "fake"

        def generate_json(self, system, prompt, *, task="", context=None):
            return {"findings": ["просто строка", {"check": "terms", "refs": ["Сохранение порога", 7],
                                                   "problem": "Термин не определён.", "severity": "major", "fix": "—"}]}

    found, dropped = [], []
    completeness_pass(s, doc, Fake(), dropped, found, log=lambda *a: None)
    assert len(found) == 1 and found[0].refs[0].quote == "Сохранение порога" and _quotes_ok(found, s, doc)


def test_undefined_condition_terms_on_organizers_document():
    """N24: «активная карта KZT», «проведённые покупки», «исходный итог» используются как условия, но не определены."""
    doc = read_document(REAL)
    s = split_requirements(doc)
    f = undefined_terms(s.requirements, doc)[0]
    assert f.severity == "major" and f.criterion == "set_comprehensible" and _quotes_ok([f], s, doc)
    assert "активной карты KZT" in f.problem and "проведённые покупки" in f.problem


@pytest.mark.parametrize("definition", [
    "## 1. Термины\n\n- Активная карта — карта в статусе «Действует».\n",
    "## Пояснения\nАктивная карта — это карта в статусе «Действует».\n",
    "## Пояснения\nПод активной картой понимается карта в статусе «Действует»; активная карта означает статус «Действует».\n",
])
def test_defined_condition_term_is_not_flagged(tmp_path, definition):
    rule = "## 2. Функциональные требования\n\n- **Ф-1.** Держатель активной карты задаёт порог.\n"
    d1, s1 = _doc(tmp_path, "# Д\n\n" + rule, "a.md")
    d2, s2 = _doc(tmp_path, "# Д\n\n" + definition + "\n" + rule, "b.md")
    assert len(undefined_terms(s1.requirements, d1)) == 1
    assert undefined_terms(s2.requirements, d2) == []


def test_deep_profile_runs_focused_passes_with_verified_quotes(tmp_path, monkeypatch):
    """Профиль deep: узкие проходы (по одному классу на запрос) добавляют только замечания с подтверждённой цитатой."""
    from req_review.mock_llm import MockLLM
    from req_review.pipeline import Options, review_document

    monkeypatch.setenv("RAG", "off")
    rv = review_document(REAL, MockLLM(), Options(profile="deep", domain="none"), log=lambda *a: None)
    assert set(rv.focus) == {"focus_bounds", "focus_api_negative", "focus_acceptance", "focus_nfr", "focus_errors_ui",
                             "focus_data", "focus_integration"}
    added = [f for f in rv.set_findings if f.source.startswith("LLM (узкий проход")]
    assert added and all(v >= 0 for v in rv.focus.values())
    assert any(d["problem"] == "[mock] выдуманный пропуск" for d in rv.dropped)
    by = {r.rid: r.text for r in rv.split.requirements}
    assert all(quote_in(x.quote, by.get(x.req_id, rv.doc.text)) for f in rv.set_findings for x in f.refs)
    assert rv.depth["review_stats"]["focused"] == rv.focus


def test_focused_pass_skipped_when_not_applicable(tmp_path):
    from req_review.focus import applicable

    d, s = _doc(tmp_path, "# Д\n\n## Функциональные требования\n- **Ф-1.** Клиент видит список карт.\n")
    from req_review.focus import PASSES

    assert not any(applicable(t, s, d) for t in PASSES)


def test_self_consistency_keeps_only_confirmed_llm_findings(tmp_path):
    """Самосогласованность: замечание модели остаётся, если второй проход (другая температура) его подтвердил;
    правило не трогается; неподтверждённое — в rejected с причиной."""
    from req_review.checker import Finding, ReqResult, ReviewResult
    from req_review.focus import self_consistency
    from req_review.llm import BaseLLM

    doc, s = _doc(tmp_path, API_DOC)
    r = s.requirements[0]
    q = " ".join(r.text.split()[:3])
    a = Finding(r.rid, "verifiable", q, "Непроверяемо.", "major", "—", "LLM")
    b = Finding(r.rid, "singular", q, "Составное.", "minor", "—", "LLM")
    c = Finding(r.rid, "complete", q, "Правило.", "major", "—", "правило")
    rv = ReviewResult(doc=doc, split=s, req_results=[ReqResult(r, [a, b, c])], set_findings=[], dropped=[])
    temps = []

    class Fake(BaseLLM):
        provider, model, temperature = "fake", "fake", 0.0

        def generate_json(self, system, prompt, *, task="", context=None):
            temps.append(self.temperature)
            return {"results": [{"id": r.rid, "findings": [{"criterion": "verifiable", "quote": q, "problem": "x",
                                                            "severity": "major", "fix": "—"}]}]}

    llm = Fake()
    st = self_consistency(rv, llm, batch_size=6, log=lambda *x: None)
    assert temps == [0.4] and llm.temperature == 0.0  # второй проход — с другой температурой, затем возврат
    assert st == {"confirmed": 1, "removed": 1}
    assert [f.problem for f in rv.req_results[0].findings] == ["Непроверяемо.", "Правило."]
    assert a.source == "LLM ×2"
    assert rv.rejected[0]["problem"] == "Составное." and "самосогласованность" in rv.rejected[0]["reason"]


def test_markdown_summary_30s_anchors_and_no_repeated_texts(tmp_path, monkeypatch):
    """Markdown: блок «Итог за 30 секунд» сверху, каждая ссылка #r-…/#s-… ведёт на существующий якорь,
    6 разделов ТЗ по порядку, полный текст требования не повторяется, отчёт меньше, чем у v5 (129 КБ без модели)."""
    import re as _re

    from req_review.cli import main

    monkeypatch.setenv("LLM_PROVIDER", "rules")
    monkeypatch.setenv("RAG", "off")
    out = tmp_path / "r.md"
    assert main([str(REAL), str(out), "--env", str(tmp_path / "x.env"), "--quiet", "--no-xlsx", "--no-jira", "--no-html"]) == 0
    md = out.read_text(encoding="utf-8")
    head = md.split("## 1. Паспорт прогона")[0]
    assert "<!-- reqlens:summary:start -->" in head and "<!-- reqlens:summary:end -->" in head
    assert "Итог за 30 секунд" in head and "| Разработка | Тестирование |" in head and "Что исправить первым" in head
    assert 5 <= len(_re.findall(r"(?m)^\d+\. ", head.split("Что исправить первым")[1])) <= 8
    anchors = set(_re.findall(r'<a id="([rs]-\d+)"></a>', md))
    links = set(_re.findall(r"\]\(#([rs]-\d+)\)", md))
    assert links and links <= anchors, links - anchors
    pos = [md.index(f"## {i}. ") for i in range(1, 7)]
    assert pos == sorted(pos)
    d = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    for r in d["requirements"]:
        if len(r["text"]) > 140:
            assert md.count(r["text"]) <= 1, r["rid"]
    assert len(md.encode()) < 129_000


def test_ref_with_requirement_id_only_gets_verbatim_quote(tmp_path):
    """Модель указала требование без цитаты ("R-001") — цитатой становится начало его текста (дословно);
    "DOC" без цитаты отбрасывается: место указать нельзя."""
    from req_review.depth import llm_set_pass
    from req_review.llm import BaseLLM

    doc, s = _doc(tmp_path, API_DOC)
    r = s.requirements[0]

    class Fake(BaseLLM):
        provider, model = "fake", "fake"

        def generate_json(self, system, prompt, *, task="", context=None):
            return {"findings": [{"refs": [r.rid], "problem": "Граница не определена.", "severity": "major", "fix": "—"},
                                 {"refs": ["DOC"], "problem": "Без места.", "severity": "major", "fix": "—"}]}

    found, dropped = [], []
    n = llm_set_pass(s, doc, Fake(), dropped, found, log=lambda *a: None, system="x", task="focus_bounds", label="t", source="LLM")
    assert n == 1 and found[0].refs[0].req_id == r.rid and quote_in(found[0].refs[0].quote, r.text)
    assert len(dropped) == 1


@pytest.mark.parametrize("fmt", ["docx", "pdf"])
def test_organizers_document_in_docx_and_pdf(tmp_path, monkeypatch, fmt):
    """Документ организаторов в DOCX и PDF (таблицы Word / таблицы PDF, заголовки по размеру шрифта, переносы строк)
    без модели находит столько же ожидаемых дефектов, сколько Markdown; цитаты дословные, у PDF есть страницы."""
    import sys

    from req_review.cli import main

    sys.path.insert(0, str(ROOT / "bench" / "real"))
    sys.path.insert(0, str(ROOT / "bench"))
    import formats
    import real_eval

    if fmt == "pdf":
        pytest.importorskip("reportlab")
        if not any(f.exists() for f in formats.FONTS):
            pytest.skip("нет шрифта с кириллицей")
    src = (formats.to_docx if fmt == "docx" else formats.to_pdf)(tmp_path / f"n.{fmt}")
    monkeypatch.setenv("LLM_PROVIDER", "rules")
    monkeypatch.setenv("RAG", "off")
    out = tmp_path / "r.md"
    assert main([str(src), str(out), "--env", str(tmp_path / "x.env"), "--quiet", "--no-xlsx", "--no-jira", "--no-html"]) == 0
    rep = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    res = real_eval.evaluate(rep)
    assert res["found"] >= 25 and res["critical_found"] >= 6, [r["id"] for r in res["rows"] if not r["found"]]
    doc = read_document(src)
    by = {r["rid"]: r["text"] for r in rep["requirements"]}
    assert all(quote_in(f["quote"], by[r["rid"]]) for r in rep["requirements"] for f in r["findings"])
    assert all(quote_in(x["quote"], by.get(x.get("id") or x.get("req_id"), doc.text)) for f in rep["set_findings"] for x in f["refs"])
    if fmt == "pdf":
        assert doc.pages >= 2 and all(r["page"] for r in rep["requirements"])


def test_no_key_gives_clear_error_and_rules_hint(tmp_path, monkeypatch, capsys):
    """Без ключа — понятная ошибка (код 2) и готовая команда для режима без модели."""
    from req_review.cli import main

    for v in ("GEMINI_API_KEY", "LLM_PROVIDER", "ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    rc = main([str(REAL), str(tmp_path / "r.md"), "--env", str(tmp_path / "нет.env"), "--quiet"])
    err = capsys.readouterr()
    text = err.err + err.out
    assert rc == 2 and "GEMINI_API_KEY" in text and "LLM_PROVIDER=rules python review.py" in text


def test_critical_rule_marker_kept_when_model_uses_other_criterion(tmp_path):
    """«и т.д.» (открытое перечисление → полнота, critical): модель записала его как неоднозначность —
    замечание правила по полноте остаётся отдельно, иначе теряется нарушенная характеристика."""
    from req_review.checker import check_requirements
    from req_review.llm import BaseLLM

    doc, s = _doc(tmp_path, "# Д\n\n## Функциональные требования\n- **Ф-1.** Система должна фильтровать историю по периоду, "
                            "поставщику и т.д.\n")
    r = s.requirements[0]

    class Fake(BaseLLM):
        provider, model = "fake", "fake"

        def generate_json(self, system, prompt, *, task="", context=None):
            return {"results": [{"id": r.rid, "findings": [{"criterion": "unambiguous", "quote": "поставщику и т.д.",
                                                            "problem": "Неоднозначно.", "severity": "major", "fix": "—"}]}]}

    rr = check_requirements(s.requirements, doc, Fake(), 6, [], log=lambda *a: None)[0]
    crits = {(f.criterion, f.source) for f in rr.findings}
    assert ("unambiguous", "LLM + правило") in crits and ("complete", "правило") in crits


def test_citation_audit_counts_and_header(tmp_path, monkeypatch):
    from req_review.cli import main

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    out = tmp_path / "r.md"
    assert main([str(ROOT / "tests" / "fixtures" / "sample_requirements.md"), str(out), "--env", str(tmp_path / "x.env"),
                 "--quiet", "--no-xlsx", "--no-jira"]) == 0
    d = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    ca = d["citation_audit"]
    refs = sum(1 for r in d["requirements"] for f in r["findings"] if f["quote"]) + \
        sum(1 for f in d["set_findings"] for x in f["refs"] if x["quote"])
    assert ca["total"] == refs and ca["verified"] == ca["exact"] + ca["fuzzy"] == ca["total"] and ca["missing"] == 0
    assert ca["dropped"] == len(d["dropped"]) >= 1  # выдуманная цитата mock-модели отброшена
    head = out.read_text(encoding="utf-8").split("## 1. Паспорт прогона")[0]
    assert "Аудит цитат" in head and f"**{ca['verified']}**" in head


def test_pdf_report_is_readable(tmp_path, monkeypatch):
    pytest.importorskip("reportlab")
    from req_review.cli import main
    from req_review.pdf_report import PdfFontError, find_font

    try:
        find_font()
    except PdfFontError:
        pytest.skip("нет шрифта с кириллицей")
    import pdfplumber

    monkeypatch.setenv("LLM_PROVIDER", "rules")
    out = tmp_path / "r.md"
    assert main([str(ROOT / "bench" / "real" / "notifications.md"), str(out), "--env", str(tmp_path / "x.env"),
                 "--quiet", "--no-xlsx", "--no-jira", "--pdf"]) == 0
    pdf = out.with_suffix(".pdf")
    assert pdf.exists() and pdf.stat().st_size < 1024 * 1024
    with pdfplumber.open(pdf) as p:
        text = "".join(pg.extract_text() or "" for pg in p.pages)
    for marker in ("Паспорт прогона", "Нарезка требований", "Проверка каждого требования", "Сводка", "Итог", "Аудит цитат"):
        assert marker in text, marker
    assert "reqlens:summary" not in text and r"\|" not in text
    assert main([str(ROOT / "tests" / "fixtures" / "sample_requirements.md"), str(tmp_path / "n.md"),
                 "--env", str(tmp_path / "x.env"), "--quiet", "--no-xlsx", "--no-jira"]) == 0
    assert not (tmp_path / "n.pdf").exists()  # профиль fast без --pdf — PDF не создаётся


def test_fix_loop_writes_before_after(tmp_path, monkeypatch):
    from req_review.cli import main

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    out = tmp_path / "r.md"
    assert main([str(ROOT / "tests" / "fixtures" / "sample_requirements.md"), str(out), "--env", str(tmp_path / "x.env"),
                 "--quiet", "--no-xlsx", "--no-jira", "--fix-loop"]) == 0
    ba = (tmp_path / "r_before_after.md").read_text(encoding="utf-8")
    assert "| Балл документа |" in ba and "| Критичных |" in ba and "По требованиям" in ba
    d = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    rs = d["rescore"]
    assert rs["counts_after"]["critical"] <= rs["counts_before"]["critical"] and rs["after"] >= rs["before"]
    assert rs["compare"]["counts"]["fixed"] >= 1
    assert len(rs["remaining"]) == rs["counts_after"]["critical"] or len(rs["remaining"]) == 15


def test_ensemble_merge_unions_without_duplicates(monkeypatch):
    from req_review.ensemble import merge, refresh_depth
    from req_review.mock_llm import MockLLM
    from req_review.pipeline import Options, review_document

    monkeypatch.setenv("REQLENS_GAPS", "1")
    fix = ROOT / "tests" / "fixtures" / "sample_requirements.md"
    rv_a = review_document(fix, MockLLM(), Options(), log=lambda m: None)
    rv_b = review_document(fix, MockLLM(), Options(), log=lambda m: None)
    llm_b_only = [(rr.req.rid, f.criterion) for rr in rv_a.req_results for f in rr.findings if "LLM" in f.source][:3]
    assert llm_b_only, "в mock-прогоне должны быть замечания модели"
    for rr in rv_a.req_results:  # модель A «пропустила» три замечания, которые нашла модель B
        rr.findings = [f for f in rr.findings if (rr.req.rid, f.criterion) not in llm_b_only or "LLM" not in f.source]
    total_b = sum(len(rr.findings) for rr in rv_b.req_results) + len(rv_b.set_findings)
    st = merge(rv_a, rv_b)
    refresh_depth(rv_a)
    assert st["b_added"] >= len(llm_b_only) and st["both"] >= 1
    total = sum(len(rr.findings) for rr in rv_a.req_results) + len(rv_a.set_findings)
    assert total == total_b  # одинаковые модели: после объединения — тот же набор, без дублей
    labels = {f.ensemble for rr in rv_a.req_results for f in rr.findings} | {f.ensemble for f in rv_a.set_findings}
    assert labels <= {"обе", "модель A", "модель B", "правило"} and "модель B" in labels and "" not in labels
    by = {rr.req.rid: rr.req.text for rr in rv_a.req_results}
    assert all(quote_in(f.quote, by[rr.req.rid]) for rr in rv_a.req_results for f in rr.findings if f.quote)
    assert rv_a.depth["review_stats"]["confirmed"] == total and rv_a.depth["citation_audit"]["missing"] == 0


def test_ensemble_cli_passport(tmp_path, monkeypatch):
    from req_review.cli import main

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    out = tmp_path / "r.md"
    assert main([str(ROOT / "tests" / "fixtures" / "sample_requirements.md"), str(out), "--env", str(tmp_path / "x.env"),
                 "--quiet", "--no-xlsx", "--no-jira", "--ensemble", "m-one,m-two"]) == 0
    d = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    ens = d["passport"]["ensemble"]
    assert len(ens["models"]) == 2 and ens["both"] >= 1 and ens["only_b"] == 0  # одинаковые mock-модели
    assert "Ансамбль моделей" in out.read_text(encoding="utf-8") and "ансамбль" in d["passport"]["model"]
    assert all(f.get("ensemble") for r in d["requirements"] for f in r["findings"])


def test_html_report_has_v7_blocks_and_hides_them_for_old_reports(tmp_path, monkeypatch):
    from req_review.html_report import build_data
    from req_review.pipeline import Options, run

    monkeypatch.setenv("LLM_PROVIDER", "rules")
    ctx = run(str(ROOT / "bench" / "real" / "notifications.md"), str(tmp_path / "r.md"),
              Options(xlsx=False, jira=False), log=lambda m: None)
    html = (tmp_path / "r.html").read_text(encoding="utf-8")
    assert html.encode("utf-8").__len__() < 1024 * 1024
    for marker in ("summary30HTML", "trustHTML", "acceptanceHTML", "matrixHTML", "Итог за 30 секунд", "30 секундтағы қорытынды",
                   "REQLENS_ASK", "Спроси отчёт", "Есептен сұра"):
        assert marker in html, marker
    d = build_data(ctx)["depth"]
    assert d["verdict"]["development"] and d["fix_plan"] and d["citation_audit"]["total"] > 0
    assert d["lines"]["accounted"] == d["lines"]["total"] and d["matrix"] and d["acceptance"]["percent"] is not None
    ctx.rv.depth = {}  # отчёт 2.2 без полей глубины — блоки не рисуются (D.depth = null)
    assert build_data(ctx)["depth"] is None


def test_tz_self_check_passes_on_submission_report():
    import importlib.util

    spec = importlib.util.spec_from_file_location("tz_check", ROOT / "scripts" / "tz_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows = mod.check(ROOT / "reports" / "requirements-report.md")
    clauses = {r["clause"] for r in rows}
    assert {"§1", "§2", "§3", "§4", "§5", "§6", "§7"} <= clauses
    failed = [r["what"] for r in rows if r["required"] and not r["ok"]]
    assert failed == [], failed
    assert all(r["evidence"] for r in rows)
