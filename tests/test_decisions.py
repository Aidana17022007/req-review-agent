"""v9: повестка решений для владельца продукта — реальные развилки из противоречий и критичных пропусков."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _lines(d):
    return {x["line"] for x in d["where"]}


def test_organizers_report_has_the_real_forks():
    """На документе организаторов: Ф-2 / пример приёмки (строки 38, 64), Ф-3 / Ф-4 (39, 40), API 200 ERROR / 400."""
    from req_review.decisions import build_decisions

    data = json.loads((ROOT / "reports" / "requirements-report.json").read_text(encoding="utf-8"))
    ds = build_decisions(data)
    assert 3 <= len(ds) <= 8
    assert [d["id"] for d in ds] == [f"D-{i:02d}" for i in range(1, len(ds) + 1)]
    assert any({38, 64} <= _lines(d) for d in ds), "Ф-2 и пример приёмки"
    assert any({39, 40} <= _lines(d) for d in ds), "Ф-3 и Ф-4"
    api = [d for d in ds if "ERROR" in " ".join(d["options"]) and "400" in " ".join(d["options"])]
    assert api, "API: 200 с ошибкой или 400"
    for d in ds:
        assert d["wording"] == "код" and 2 <= len(d["options"]) <= 3 and d["impact"] and d["source_ids"]
        assert all(sid.startswith("S-") for sid in d["source_ids"])
        assert "The " not in d["impact"]  # английские вставки из текста замечаний в повестку не попадают


def test_pipeline_writes_decisions_file_section_and_json(tmp_path, monkeypatch):
    from req_review.pipeline import Options, run

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MIN_INTERVAL", "0")
    out = tmp_path / "report.md"
    ctx = run(str(ROOT / "tests" / "fixtures" / "sample_requirements.md"), str(out),
              Options(html=False, xlsx=False, jira=False, pdf=False), log=lambda m: None)
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["decisions"] and data["decisions"] == ctx.decisions
    first = data["decisions"][0]  # противоречие лимитов 500 000 / 300 000 в тестовом документе
    assert first["source_ids"] == ["S-01"] and first["title"].startswith("Какое значение принять")
    md = out.read_text(encoding="utf-8")
    assert "### Решения для владельца продукта" in md and md.index("## 6. Итог") < md.index("### Решения для владельца")
    dec = (tmp_path / "report_decisions.md").read_text(encoding="utf-8")
    assert "## D-01." in dec and "**Варианты:**" in dec and "*Основание:* S-01" in dec


def test_rephrase_keeps_code_facts_and_rejects_new_numbers():
    from types import SimpleNamespace as NS

    from req_review.decisions import rephrase

    base = [{"id": "D-01", "title": "Какое значение принять: 3 или 5?", "where": [], "impact": "Тесты разойдутся.",
             "options": ["3 (R-1)", "5 (R-2)"], "source_ids": ["S-01"], "wording": "код"},
            {"id": "D-02", "title": "Что верно: A или B?", "where": [], "impact": "Без решения нельзя тестировать.",
             "options": ["A", "B"], "source_ids": ["S-02"], "wording": "код"}]

    class Fake:
        provider = "gemini"

        def generate_json(self, *a, **k):
            return {"items": [{"id": "D-01", "title": "Сколько попыток ввода разрешить клиенту: 3 или 5?", "impact": "Клиент"
                               " узнает о блокировке."},
                              {"id": "D-02", "title": "Выбрать 7 вариантов?", "impact": "Добавлено число 7."}]}

    out = rephrase([dict(d) for d in base], Fake())
    assert out[0]["wording"] == "модель" and out[0]["options"] == base[0]["options"]
    assert out[1]["wording"] == "код" and out[1]["title"] == base[1]["title"]  # новое число 7 — формулировка модели отклонена
    assert rephrase([dict(d) for d in base], NS(provider="mock"))[0]["wording"] == "код"
    assert os.environ.get("LLM_CACHE") == "0"
