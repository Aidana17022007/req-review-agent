"""v13: единый замер — полнота, точность, F1 с 95 % доверительными интервалами (бутстреп) и разметка несовпавших.

Запуск:  python bench/gold_score.py                     — по последнему прогону бенчмарка (bench/results_detail.json,
                                                      его пишет python bench/run.py) и отчёту для сдачи
         python bench/gold_score.py --real ОТЧЁТ.json    — другой отчёт по документу организаторов
         python bench/gold_score.py --write              — дописать таблицу в bench/RESULTS.md и сохранить bench/score.json

Эталон: внедрённые дефекты 9 вымышленных документов (bench/ground_truth.json) + ожидаемые дефекты документа
организаторов (bench/real/notifications.json). Полнота — доля найденных дефектов эталона.
Точность — по существенным и критичным замечаниям: верные (совпали с дефектом эталона) / все размеченные.
Замечания, не совпавшие ни с одним дефектом эталона, не считаются ложными автоматически: они попадают в
bench/unmatched.md, где человек отмечает «настоящий» (дефект есть, но эталон его не содержит) или «ложное».
Неразмеченные в «честную» точность не входят и показываются отдельно; «строгая» точность считает их ложными.
Интервалы — перцентильный бутстреп (1000 повторов, seed 13) по дефектам (полнота) и по замечаниям (точность).
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

UNMATCHED = HERE / "unmatched.md"
VERDICTS = {"настоящий": True, "ложное": False}


def _key(doc: str, where: str, problem: str) -> str:
    return hashlib.sha1(f"{doc}|{where}|{' '.join(problem.split())[:200]}".encode()).hexdigest()[:10]


def load_verdicts(path: Path = UNMATCHED) -> dict[str, bool]:
    """Разметка из bench/unmatched.md: строки таблицы «| key | … | вердикт |»."""
    out: dict[str, bool] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and re.fullmatch(r"[0-9a-f]{10}", cells[0]):
            v = cells[-1].lower().replace("ё", "е")
            for word, val in VERDICTS.items():
                if v.startswith(word.replace("ё", "е")):
                    out[cells[0]] = val
    return out


def real_items(report: dict) -> tuple[list[dict], list[dict]]:
    """Документ организаторов: дефекты (найден / нет) и существенные замечания с исходом (верное / не совпало)."""
    from real_eval import evaluate

    ev = evaluate(report)
    truth = json.loads((HERE / "real" / "notifications.json").read_text(encoding="utf-8"))
    pats = [re.compile(p.replace("ё", "е"), re.I | re.S) for d in truth["defects"] for p in d["match"]]
    rows = [{"doc": "organizers", "type": r["id"], "ids": [r["id"]], "found": r["found"], "severity": r["severity"]}
            for r in ev["rows"]]
    items = []
    for r in report.get("requirements", []):
        for f in r.get("findings", []):
            if f.get("severity") != "minor":
                items.append({"doc": "organizers", "where": r.get("doc_id") or r["rid"], "criterion": f["criterion"],
                              "severity": f["severity"], "quote": f.get("quote", ""), "problem": f.get("problem", ""),
                              "fix": f.get("fix", "")})
    for i, f in enumerate(report.get("set_findings", []), 1):
        if f.get("severity") != "minor":
            items.append({"doc": "organizers", "where": f"S-{i:02d}", "criterion": f["criterion"], "severity": f["severity"],
                          "quote": " / ".join(x.get("quote", "") for x in f.get("refs", []))[:200],
                          "problem": f.get("problem", ""), "fix": f.get("fix", "")})
    for it in items:
        t = f"{it['problem']} {it.pop('fix')}".lower().replace("ё", "е")
        it["outcome"] = "tp" if any(p.search(t) for p in pats) else "unmatched"
    return rows, items


def bootstrap(values: list[int], reps: int = 1000, seed: int = 13) -> tuple[float, float]:
    """95 % перцентильный интервал доли единиц в values."""
    if not values:
        return (0.0, 0.0)
    rnd = random.Random(seed)
    n = len(values)
    stats = sorted(sum(values[rnd.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return stats[int(0.025 * reps)], stats[min(reps - 1, int(0.975 * reps))]


def score(rows: list[dict], items: list[dict], verdicts: dict[str, bool], reps: int = 1000, seed: int = 13) -> dict:
    for it in items:
        it.setdefault("key", _key(it["doc"], it["where"], it["problem"]))
    rec = [int(r["found"]) for r in rows]
    judged = []  # 1 — верное, 0 — ложное; неразмеченные несовпавшие — отдельно
    unjudged = 0
    for it in items:
        if it["outcome"] == "tp":
            judged.append(1)
        elif it["outcome"] == "fp":
            judged.append(0)
        elif it["key"] in verdicts:
            judged.append(int(verdicts[it["key"]]))
        else:
            unjudged += 1
    strict = judged + [0] * unjudged
    r = sum(rec) / len(rec) if rec else 0.0
    p = sum(judged) / len(judged) if judged else 1.0
    ps = sum(strict) / len(strict) if strict else 1.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    by_doc: dict[str, list[int]] = {}
    for row in rows:
        by_doc.setdefault(row["doc"], [0, 0])
        by_doc[row["doc"]][0] += int(row["found"])
        by_doc[row["doc"]][1] += 1
    crit = [int(row["found"]) for row in rows if row.get("severity") == "critical" or row.get("type") == "contradiction"]
    return {"recall": r, "recall_ci": bootstrap(rec, reps, seed), "found": sum(rec), "total": len(rec),
            "precision": p, "precision_ci": bootstrap(judged, reps, seed), "precision_strict": ps,
            "judged": len(judged), "unjudged": unjudged, "f1": f1,
            "critical_found": sum(crit), "critical_total": len(crit), "by_doc": by_doc,
            "method": f"перцентильный бутстреп, {reps} повторов, seed {seed}"}


def write_unmatched(items: list[dict], verdicts: dict[str, bool]) -> int:
    rows = [it for it in items if it["outcome"] == "unmatched"]
    old = {}
    if UNMATCHED.exists():  # сохранить уже вписанные вердикты и комментарии
        for line in UNMATCHED.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and re.fullmatch(r"[0-9a-f]{10}", cells[0]):
                old[cells[0]] = cells[-1]
    out = ["# Замечания, не совпавшие с эталоном", "",
           "Каждая строка — существенное или критичное замечание агента, которого нет в эталоне. В последней колонке впишите",
           "**настоящий** (дефект есть в документе, эталон его не содержит) или **ложное** (дефекта нет), можно с",
           "комментарием после слова. Файл пересобирается `python bench/gold_score.py`, вписанные вердикты сохраняются по ключу.", "",
           "| Ключ | Документ | Где | Критерий | Серьёзность | Замечание | Вердикт |", "|---|---|---|---|---|---|---|"]
    for it in sorted(rows, key=lambda x: (x["doc"], x["where"])):
        prob = " ".join(it["problem"].split())[:220].replace("|", "/")
        out.append(f"| {it['key']} | {it['doc']} | {it['where']} | {it.get('criterion', '')} | {it.get('severity', '')} | {prob} | "
                   f"{old.get(it['key'], '')} |")
    UNMATCHED.write_text("\n".join(out) + "\n", encoding="utf-8")
    return len(rows)


def md(res: dict, label: str) -> str:
    pct = lambda x: f"{100 * x:.0f} %"  # noqa: E731
    ci = lambda c: f"[{pct(c[0])}–{pct(c[1])}]"  # noqa: E731
    lines = ["## Единый замер (v13): эталон из " + str(res["total"]) + " дефектов, 95 % интервалы", "",
             f"*Прогон:* {label}. Команда: `python bench/gold_score.py`. {res['method']}.", "",
             "| Метрика | Значение | 95 % интервал |", "|---|---|---|",
             f"| Полнота | **{pct(res['recall'])}** ({res['found']} из {res['total']}) | {ci(res['recall_ci'])} |",
             f"| Точность (размечено {res['judged']}) | **{pct(res['precision'])}** | {ci(res['precision_ci'])} |",
             f"| Точность строгая (неразмеченные {res['unjudged']} — как ложные) | {pct(res['precision_strict'])} | — |",
             f"| F1 | **{pct(res['f1'])}** | — |",
             f"| Критичные и противоречия | {res['critical_found']} из {res['critical_total']} | — |", "",
             "| Документ | Найдено |", "|---|---|"]
    for d, (f, t) in res["by_doc"].items():
        lines.append(f"| {d} | {f} из {t} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python bench/gold_score.py")
    ap.add_argument("--detail", default=str(HERE / "results_detail.json"), help="построчные исходы bench/run.py")
    ap.add_argument("--real", default=str(ROOT / "reports" / "requirements-report.json"), help="отчёт по документу организаторов")
    ap.add_argument("--write", action="store_true", help="дописать таблицу в bench/RESULTS.md и сохранить bench/score.json")
    a = ap.parse_args(argv)
    rows, items, label = [], [], []
    dp = Path(a.detail)
    if dp.exists():
        det = json.loads(dp.read_text(encoding="utf-8"))
        rows += det["rows"]
        items += det["items"]
        label.append(f"бенчмарк — {det.get('label', '')}")
    else:
        print(f"нет {dp} — сначала python bench/run.py (считаю только документ организаторов)")
    rp = Path(a.real)
    if rp.exists():
        rep = json.loads(rp.read_text(encoding="utf-8"))
        r2, i2 = real_items(rep)
        rows += r2
        items += i2
        label.append(f"документ организаторов — {rep.get('passport', {}).get('model', '')}")
    verdicts = load_verdicts()
    res = score(rows, items, verdicts)
    n_un = write_unmatched(items, verdicts)
    text = md(res, "; ".join(label))
    print(text)
    print(f"несовпавших замечаний: {n_un} (разметка — {UNMATCHED.relative_to(ROOT)})")
    if a.write:
        (HERE / "score.json").write_text(json.dumps({**res, "label": "; ".join(label)}, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
        with open(HERE / "RESULTS.md", "a", encoding="utf-8") as fh:
            fh.write("\n" + text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
