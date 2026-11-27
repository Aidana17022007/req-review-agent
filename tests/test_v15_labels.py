"""v15: лист ручной разметки и перенос вердиктов людей по ключу; агент меток не ставит."""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))

import gold_score as gs  # noqa: E402
import label_sheet as ls  # noqa: E402

HEAD = "| Ключ | Документ | Где | Критерий | Серьёзность | Замечание | Вердикт |\n|---|---|---|---|---|---|---|\n"
ROWS = ["| aaaaaaaaa1 | cards | CRD-01 | verifiable | major | Размыто | |",
        "| aaaaaaaaa2 | cards | CRD-02 | verifiable | major | Нет числа | ложное: шаблон |",
        "| aaaaaaaaa3 | qr | QR-01 | complete | critical | Нет кода ошибки | |"]


def _md(tmp_path: Path) -> Path:
    p = tmp_path / "unmatched.md"
    p.write_text("# Замечания\n\n" + HEAD + "\n".join(ROWS) + "\n", encoding="utf-8")
    return p


def _labels(marks: dict, who: str = "Айгерим (QA)", sheet: str = "unmatched") -> dict:
    return {"sheet": sheet, "annotator": who, "labels": {k: {"verdict": v, "comment": c} for k, (v, c) in marks.items()}}


def test_labels_move_to_md_by_key(tmp_path):
    p = _md(tmp_path)
    rep = ls.apply_labels(_labels({"aaaaaaaaa1": ("настоящий", ""), "aaaaaaaaa3": ("спорно", "нужен | контекст\nбанка")}), p)
    assert rep["applied"] == 2 and not rep["conflicts"] and not rep["unknown"]
    t = p.read_text(encoding="utf-8")
    assert "| aaaaaaaaa1 | cards | CRD-01 | verifiable | major | Размыто | настоящий |" in t
    assert "| aaaaaaaaa3 | qr | QR-01 | complete | critical | Нет кода ошибки | спорно: нужен / контекст банка |" in t
    assert "| aaaaaaaaa2 | cards | CRD-02 | verifiable | major | Нет числа | ложное: шаблон |" in t  # чужое не тронуто
    assert gs.load_verdicts(p) == {"aaaaaaaaa1": True, "aaaaaaaaa2": False, "aaaaaaaaa3": None}
    again = ls.apply_labels(_labels({"aaaaaaaaa1": ("настоящий", "")}), p)
    assert again["same"] == 1 and p.read_text(encoding="utf-8") == t  # повтор ничего не меняет


def test_empty_labels_change_nothing(tmp_path):
    p = _md(tmp_path)
    before = p.read_bytes()
    for labels in ({"sheet": "unmatched", "labels": {}}, {"sheet": "unmatched", "annotator": "", "labels": {}},
                   _labels({"aaaaaaaaa1": ("", "только комментарий")})):
        rep = ls.apply_labels(labels, p)
        assert rep["applied"] == rep["updated"] == 0 and p.read_bytes() == before


def test_conflict_kept_unless_overwrite_and_unknown_reported(tmp_path):
    p = _md(tmp_path)
    rep = ls.apply_labels(_labels({"aaaaaaaaa2": ("настоящий", ""), "bbbbbbbbb9": ("ложное", "")}), p)
    assert rep["conflicts"] == [("aaaaaaaaa2", "ложное: шаблон", "настоящий")] and rep["unknown"] == ["bbbbbbbbb9"]
    assert "| Нет числа | ложное: шаблон |" in p.read_text(encoding="utf-8")
    rep = ls.apply_labels(_labels({"aaaaaaaaa2": ("ложное", "шаблонная фраза")}), p)  # тот же вердикт — уточнение
    assert rep["updated"] == 1 and "| Нет числа | ложное: шаблонная фраза |" in p.read_text(encoding="utf-8")
    rep = ls.apply_labels(_labels({"aaaaaaaaa2": ("настоящий", "")}), p, overwrite=True)
    assert rep["updated"] == 1 and "| Нет числа | настоящий |" in p.read_text(encoding="utf-8")


def test_refuses_labels_not_from_a_person(tmp_path):
    """Без имени разметчика или с одинаковой меткой на всех строках — не переносится (агент не ставит метки)."""
    p = _md(tmp_path)
    before = p.read_bytes()
    with pytest.raises(ls.LabelsError, match="кто размечал"):
        ls.apply_labels(_labels({"aaaaaaaaa1": ("настоящий", "")}, who=" "), p)
    same = {f"{i:010x}": ("настоящий", "") for i in range(ls.MIN_SAME)}
    with pytest.raises(ls.LabelsError, match="одинаковые"):
        ls.apply_labels(_labels(same), p)
    with pytest.raises(ls.LabelsError, match="не из списка"):
        ls.apply_labels(_labels({"aaaaaaaaa1": ("да", "")}), p)  # вердикт другого листа
    assert p.read_bytes() == before
    assert ls.apply_labels(_labels(same), p, force=True)["unknown"]  # --force — осознанно


