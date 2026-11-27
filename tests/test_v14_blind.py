"""v14: слепой набор — оценка по месту и классу с чистыми требованиями, точностью и бутстрепом (на выдуманном примере)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))

DOC = """# Мини-ТЗ: переводы (выдуманный тестовый документ)

R-1. Система должна быстро проводить перевод.
R-2. Лимит перевода — 500 000 тенге в сутки.
R-3. Лимит перевода — 300 000 тенге в сутки.
R-4. Комиссия за перевод между своими счетами — 0 тенге.
R-5. Пользователь видит статус перевода в истории операций.
"""


def _ext():
    import importlib.util

    spec = importlib.util.spec_from_file_location("ext_score_t", ROOT / "bench" / "external" / "score.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rep(*findings):
    return {"passport": {"model": "test / m", "agent_version": "t", "calls": 2},
            "requirements": [{"rid": rid, "findings": [{"criterion": c, "severity": s, "quote": q, "problem": p}]}
                             for rid, c, s, q, p in findings], "set_findings": []}


def test_score_clean_requirements_precision_and_text_layer(tmp_path):
    sc = _ext()
    src = tmp_path / "doc.txt"
    src.write_text(DOC, encoding="utf-8")
    ann = {"document": str(tmp_path / "doc.docx"), "source": str(src), "annotator": "тест",
           "defects": [{"lines": [3], "class": "ambiguous", "severity": "major"},
                       {"lines": [4, 5], "class": "contradiction", "severity": "critical"}],
           "clean": [{"lines": [6]}, {"lines": [7]}]}
    rep = _rep(("R-1", "unambiguous", "major", "должна быстро проводить", "«быстро» не измеримо"),
               ("R-2", "set_consistent", "critical", "Лимит перевода — 500 000 тенге", "500 000 против 300 000"),
               ("R-4", "complete", "major", "Комиссия за перевод между своими", "ложное: к чистому"),
               ("R-5", "verifiable", "minor", "статус перевода в истории", "ложное мелкое: к чистому"),
               ("R-9", "verifiable", "minor", "нет такой цитаты", "вне разметки"))
    r = sc.score(ann, rep)
    assert r["found"] == 2 and r["matched"] == 2 and r["findings"] == 5
    assert r["clean_total"] == 2 and r["clean_flagged"] == 2 and r["false_clean"] == 2 and r["false_clean_significant"] == 1
    assert r["precision"] == 0.5 and r["precision_strict"] == 0.4  # 2 / (2 + 2) и 2 / 5
    assert sum(f["on_clean"] for f in r["agent_only"]) == 2
    agg = sc.aggregate([r, r])
    assert agg["found"] == 4 and agg["total"] == 4 and agg["recall_ci"] == (1.0, 1.0)
    lo, hi = agg["precision_ci"]
    assert 0 <= lo <= 0.5 <= hi <= 1 and agg == sc.aggregate([r, r]), "seed фиксирован — интервал повторяется"
    assert "к чистому" in sc.to_md(r)


def test_score_requires_text_layer_for_docx(tmp_path):
    sc = _ext()
    ann = {"document": str(tmp_path / "doc.docx"), "defects": [{"lines": [1], "class": "ambiguous", "severity": "minor"}]}
    try:
        sc.score(ann, _rep())
    except ValueError as e:
        assert "source" in str(e)
    else:
        raise AssertionError("без текстового слоя номера строк DOCX не определены")


def test_blind_eval_annotation_keys_three_modes_and_compare(tmp_path, monkeypatch):
    import blind_eval

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MIN_INTERVAL", "0")
    docs, keys, reports = tmp_path / "docs", tmp_path / "keys", tmp_path / "reports"
    docs.mkdir()
    keys.mkdir()
    (docs / "mini.md").write_text(DOC, encoding="utf-8")
    key = {"document": str(docs / "mini.md"), "title": "Мини-ТЗ", "format": "md", "annotator": "тест",
           "defects": [{"lines": [3], "class": "ambiguous", "severity": "major"},
                       {"lines": [4, 5], "class": "contradiction", "severity": "critical"}],
           "clean": [{"lines": [6]}, {"lines": [7]}]}
    (keys / "mini.json").write_text(json.dumps(key, ensure_ascii=False), encoding="utf-8")
    assert blind_eval.is_annotation_key(key)
    for mode in ("agent", "rules"):
        rc = blind_eval.main(["--docs", str(docs), "--keys", str(keys), "--mode", mode, "--profile", "fast",
                              "--out", str(reports / mode)])
        assert rc == 0 and (reports / mode / "mini.json").exists()
    res = tmp_path / "bench_RESULTS.md"
    res.write_text("# Бенчмарк\n\n## Реальный документ организаторов\n\nтаблица\n", encoding="utf-8")
    rc = blind_eval.main(["--docs", str(docs), "--keys", str(keys), "--compare", "--reports", str(reports), "--results", str(res)])
    assert rc == 0
    text = res.read_text(encoding="utf-8")
    assert "## Реальный документ организаторов" in text and text.count("## Слепые документы") == 1
    sec = text[text.index("## Слепые документы"):]
    assert "ReqLens (deep)" in sec and "Только правила" in sec and "Голая модель" not in sec  # нет отчётов — нет колонки
    assert "отдельный ИИ-агент" in sec and "Точность строгая" in sec
    assert len([ln for ln in sec.splitlines() if ln.startswith("| Показатель")]) == 1, "в разделе одна таблица (сайт)"
    agg = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert set(agg) == {"agent", "rules"} and agg["agent"]["total"] == 2
    assert "# Слепые документы: по документам" in (tmp_path / "RESULTS.md").read_text(encoding="utf-8")
