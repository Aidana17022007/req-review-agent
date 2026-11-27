"""v13: стабильность на документе организаторов — среднее и разброс полноты по N прогонам.

Запуск:  python review.py bench/real/notifications.md reports/runs/report.md --profile fast --runs 3
         python bench/stability.py reports/runs/report_runs.json [--write]
Каждый прогон из <отчёт>_runs.json оценивается bench/real_eval.py::evaluate (26 ожидаемых дефектов).
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def evaluate_runs(data: dict) -> dict:
    from real_eval import evaluate

    res = [evaluate(r) for r in data["runs"]]
    rec = [r["recall"] for r in res]
    found_each = [{row["id"] for row in r["rows"] if row["found"]} for r in res]
    always = set.intersection(*found_each) if found_each else set()
    return {"n": len(res), "found": [r["found"] for r in res], "total": res[0]["total"] if res else 0,
            "critical": [r["critical_found"] for r in res], "critical_total": res[0]["critical_total"] if res else 0,
            "recall_mean": statistics.mean(rec) if rec else 0.0, "recall_min": min(rec) if rec else 0.0,
            "recall_max": max(rec) if rec else 0.0, "recall_sd": statistics.pstdev(rec) if len(rec) > 1 else 0.0,
            "found_in_all": len(always), "info": data.get("info") or {}}


def md(s: dict, src: str) -> str:
    pct = lambda x: f"{100 * x:.0f} %"  # noqa: E731
    return "\n".join([
        f"## Стабильность (v13): {s['n']} прогона на документе организаторов", "",
        f"Команда: `python bench/stability.py {src}`.", "",
        "| Метрика | Значение |", "|---|---|",
        "| Найдено по прогонам | " + " / ".join(f"{x} из {s['total']}" for x in s["found"]) + " |",
        f"| Полнота: среднее (мин–макс, σ) | **{pct(s['recall_mean'])}** ({pct(s['recall_min'])}–{pct(s['recall_max'])}, "
        f"σ {100 * s['recall_sd']:.1f} п. п.) |",
        "| Критичные по прогонам | " + " / ".join(f"{x} из {s['critical_total']}" for x in s["critical"]) + " |",
        f"| Найдено во всех прогонах | {s['found_in_all']} из {s['total']} |",
        f"| Устойчивых замечаний (≥ 2 из N) / только в одном | {s['info'].get('stable', '—')} / {s['info'].get('unstable', '—')} |",
        ""])


def main(argv: list[str]) -> int:
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print(__doc__)
        return 2
    s = evaluate_runs(json.loads(Path(paths[0]).read_text(encoding="utf-8")))
    text = md(s, paths[0])
    print(text)
    if "--write" in argv:
        (HERE / "stability.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
        with open(HERE / "RESULTS.md", "a", encoding="utf-8") as fh:
            fh.write("\n" + text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
