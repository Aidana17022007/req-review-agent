"""v13: единый замер — полнота, точность, F1 с 95 % доверительными интервалами (бутстреп) и разметка несовпавших.

Запуск:  python bench/gold_score.py                     — по последнему прогону бенчмарка (bench/results_detail.json,
                                                      его пишет python bench/run.py) и отчёту для сдачи
         python bench/gold_score.py --real ОТЧЁТ.json    — другой отчёт по документу организаторов
         python bench/gold_score.py --write              — обновить раздел в bench/RESULTS.md, bench/score.json и README
         python bench/gold_score.py --readme             — только строка README по bench/score.json (без пересчёта)
         python bench/gold_score.py --labels labels.json — перенести вердикты из bench/label_sheet.html в unmatched.md

Эталон: внедрённые дефекты 9 вымышленных документов (bench/ground_truth.json) + ожидаемые дефекты документа
организаторов (bench/real/notifications.json). Полнота — доля найденных дефектов эталона.
Точность — по существенным и критичным замечаниям: верные (совпали с дефектом эталона) / все размеченные.
Замечания, не совпавшие ни с одним дефектом эталона, не считаются ложными автоматически: они попадают в
bench/unmatched.md, где человек отмечает «настоящий» (дефект есть, но эталон его не содержит) или «ложное».
Неразмеченные в «честную» точность не входят и показываются отдельно; «строгая» точность считает их ложными.
v15: пока проверено не всё, точность выводится диапазоном [строгая … по проверенным] со строкой «проверено N из M».
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
VERDICTS = {"настоящий": True, "ложное": False, "спорно": None}  # спорно — проверено, но верным не считается


def _key(doc: str, where: str, problem: str) -> str:
    return hashlib.sha1(f"{doc}|{where}|{' '.join(problem.split())[:200]}".encode()).hexdigest()[:10]


def load_verdicts(path: Path = UNMATCHED) -> dict[str, bool | None]:
    """Разметка из bench/unmatched.md: строки таблицы «| key | … | вердикт |» (True / False / None — спорно)."""
    out: dict[str, bool | None] = {}
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
    judged = []  # 1 — верное, 0 — ложное; неразмеченные и спорные несовпавшие — отдельно
    unjudged = disputed = 0
    for it in items:
        if it["outcome"] == "tp":
            judged.append(1)
        elif it["outcome"] == "fp":
            judged.append(0)
        elif it["key"] in verdicts and verdicts[it["key"]] is None:
            disputed += 1
        elif it["key"] in verdicts:
            judged.append(int(verdicts[it["key"]]))
        else:
            unjudged += 1
    strict = judged + [0] * (unjudged + disputed)
    r = sum(rec) / len(rec) if rec else 0.0
    p = sum(judged) / len(judged) if judged else 1.0
    ps = sum(strict) / len(strict) if strict else 1.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    f1s = 2 * ps * r / (ps + r) if ps + r else 0.0
    manual = sum(1 for it in items if it["outcome"] == "unmatched" and it["key"] in verdicts)
    by_doc: dict[str, list[int]] = {}
    for row in rows:
        by_doc.setdefault(row["doc"], [0, 0])
        by_doc[row["doc"]][0] += int(row["found"])
        by_doc[row["doc"]][1] += 1
    crit = [int(row["found"]) for row in rows if row.get("severity") == "critical" or row.get("type") == "contradiction"]
    return {"recall": r, "recall_ci": bootstrap(rec, reps, seed), "found": sum(rec), "total": len(rec),
            "precision": p, "precision_ci": bootstrap(judged, reps, seed), "precision_strict": ps,
            "judged": len(judged), "unjudged": unjudged, "f1": f1, "f1_strict": f1s,
            # v15: сколько замечаний проверено и как — для честной строки «проверено N из M»
            "findings": len(judged) + disputed + unjudged, "correct": sum(judged), "disputed": disputed,
            "checked_gold": len(judged) + disputed - manual, "checked_manual": manual,
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
           "**настоящий** (дефект есть в документе, эталон его не содержит), **ложное** (дефекта нет) или **спорно**, можно",
           "с комментарием после слова. Удобнее — в `bench/label_sheet.html` (текст требования рядом), затем",
           "`python bench/gold_score.py --labels labels.json`. Файл пересобирается `python bench/gold_score.py`, вписанные",
           "вердикты сохраняются по ключу.", "",
           "| Ключ | Документ | Где | Критерий | Серьёзность | Замечание | Вердикт |", "|---|---|---|---|---|---|---|"]
    for it in sorted(rows, key=lambda x: (x["doc"], x["where"])):
        prob = " ".join(it["problem"].split())[:220].replace("|", "/")
        out.append(f"| {it['key']} | {it['doc']} | {it['where']} | {it.get('criterion', '')} | {it.get('severity', '')} | {prob} | "
                   f"{old.get(it['key'], '')} |")
    UNMATCHED.write_text("\n".join(out) + "\n", encoding="utf-8")
    return len(rows)


def _pct(x: float) -> str:
    return f"{100 * x:.0f} %"


def _range(lo: float, hi: float) -> str:
    """«93–99 %»; одно число, если концы совпадают."""
    a, b = f"{100 * lo:.0f}", f"{100 * hi:.0f}"
    return f"{a} %" if a == b else f"{a}–{b} %"


def precision_text(res: dict) -> str:
    """Точность словами: одно число — только когда проверены все замечания и спорных нет, иначе диапазон
    [строгая (непроверенные и спорные — ложные) … по проверенным]."""
    d = res.get("disputed", 0)
    n, m = res["judged"] + d, res.get("findings", res["judged"] + d + res["unjudged"])
    how = f"сверкой с эталоном {res.get('checked_gold', n)}, вручную {res.get('checked_manual', 0)}"
    correct = res.get("correct", round(res["precision"] * res["judged"]))
    sp = f", спорных {d}" if d else ""
    if res["unjudged"] or d:
        rest = f"; ещё {res['unjudged']} не проверены" if res["unjudged"] else ""
        return (f"точность — **от {_pct(res['precision_strict'])} до {_pct(res['precision'])}**: "
                f"проверено {n} из {m} существенных замечаний ({how}), верны {correct}{sp}{rest}")
    return (f"точность **{_pct(res['precision'])}** [{_range(*res['precision_ci'])}]: "
            f"проверены все {m} существенных замечаний ({how}), верны {correct}")


def readme_line(res: dict) -> str:
    """Строка README про эталон: полнота с интервалом, критичные и честная точность (числа — из score.json)."""
    return (f"эталон из {res['total']} дефектов — полнота **{_pct(res['recall'])}** [{_range(*res['recall_ci'])}], "
            f"критичных и противоречий **{res['critical_found']} из {res['critical_total']}**; {precision_text(res)} "
            f"(`bench/score.json`, разметка — `bench/unmatched.md`)")


README_START, README_END = "<!-- gold:start -->", "<!-- gold:end -->"


def update_readme(res: dict, path: Path = ROOT / "README.md") -> int:
    """Заменить текст между метками gold:start / gold:end на readme_line(res). Возвращает число мест с метками."""
    t = path.read_text(encoding="utf-8")
    pat = re.compile(re.escape(README_START) + ".*?" + re.escape(README_END), re.S)
    new, n = pat.subn(lambda _: README_START + readme_line(res) + README_END, t)
    if n and new != t:
        path.write_text(new, encoding="utf-8")
    return n


def md(res: dict, label: str) -> str:
    ci = lambda c: f"[{_pct(c[0])}–{_pct(c[1])}]"  # noqa: E731
    d = res.get("disputed", 0)
    m = res.get("findings", res["judged"] + d + res["unjudged"])
    gold, manual = res.get("checked_gold", res["judged"]), res.get("checked_manual", 0)
    if res["unjudged"] or d:
        prec = f"| Точность | **от {_pct(res['precision_strict'])} до {_pct(res['precision'])}** (проверено не всё) | — |"
        f1 = f"| F1 | от {_pct(res.get('f1_strict', res['f1']))} до {_pct(res['f1'])} | — |"
    else:
        prec = f"| Точность | **{_pct(res['precision'])}** | {ci(res['precision_ci'])} |"
        f1 = f"| F1 | **{_pct(res['f1'])}** | — |"
    lines = ["## Единый замер: эталон из " + str(res["total"]) + " дефектов, 95 % интервалы", "",
             f"*Прогон:* {label}. Команда: `python bench/gold_score.py`. {res['method']}.", "",
             f"**Проверено {res['judged'] + d} из {m} существенных замечаний** (сверкой с эталоном — {gold}, вручную — "
             f"{manual}{f'; из них спорных — {d}' if d else ''}); не проверено {res['unjudged']}."
             + (" Пока проверено не всё (или есть спорные), точность — диапазон: нижняя граница считает непроверенные и "
                "спорные ложными, верхняя — учитывает только проверенные с ответом «настоящий» / «ложное»."
                if res["unjudged"] or d else "")
             + " Разметка — `bench/unmatched.md`.", "",
             "| Метрика | Значение | 95 % интервал |", "|---|---|---|",
             f"| Полнота | **{_pct(res['recall'])}** ({res['found']} из {res['total']}) | {ci(res['recall_ci'])} |",
             prec,
             f"| Точность по проверенным ({res['judged']}) | {_pct(res['precision'])} | {ci(res['precision_ci'])} |",
             f"| Точность строгая (непроверенные {res['unjudged']} и спорные {d} — как ложные) | "
             f"{_pct(res['precision_strict'])} | — |",
             f1,
             f"| Критичные и противоречия | {res['critical_found']} из {res['critical_total']} | — |", "",
             "| Документ | Найдено |", "|---|---|"]
    for doc, (f, t) in res["by_doc"].items():
        lines.append(f"| {doc} | {f} из {t} |")
    return "\n".join(lines) + "\n"


def write_results(text: str, path: Path = HERE / "RESULTS.md") -> None:
    """Заменить раздел «## Единый замер…» в RESULTS.md (до следующего «## »), а если его нет — дописать в конец."""
    t = path.read_text(encoding="utf-8") if path.exists() else ""
    m = re.search(r"^## Единый замер.*?(?=^## |\Z)", t, re.S | re.M)
    if m:
        rest = t[m.end():]
        t = t[:m.start()] + text + ("\n" if rest else "") + rest
    else:
        t = t.rstrip("\n") + "\n\n" + text
    path.write_text(t, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python bench/gold_score.py")
    ap.add_argument("--detail", default=str(HERE / "results_detail.json"), help="построчные исходы bench/run.py")
    ap.add_argument("--real", default=str(ROOT / "reports" / "requirements-report.json"), help="отчёт по документу организаторов")
    ap.add_argument("--write", action="store_true",
                    help="обновить раздел в bench/RESULTS.md, сохранить bench/score.json и строку README")
    ap.add_argument("--readme", action="store_true", help="только обновить строку README по bench/score.json (без пересчёта)")
    ap.add_argument("--labels", nargs="+", metavar="LABELS.json",
                    help="перенести вердикты людей из файлов «Сохранить» bench/label_sheet.html (или bench/real/human_check.html)"
                         " в bench/unmatched.md / bench/real/human_check.md по ключу строки")
    ap.add_argument("--overwrite", action="store_true", help="с --labels: заменить уже вписанный другой вердикт")
    ap.add_argument("--force", action="store_true", help="с --labels: перенести, даже если все метки одинаковые")
    a = ap.parse_args(argv)
    if a.labels:
        from label_sheet import apply_files

        return apply_files([Path(x) for x in a.labels], overwrite=a.overwrite, force=a.force)
    if a.readme:
        res = json.loads((HERE / "score.json").read_text(encoding="utf-8"))
        n = update_readme(res)
        print(readme_line(res))
        print(f"README: мест с метками — {n}")
        return 0
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
        write_results(text)
        print(f"README: мест с метками — {update_readme(res)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
