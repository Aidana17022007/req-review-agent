"""v13: эталон ≥ 150 дефектов, бутстреп-интервалы, разметка несовпавших, кэш-только для абляции."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))


def test_gold_has_at_least_150_defects_on_10_documents():
    gt = json.loads((ROOT / "bench" / "ground_truth.json").read_text(encoding="utf-8"))
    real = json.loads((ROOT / "bench" / "real" / "notifications.json").read_text(encoding="utf-8"))
    assert gt["total_defects"] + len(real["defects"]) >= 150 and len(gt["documents"]) + 1 >= 10
    for name in ("refinance", "qr", "fx"):  # v13: новые документы с непохожими формулировками дефектов
        doc = gt["documents"][name]
        assert len(doc["defects"]) >= 14 and doc["clean_ids"]
        text = (ROOT / doc["file"]).read_text(encoding="utf-8")
        for d in doc["defects"]:
            assert all(f"**{i}.**" in text for i in d["ids"])


def test_inject_is_reproducible(tmp_path):
    from inject import build_doc

    a, ta = build_doc("fx")
    b, tb = build_doc("fx")
    assert a == b and ta == tb and "круглосуточно" in a and "в кратчайшие сроки" in a


def test_bootstrap_deterministic_and_bounds():
    from gold_score import bootstrap

    v = [1] * 90 + [0] * 10
    lo, hi = bootstrap(v)
    assert bootstrap(v) == (lo, hi) and lo < 0.9 < hi and 0.8 <= lo and hi <= 0.97
    assert bootstrap([1, 1, 1]) == (1.0, 1.0) and bootstrap([]) == (0.0, 0.0)


def test_score_uses_verdicts_for_unmatched(tmp_path, monkeypatch):
    import gold_score as score

    rows = [{"doc": "d", "found": True}, {"doc": "d", "found": False}]
    items = [{"doc": "d", "where": "A-1", "problem": "p1", "outcome": "tp"},
             {"doc": "d", "where": "A-2", "problem": "p2", "outcome": "fp"},
             {"doc": "d", "where": "A-3", "problem": "p3", "outcome": "unmatched"},
             {"doc": "d", "where": "A-4", "problem": "p4", "outcome": "unmatched"}]
    k3 = score._key("d", "A-3", "p3")
    res = score.score(rows, items, {k3: True})
    assert res["recall"] == 0.5 and res["judged"] == 3 and res["unjudged"] == 1
    assert res["precision"] == pytest.approx(2 / 3) and res["precision_strict"] == pytest.approx(2 / 4)
    monkeypatch.setattr(score, "UNMATCHED", tmp_path / "u.md")
    assert score.write_unmatched(items, {}) == 2
    t = (tmp_path / "u.md").read_text(encoding="utf-8")
    lines = [ln if not ln.startswith(f"| {k3} ") else ln.rstrip(" |") + " | ложное: шаблонная фраза |" for ln in t.splitlines()]
    (tmp_path / "u.md").write_text("\n".join(lines), encoding="utf-8")
    assert score.load_verdicts(tmp_path / "u.md") == {k3: False}
    score.write_unmatched(items, {})  # пересборка сохраняет вписанный вердикт
    assert score.load_verdicts(tmp_path / "u.md") == {k3: False}


def test_real_items_match_report():
    import gold_score as score

    rep = json.loads((ROOT / "reports" / "requirements-report.json").read_text(encoding="utf-8"))
    rows, items = score.real_items(rep)
    assert len(rows) == 26 and sum(r["found"] for r in rows) == 26
    assert items and {i["outcome"] for i in items} <= {"tp", "unmatched"} and any(i["outcome"] == "tp" for i in items)


def test_cache_only_never_calls_model(tmp_path, monkeypatch):
    from req_review.llm import BaseLLM, LLMError

    class Fake(BaseLLM):
        provider, model = "fake", "m"

        def _call(self, *a, **k):  # pragma: no cover — не должен вызываться
            raise AssertionError("модель вызвана")

    monkeypatch.setenv("LLM_CACHE", "only")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    f = Fake()
    with pytest.raises(LLMError, match="нет в кэше"):
        f.generate_json("s", "p")
    assert f.stats.cache_misses == 1 and f.stats.calls == 0
    cache = f._cache_path("s", "p2")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text('{"ok": true}', encoding="utf-8")
    assert f.generate_json("s", "p2") == {"ok": True}


def test_ablation_variants_run_on_mock(monkeypatch):
    import ablation

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MIN_INTERVAL", "0")
    truth = json.loads((ROOT / "bench" / "ground_truth.json").read_text(encoding="utf-8"))
    one = {"documents": {"fx": truth["documents"]["fx"]}}
    full = ablation.run_variant(one, {})
    no_hints = ablation.run_variant(one, {"REQLENS_HINTS": "0"})
    assert full["total"] == 15 and no_hints["recall"] <= full["recall"]
    assert "Абляция" in ablation.table([("Полный", full), ("Без правил", no_hints)])
