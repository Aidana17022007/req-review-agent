"""v15: честная точность — «проверено N из M», диапазон, пока проверено не всё; строка README из bench/score.json."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))

import gold_score as gs  # noqa: E402


def _res(unjudged: int, manual: int = 0) -> dict:
    rows = [{"doc": "d", "found": True, "severity": "critical"}] * 9 + [{"doc": "d", "found": False}]
    items = [{"doc": "d", "where": f"A-{i}", "problem": f"p{i}", "outcome": "tp"} for i in range(8)]
    items += [{"doc": "d", "where": "F-1", "problem": "f", "outcome": "fp"}]
    items += [{"doc": "d", "where": f"U-{i}", "problem": f"u{i}", "outcome": "unmatched"} for i in range(unjudged + manual)]
    verdicts = {gs._key("d", f"U-{i}", f"u{i}"): True for i in range(manual)}
    return gs.score(rows, items, verdicts)


def test_readme_line_shows_range_while_findings_unchecked():
    res = _res(unjudged=9)
    line = gs.readme_line(res)
    assert res["judged"] == 9 and res["unjudged"] == 9 and res["findings"] == 18
    assert "от 44 % до 89 %" in line  # 8 из 18 … 8 из 9
    assert "проверено 9 из 18" in line and "ещё 9 не проверены" in line and "вручную 0" in line
    assert "полнота **90 %**" in line and "критичных и противоречий **9 из 9**" in line
    assert "точность **" not in line  # одного числа точности нет, пока проверено не всё


def test_readme_line_single_number_when_all_checked():
    res = _res(unjudged=0, manual=3)
    line = gs.readme_line(res)
    assert res["unjudged"] == 0 and res["checked_manual"] == 3 and res["checked_gold"] == 9
    assert "точность **92 %**" in line and "проверены все 12" in line and "вручную 3" in line and " до " not in line


def test_results_md_says_checked_n_of_m_and_range():
    text = gs.md(_res(unjudged=9), "тест")
    assert "**Проверено 9 из 18 существенных замечаний**" in text and "не проверено 9" in text
    assert "| Точность | **от 44 % до 89 %** (проверено не всё) | — |" in text
    full = gs.md(_res(unjudged=0, manual=3), "тест")
    assert "| Точность | **92 %** |" in full and "проверено не всё" not in full


def test_update_readme_replaces_only_between_markers(tmp_path):
    p = tmp_path / "README.md"
    p.write_text(f"| a | старое {gs.README_START}точность 99 %{gs.README_END} |\nхвост {gs.README_START}x{gs.README_END}\n",
                 encoding="utf-8")
    res = _res(unjudged=9)
    assert gs.update_readme(res, p) == 2
    t = p.read_text(encoding="utf-8")
    assert "точность 99 %" not in t and t.count(gs.readme_line(res)) == 2 and t.startswith("| a | старое ")
    assert gs.update_readme(res, p) == 2 and p.read_text(encoding="utf-8") == t  # повтор ничего не меняет
    q = tmp_path / "plain.md"
    q.write_text("без меток\n", encoding="utf-8")
    assert gs.update_readme(res, q) == 0 and q.read_text(encoding="utf-8") == "без меток\n"


def test_write_results_replaces_section_instead_of_appending(tmp_path):
    p = tmp_path / "RESULTS.md"
    p.write_text("# R\n\n## Единый замер (v13): старое\n\nстарая таблица\n\n## Реакция\n\nхвост\n", encoding="utf-8")
    gs.write_results("## Единый замер: новое\n\nновая таблица\n", p)
    gs.write_results("## Единый замер: новое\n\nновая таблица\n", p)
    t = p.read_text(encoding="utf-8")
    assert t.count("## Единый замер") == 1 and "старое" not in t and t.endswith("## Реакция\n\nхвост\n")


def test_readme_numbers_come_from_score_json():
    """README не правят руками: строка между метками совпадает с readme_line(bench/score.json)."""
    res = json.loads((ROOT / "bench" / "score.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.count(gs.README_START) >= 1 and readme.count(gs.README_START) == readme.count(gs.README_END)
    assert gs.README_START + gs.readme_line(res) + gs.README_END in readme
    head = readme.split("## Как это выглядит")[0]
    assert "точность 99 %" not in head