def test_human_check_sheet_uses_da_net(tmp_path):
    p = tmp_path / "human_check.md"
    p.write_text("| Ключ | Где | Серьёзность | Замечание | Человек |\n|---|---|---|---|---|\n"
                 "| ccccccccc1 | S-01 | critical | GET меняет данные |  |\n", encoding="utf-8")
    rep = ls.apply_labels(_labels({"ccccccccc1": ("да", "")}, sheet="human_check"), p)
    assert rep["applied"] == 1 and "| GET меняет данные | да |" in p.read_text(encoding="utf-8")
    with pytest.raises(ls.LabelsError):
        ls.apply_labels(_labels({"ccccccccc1": ("настоящий", "")}, sheet="human_check"), p)


def test_gold_score_labels_cli(tmp_path, monkeypatch):
    p = _md(tmp_path)
    monkeypatch.setitem(ls.SHEETS["unmatched"], "md", p)
    f = tmp_path / "labels.json"
    f.write_text(json.dumps(_labels({"aaaaaaaaa1": ("ложное", "")}), ensure_ascii=False), encoding="utf-8")
    assert gs.main(["--labels", str(f)]) == 0
    assert gs.load_verdicts(p)["aaaaaaaaa1"] is False
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_labels({"aaaaaaaaa3": ("ложное", "")}, who="")), encoding="utf-8")
    assert gs.main(["--labels", str(bad)]) == 1 and "aaaaaaaaa3" not in gs.load_verdicts(p)


def test_disputed_counts_as_checked_but_not_correct():
    rows = [{"doc": "d", "found": True}]
    items = [{"doc": "d", "where": "A", "problem": "a", "outcome": "tp"},
             {"doc": "d", "where": "B", "problem": "b", "outcome": "unmatched"},
             {"doc": "d", "where": "C", "problem": "c", "outcome": "unmatched"}]
    res = gs.score(rows, items, {gs._key("d", "B", "b"): None, gs._key("d", "C", "c"): True})
    assert res["disputed"] == 1 and res["unjudged"] == 0 and res["judged"] == 2 and res["findings"] == 3
    assert res["precision"] == 1.0 and res["precision_strict"] == pytest.approx(2 / 3) and res["checked_manual"] == 2
    line = gs.readme_line(res)
    assert "от 67 % до 100 %" in line and "проверено 3 из 3" in line and "спорных 1" in line and "не проверены" not in line


def _sheet_data(path: Path) -> dict:
    html = path.read_text(encoding="utf-8")
    return json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S)[1].replace("<\\/", "</"))


@pytest.mark.parametrize("sheet", ["unmatched", "human_check"])
def test_sheet_is_offline_complete_and_unlabelled(tmp_path, sheet):
    """Лист: все строки .md, ни одного выбранного вердикта, без внешних ресурсов, < 1 МБ; .md не меняется."""
    md = ls.SHEETS[sheet]["md"]
    before = md.read_bytes()
    out = ls.build(sheet, tmp_path / "sheet.html")
    assert md.read_bytes() == before
    html = out.read_text(encoding="utf-8")
    data = _sheet_data(out)
    keys = [r[0] for r in ls.md_rows(md)]
    assert out.stat().st_size < 1_000_000 and sorted(it["key"] for it in data["items"]) == sorted(keys)
    assert not any("verdict" in it for it in data["items"])  # агент не предзаполняет метки
    assert 'aria-pressed="true"' not in html and " checked" not in html
    assert not re.search(r'(src|href)="https?://', html) and "@import" not in html
    located = sum(1 for it in data["items"] if it["ctx"])
    assert located >= 0.9 * len(keys)  # почти у всех — строка документа с соседними
    assert data["verdicts"] == ls.SHEETS[sheet]["verdicts"] and "Размечено" in html


def test_sheet_groups_findings_on_same_line():
    lines = ["# Док", "", "- **QR-01.** Система должна быстро отвечать.", "- **QR-02.** Код ошибки не задан.", ""]
    assert ls.locate(lines, "QR-01", "") == [2] and ls.locate(lines, "QR-01, QR-02", "") == [2, 3]
    assert ls.locate(lines, "DOC", "Код  ошибки **не** задан") == [3]  # цитата без markdown и лишних пробелов
    assert ls.locate(lines, "S-04", "") == [] and ls.context(lines, [2], 1) == [[3, lines[2], True], [4, lines[3], False]]
