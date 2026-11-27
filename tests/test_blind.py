"""v9: слепая оценка — инфраструктура на выдуманном мини-документе (настоящие документы присылает человек вне команды)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))

MINI = """# Мини-ТЗ: кэшбэк (выдуманный тестовый документ)

## Требования

- **R-1.** Система должна быстро начислять кэшбэк после покупки.
- **R-2.** Кэшбэк начисляется по категориям: кафе, транспорт и т.д.
- **R-3.** Максимальный кэшбэк в месяц — 10 000 тенге.
- **R-4.** Максимальный кэшбэк в месяц — 15 000 тенге.
"""
KEY = {"document": "mini.md", "title": "Мини-ТЗ: кэшбэк", "note": "тестовый ключ",
       "defects": [{"id": "B01", "severity": "critical", "title": "Скорость начисления без порога",
                    "match": ["(размыт|порог|скорост|быстр)"]},
                   {"id": "B02", "severity": "critical", "title": "Лимит 10 000 против 15 000",
                    "match": ["10\\s?000[^.]{0,200}15\\s?000", "15\\s?000[^.]{0,200}10\\s?000", "разные значения"]},
                   {"id": "B03", "severity": "major", "title": "Не описан возврат кэшбэка при отмене покупки",
                    "match": ["возврат[^.]{0,80}кэшбэк", "отмен[^.]{0,80}покупк"]}]}


def test_blind_eval_runs_agent_scores_and_writes_section(tmp_path, monkeypatch):
    import blind_eval

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MIN_INTERVAL", "0")
    docs, keys = tmp_path / "blind", tmp_path / "blind" / "keys"
    keys.mkdir(parents=True)
    (docs / "mini.md").write_text(MINI, encoding="utf-8")
    (docs / "nokey.md").write_text(MINI, encoding="utf-8")  # без ключа — не оценивается
    (keys / "mini.json").write_text(json.dumps(KEY, ensure_ascii=False), encoding="utf-8")
    results = tmp_path / "RESULTS.md"
    results.write_text("# Бенчмарк\n\n## Реальный документ организаторов\n\nтаблица\n", encoding="utf-8")
    assert [p.name for p, _ in blind_eval.pairs(docs, keys)] == ["mini.md"]
    rc = blind_eval.main(["--docs", str(docs), "--out", str(tmp_path / "out"), "--profile", "fast", "--results", str(results)])
    assert rc == 0
    text = results.read_text(encoding="utf-8")
    assert "## Реальный документ организаторов" in text and "## Слепые документы" in text  # чужой раздел не тронут
    row = next(ln for ln in text.splitlines() if ln.startswith("| Мини-ТЗ: кэшбэк"))
    assert "из 3" in row and "B03" in row  # пропуск про возврат mock-агент не находит — он в «Не найдено»
    # повторная запись заменяет раздел, а не дублирует; готовые отчёты — без нового прогона
    rc = blind_eval.main(["--docs", str(docs), "--reports", str(tmp_path / "out"), "--results", str(results)])
    assert rc == 0 and results.read_text(encoding="utf-8").count("## Слепые документы") == 1


def test_blind_eval_without_documents_explains(tmp_path, capsys):
    import blind_eval

    assert blind_eval.main(["--docs", str(tmp_path / "нет")]) == 2
    assert "bench/blind/README.md" in capsys.readouterr().out


def test_bench_run_keeps_appended_sections():
    src = (ROOT / "bench" / "run.py").read_text(encoding="utf-8")
    assert "## Слепые документы" in src and "## Реальный документ организаторов" in src and "KEEP_SECTIONS" in src
