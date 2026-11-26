"""Оценка отчёта на реальном документе организаторов: сколько из ожидаемых дефектов (bench/real/notifications.json) найдено.

Запуск:  python bench/real_eval.py reports/report.json [ещё.json …]
         python bench/real_eval.py --run                — прогнать агента (модель из .env) и оценить результат
Совпадение ищется регулярными выражениями по тексту проблемы и рекомендации замечаний (не по цитате документа):
«нашёл ли агент эту проблему». Список дефектов составлен командой своими словами — см. поле note в JSON.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRUTH = HERE / "real" / "notifications.json"


def finding_texts(report: dict) -> list[str]:
    out = []
    for r in report.get("requirements", []):
        for f in r.get("findings", []):
            out.append(f"{f.get('problem', '')} {f.get('fix', '')}")
    for f in report.get("set_findings", []):
        out.append(f"{f.get('problem', '')} {f.get('fix', '')}")
    return [t.lower().replace("ё", "е") for t in out]


def evaluate(report: dict, truth: dict | None = None) -> dict:
    truth = truth or json.loads(TRUTH.read_text(encoding="utf-8"))
    texts = finding_texts(report)
    rows = []
    for d in truth["defects"]:
        pats = [re.compile(p.replace("ё", "е"), re.I | re.S) for p in d["match"]]
        hit = next((t for t in texts if any(p.search(t) for p in pats)), None)
        rows.append({**d, "found": hit is not None})
    found = sum(r["found"] for r in rows)
    crit = [r for r in rows if r["severity"] == "critical"]
    return {"rows": rows, "found": found, "total": len(rows), "recall": found / len(rows),
            "critical_found": sum(r["found"] for r in crit), "critical_total": len(crit),
            "findings": len(texts), "model": report.get("passport", {}).get("model", ""),
            "version": report.get("passport", {}).get("agent_version", "")}


def table(results: list[tuple[str, dict]]) -> str:
    head = "| Дефект | " + " | ".join(name for name, _ in results) + " |"
    lines = [head, "|---|" + "---|" * len(results)]
    for i, d in enumerate(results[0][1]["rows"]):
        sev = {"critical": "🔴", "major": "🟠", "minor": "🟡"}[d["severity"]]
        lines.append(f"| {sev} {d['id']} {d['title']} | " + " | ".join("✅" if r["rows"][i]["found"] else "—" for _, r in results) + " |")
    lines.append("| **Найдено** | " + " | ".join(f"**{r['found']} из {r['total']}** ({round(100 * r['recall'])} %), "
                                                    f"критичных {r['critical_found']}/{r['critical_total']}" for _, r in results) + " |")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    paths = [a for a in argv if not a.startswith("--")]
    if "--run" in argv:
        sys.path.insert(0, str(HERE.parent))
        from dotenv import load_dotenv

        from req_review.pipeline import ROOT, Options, run

        load_dotenv(ROOT / ".env")
        out = ROOT / "reports" / "bench_real" / "report.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        run(str(HERE / "real" / "notifications.md"), str(out), Options(profile="deep", xlsx=False, jira=False))
        paths.append(str(out.with_suffix(".json")))
    if not paths:
        print(__doc__)
        return 2
    results = []
    for p in paths:
        rep = json.loads(Path(p).read_text(encoding="utf-8"))
        res = evaluate(rep)
        results.append((Path(p).stem if len(paths) > 1 else "отчёт", res))
        print(f"{p}: {res['found']}/{res['total']} ({round(100 * res['recall'])} %), критичных {res['critical_found']}/"
              f"{res['critical_total']}, замечаний {res['findings']} · {res['model']}")
    print()
    print(table(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
