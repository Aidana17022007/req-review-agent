"""v13+ A9: генератор мутаций (детерминирован, опоры верны, строгий счёт) и одинаковое чтение MD / DOCX / PDF."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT / "bench" / "real"))


def test_mutations_deterministic_and_anchors_point_at_defect(tmp_path, monkeypatch):
    import mutate

    monkeypatch.setattr(mutate, "OUT", tmp_path / "m1")
    a = mutate.build(seed=7, per_base=3)
    monkeypatch.setattr(mutate, "OUT", tmp_path / "m2")
    b = mutate.build(seed=7, per_base=3)
    strip = lambda m: [(v["name"], v["defects"]) for v in m["variants"]]  # noqa: E731
    assert strip(a) == strip(b) and a["total_defects"] >= 20
    marks = {"vague": tuple(mutate.VAGUE), "andor": ("и/или",), "tbd": ("TBD",), "open_list": ("т. д.",)}
    for v in a["variants"]:
        lines = (tmp_path / "m1" / f"{v['name']}.md").read_text(encoding="utf-8").splitlines()
        for d in v["defects"]:
            for n, t in zip(d["anchors"], d["anchor_text"]):
                assert lines[n - 1] == t  # опора — ровно та строка, где дефект
            if d["type"] in marks:
                assert any(m in d["anchor_text"][0] for m in marks[d["type"]]), d
            if d["type"] in ("contradiction", "status"):
                assert len(d["anchors"]) == 2 and d["severity"] == "critical"


def test_clean_base_has_no_mutation_markers():
    for p in (ROOT / "bench" / "clean").glob("*.md"):
        if p.name == "README.md":
            continue
        t = p.read_text(encoding="utf-8")
        assert "и/или" not in t and "TBD" not in t and "т. д." not in t, p.name


def test_strict_scoring_needs_quote_on_anchor(tmp_path, monkeypatch):
    import mutate

    from req_review.llm import build_llm_from_env
    from req_review.pipeline import Options, review_document

    monkeypatch.setenv("LLM_PROVIDER", "rules")
    monkeypatch.setattr(mutate, "OUT", tmp_path / "m")
    m = mutate.build(seed=13, per_base=4)
    v = next(v for v in m["variants"] if v["defects"][0]["type"] == "tbd")
    rv = review_document(tmp_path / "m" / f"{v['name']}.md", build_llm_from_env(), Options(), log=lambda x: None)
    d = v["defects"][0]
    assert mutate.found(rv, d)
    moved = {**d, "anchor_text": ["| XX-01 | строка, которой нет в документе | Высокий |"]}
    assert not mutate.found(rv, moved)  # замечание есть, но не на опоре — не засчитывается


def test_contradiction_needs_both_sides(tmp_path, monkeypatch):
    import mutate

    from req_review.llm import build_llm_from_env
    from req_review.pipeline import Options, review_document

    monkeypatch.setenv("LLM_PROVIDER", "rules")
    monkeypatch.setattr(mutate, "OUT", tmp_path / "m")
    m = mutate.build(seed=13, per_base=4)
    v = next(v for v in m["variants"] if v["defects"][0]["type"] == "contradiction")
    rv = review_document(tmp_path / "m" / f"{v['name']}.md", build_llm_from_env(), Options(), log=lambda x: None)
    d = v["defects"][0]
    assert mutate.found(rv, d)
    one_side = {**d, "anchor_text": [d["anchor_text"][0], "| XX-02 | другая строка | Высокий |"]}
    assert not mutate.found(rv, one_side)


def test_formats_same_findings_on_organizers_doc(monkeypatch):
    import formats_eval

    from req_review.rules_llm import RulesOnlyLLM

    res = formats_eval.evaluate(formats_eval.items(1), RulesOnlyLLM(), log=lambda m: None)
    r = res["rows"][0]
    assert r["spread"] <= 1 and r["formats"]["pdf"]["requirements"] == r["formats"]["md"]["requirements"]


def test_pdf_heading_does_not_swallow_next_line(tmp_path):
    from formats import to_pdf

    from req_review.reader import read_document

    body = "".join(f"- **Т-{i}.** Клиент видит баланс карты номер {i} в приложении банка.\n" for i in range(1, 9))
    md = "# Документ\n\n## Тестирование\n\nзаполняется позже\n\n## Требования\n\n" + body
    d = read_document(to_pdf(tmp_path / "a.pdf", md))
    texts = [ln.text for ln in d.lines]
    assert any(t.startswith("#") and t.rstrip().endswith("Тестирование") for t in texts)
    assert "заполняется позже" in texts


def test_manifest_committed_matches_build(tmp_path, monkeypatch):
    import mutate

    committed = json.loads((ROOT / "bench" / "mutations" / "manifest.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(mutate, "OUT", tmp_path / "m")
    fresh = mutate.build(seed=committed["seed"], per_base=committed["per_base"])
    assert [v["name"] for v in fresh["variants"]] == [v["name"] for v in committed["variants"]]
