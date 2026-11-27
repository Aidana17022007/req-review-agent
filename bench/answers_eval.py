"""v14: ответы аналитика, написанные не командой, → проверка, верно ли ReqLens определил тип каждого ответа.

Запуск:  python bench/answers_eval.py --template examples/answers/external/answers_template.md
             — шаблон ответов (все вопросы с метками) из отчёта для сдачи reports/requirements-report.json
         python bench/answers_eval.py --report reports/answers_ext/report.json --key examples/answers/external/key.json
             [--md examples/answers/external/RESULTS.md]
             — сравнить answers.items прогона `--answers` с ключом автора ответов: {"Q-xx": "concrete|evasive|contradictory"}

Ответ сопоставляется с ключом по номеру вопроса в файле ответов (answers.items[].answer_qid): в новом прогоне
вопросы перенумерованы, ответ находит свой вопрос по метке или по похожему вопросу (req_review/answers.py::_resolve).
«Не сопоставлен» — ответ, для которого в новом прогоне не нашлось вопроса: он считается ошибкой определения.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

TYPE_RU = {"concrete": "конкретный", "evasive": "уклончивый", "contradictory": "противоречивый"}


def build_template(report: Path, out: Path) -> int:
    from req_review.answers import question_options, template_md

    d = json.loads(report.read_text(encoding="utf-8"))
    qs = [NS(qid=q["qid"], ref=q["ref"], section=q["section"], rid=q.get("rid") or q["ref"], criterion=q["criterion"],
             text=q["text"], closes=q.get("closes", []), refs=q.get("refs", [])) for q in d.get("questions", [])]
    set_values = {f"S-{i:02d}": [str(v.get("value", "")) for v in (f.get("values") or []) if v.get("value")]
                  for i, f in enumerate(d.get("set_findings", []), 1) if f.get("values")}
    title = d.get("passport", {}).get("document", "") or "документ"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(template_md(qs, title, question_options(qs, d.get("decisions") or [], set_values)), encoding="utf-8")
    print(f"шаблон: {len(qs)} вопросов → {out}")
    return 0


def evaluate(report: dict, key: dict) -> dict:
    ans = report.get("answers") or {}
    by_src = {it.get("answer_qid") or it["qid"]: it for it in ans.get("items", [])}
    rows = []
    for qid, want in key.items():
        it = by_src.get(qid)
        got = it["type"] if it else ""
        rows.append({"qid": qid, "want": want, "got": got, "ok": got == want, "run_qid": it["qid"] if it else "",
                     "matched_by": (it or {}).get("matched_by", ""), "closes": (it or {}).get("closes", [])})
    summ = ans.get("summary") or {}
    return {"rows": rows, "total": len(rows), "ok": sum(r["ok"] for r in rows),
            "matched": sum(bool(r["run_qid"]) for r in rows),
            "by_type": {t: [sum(r["ok"] for r in rows if r["want"] == t), sum(r["want"] == t for r in rows)] for t in TYPE_RU},
            "fuzzy": sum(r["matched_by"] == "похожий вопрос" for r in rows),
            "blockers": summ.get("blockers") or summ.get("closed_blockers"), "summary": summ,
            "before": ans.get("before", {}), "after": ans.get("after", {}),
            "model": report.get("passport", {}).get("model", ""), "calls": report.get("passport", {}).get("calls")}


def to_md(r: dict) -> list[str]:
    bt = r["by_type"]
    L = ["| Показатель | Значение |", "|---|---|",
         f"| Тип ответа определён верно | **{r['ok']} из {r['total']}** ({round(100 * r['ok'] / max(1, r['total']))} %) |",
         f"| Конкретных / уклончивых / противоречивых | {bt['concrete'][0]} из {bt['concrete'][1]} / "
         f"{bt['evasive'][0]} из {bt['evasive'][1]} / **{bt['contradictory'][0]} из {bt['contradictory'][1]}** |",
         f"| Ответов сопоставлено с вопросами нового прогона | {r['matched']} из {r['total']} (по похожему вопросу — {r['fuzzy']}) |"]
    b, a = r["before"], r["after"]
    if b and a:
        L.append(f"| Критичных замечаний до → после | {b.get('critical')} → {a.get('critical')} |")
    L += ["", "| Q (файл ответов) | Задуманный тип | Определено | Вопрос прогона | Как сопоставлен | Закрыто |",
          "|---|---|---|---|---|---|"]
    L += [f"| {x['qid']} | {TYPE_RU.get(x['want'], x['want'])} | {('✅ ' if x['ok'] else '❌ ') + TYPE_RU.get(x['got'], x['got'] or 'не сопоставлен')} | "
          f"{x['run_qid'] or '—'} | {x['matched_by'] or '—'} | {', '.join(x['closes']) or '—'} |" for x in r["rows"]]
    return L


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python bench/answers_eval.py", description=__doc__.split("\n")[0])
    ap.add_argument("--template", help="записать шаблон ответов из отчёта для сдачи")
    ap.add_argument("--source", default=str(ROOT / "reports" / "requirements-report.json"))
    ap.add_argument("--report", help="report.json прогона с --answers")
    ap.add_argument("--key", help="ключ автора ответов: {\"Q-xx\": тип}")
    ap.add_argument("--md", help="записать таблицу в Markdown")
    a = ap.parse_args(argv)
    if a.template:
        return build_template(Path(a.source), Path(a.template))
    if not (a.report and a.key):
        ap.print_help()
        return 2
    key = json.loads(Path(a.key).read_text(encoding="utf-8"))
    key = key.get("types", key)
    res = evaluate(json.loads(Path(a.report).read_text(encoding="utf-8")), key)
    md = to_md(res)
    print("\n".join(md))
    if a.md:
        Path(a.md).write_text("\n".join(md) + "\n", encoding="utf-8")
    Path(a.report).with_name("answers_eval.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
