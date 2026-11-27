"""v13: абляция — что даёт каждый слой ReqLens. Считается из кэша ответов модели, квоту не тратит.

Запуск:  python bench/ablation.py            — варианты на документах бенчмарка (LLM_CACHE=only: только кэш)
         python bench/ablation.py --write    — дописать таблицу в bench/RESULTS.md и сохранить bench/ablation.json

Сначала нужен один прогон бенчмарка с моделью (python bench/run.py) — он наполняет кэш. Вариант, которому для ответа
нужен запрос, которого нет в кэше (например «без правил»: меняется промпт), помечается «нет в кэше: N запросов» —
его цифры неполные, и это видно в таблице. `--fill` один раз дозапрашивает недостающее у модели. «Один промпт в модель» — из bench/baseline/results.json (baseline_eval.py).
Полнота — по внедрённым дефектам; точность — как в bench/run.py (существенные замечания к заведомо чистым требованиям —
ложные). Интервалы — бутстреп по дефектам (bench/gold_score.py::bootstrap).
"""
from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

VARIANTS = [
    ("Полный ReqLens", {}),
    ("Без критика (перепроверки критичных)", {"REQLENS_CRITIC_CRITICAL": "0"}),
    ("Без прохода полноты", {"REQLENS_GAPS": "0"}),
    ("Без трассировки", {"REQLENS_TRACE": "0"}),
    ("Без подсказок правил", {"REQLENS_HINTS": "0"}),
    ("Только правила (без модели)", {"LLM_PROVIDER": "rules"}),
]


@contextmanager
def env(over: dict):
    old = {k: os.environ.get(k) for k in over}
    os.environ.update(over)
    try:
        yield
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def run_variant(truth: dict, over: dict, profile: str = "fast", fill: bool = False) -> dict:
    from gold_score import bootstrap
    from run import evaluate, summarize

    from req_review.llm import build_llm_from_env
    from req_review.pipeline import Options, review_document

    with env({"LLM_CACHE": "1" if fill else "only", **over}):
        llm = build_llm_from_env()
        parts = []
        for name, t in truth["documents"].items():
            rv = review_document(HERE.parent / t["file"], llm, Options(profile=profile, domain="none"), log=lambda m: None)
            parts.append(evaluate(rv, t, name))
    res = summarize(parts)
    return {"recall": res["recall"], "recall_ci": bootstrap([int(r["found"]) for r in res["rows"]]),
            "precision": res["precision"], "f1": res["f1"], "tp": res["tp"], "total": res["total"],
            "fp_on_clean": res["fp_on_clean"], "cache_misses": getattr(llm.stats, "cache_misses", 0), "model": llm.label}


def baseline_row() -> dict | None:
    """«Один промпт в ту же модель» — сохранённый замер bench/baseline_eval.py (5 документов на момент v11)."""
    p = HERE / "baseline" / "results.json"
    if not p.exists():
        return None
    bb = (json.loads(p.read_text(encoding="utf-8")).get("B_bare") or {}).get("bench") or {}
    return {k: bb.get(k) for k in ("recall", "tp", "total", "precision", "fp_on_clean")} if bb else None


def table(rows: list[tuple[str, dict]]) -> str:
    pct = lambda x: "—" if x is None else f"{100 * x:.0f} %"  # noqa: E731
    full = rows[0][1]["recall"] if rows else 0
    out = ["## Абляция (v13): что даёт каждый слой", "", "Команда: `python bench/ablation.py` (ответы модели — из кэша).", "",
           "| Вариант | Полнота | 95 % интервал | Точность | Ложных к чистым | Δ полноты к полному | Нет в кэше |",
           "|---|---|---|---|---|---|---|"]
    for name, r in rows:
        ci = r.get("recall_ci")
        d = "—" if r.get("recall") is None else f"{100 * (r['recall'] - full):+.0f} п. п."
        out.append(f"| {name} | {pct(r.get('recall'))} ({r.get('tp')} из {r.get('total')}) | "
                   f"{f'[{pct(ci[0])}–{pct(ci[1])}]' if ci else '—'} | {pct(r.get('precision'))} | {r.get('fp_on_clean', '—')} | "
                   f"{d} | {r.get('cache_misses', '—')} |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse

    from dotenv import load_dotenv

    ap = argparse.ArgumentParser(prog="python bench/ablation.py")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--profile", default="fast")
    ap.add_argument("--fill", action="store_true",
                    help="дозапросить у модели ответы, которых нет в кэше (тратит квоту один раз; потом снова из кэша)")
    a = ap.parse_args(argv)
    load_dotenv(HERE.parent / ".env")
    truth = json.loads((HERE / "ground_truth.json").read_text(encoding="utf-8"))
    if a.fill:
        for name, over in VARIANTS:
            run_variant(truth, over, a.profile, fill=True)
    rows = [(name, run_variant(truth, over, a.profile)) for name, over in VARIANTS]
    if b := baseline_row():
        rows.append(("Один промпт в ту же модель (v11, 5 документов)", b))
    text = table(rows)
    print(text)
    if a.write:
        (HERE / "ablation.json").write_text(json.dumps(dict(rows), ensure_ascii=False, indent=1), encoding="utf-8")
        with open(HERE / "RESULTS.md", "a", encoding="utf-8") as fh:
            fh.write("\n" + text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
