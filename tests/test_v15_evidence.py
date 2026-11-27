"""v15: таблица «Доказательства» — только числа из файлов результатов; нет файла — «ещё не измерено»."""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import evidence  # noqa: E402

BLIND = {"agent": {"found": 29, "total": 30, "recall": 29 / 30, "recall_ci": [0.9, 1.0], "critical_found": 7,
                   "critical_total": 7, "clean_total": 15, "clean_flagged": 12, "false_clean_significant": 10},
         "baseline": {"found": 20, "total": 30, "recall": 2 / 3, "recall_ci": [0.5, 0.8333], "false_clean_significant": 0}}
ANSWERS = {"total": 15, "ok": 7, "by_type": {"contradictory": [0, 3]}, "summary": {"blockers_total": 6, "blockers_closed": 4},
           "before": {"critical": 6}, "after": {"critical": 2}}


def test_no_result_files_no_numbers(tmp_path):
    rows = evidence.rows(tmp_path)
    assert rows and all("ещё не измерено" in res for _, res, _ in rows)
    assert not any("%" in res for _, res, _ in rows)  # ни одного числа без файла-источника


def test_numbers_come_from_files(tmp_path):
    (tmp_path / "bench" / "blind").mkdir(parents=True)
    (tmp_path / "bench" / "blind" / "results.json").write_text(json.dumps(BLIND), encoding="utf-8")
    (tmp_path / "examples" / "answers" / "external" / "run").mkdir(parents=True)
    (tmp_path / evidence.SRC["answers"]).write_text(json.dumps(ANSWERS), encoding="utf-8")
    shutil.copy(ROOT / "bench" / "score.json", tmp_path / "bench" / "score.json")
    t = evidence.table(tmp_path)
    assert "найдено **29 из 30** (97 %) [90–100 %], критичных 7 из 7" in t and "Разметка ИИ, не человека" in t
    assert "к 15 заведомо чистым требованиям — **10** (замечания есть у 12 из 15)" in t
    assert "слепой набор — **20 из 30** (67 %) [50–83 %], ложных к чистым 0" in t
    assert "определён верно **7 из 15**; противоречивых **0 из 3**; закрыто блокеров 4 из 6; критичных 6 → 2" in t
    sc = json.loads((ROOT / "bench" / "score.json").read_text(encoding="utf-8"))
    assert f"({sc['found']} из {sc['total']})" in t and ("от " in t) == bool(sc["unjudged"] or sc.get("disputed"))
    assert "ещё не измерено" in t  # документа организаторов в tmp нет — честно «не измерено»


def test_write_inserts_then_replaces_block(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# ReqLens\n\n## В двух словах\n\nтекст\n", encoding="utf-8")
    assert evidence.write(readme, tmp_path) is True
    t = readme.read_text(encoding="utf-8")
    assert t.index(evidence.START) < t.index("## В двух словах") and t.count(evidence.START) == 1
    assert evidence.write(readme, tmp_path) is False  # повтор ничего не меняет
    (tmp_path / "bench" / "blind").mkdir(parents=True)
    (tmp_path / "bench" / "blind" / "results.json").write_text(json.dumps(BLIND), encoding="utf-8")
    assert evidence.write(readme, tmp_path) is True
    t2 = readme.read_text(encoding="utf-8")
    assert t2.count(evidence.START) == 1 and "29 из 30" in t2 and t2.endswith("## В двух словах\n\nтекст\n")


def test_readme_has_generated_evidence_at_top():
    t = (ROOT / "README.md").read_text(encoding="utf-8")
    assert t.count(evidence.START) == 1 and t.count(evidence.END) == 1
    assert t.index(evidence.START) < t.index("## В двух словах")
    blk = t[t.index(evidence.START):t.index(evidence.END)]
    assert "## Доказательства" in blk and "| Что проверяли | Результат | Где проверить |" in blk
