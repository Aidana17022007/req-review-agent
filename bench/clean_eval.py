"""v13+: ложные тревоги на чистых ТЗ — сколько замечаний агент даёт там, где дефектов нет.

Запуск:  python bench/clean_eval.py [--profile fast|deep] [--write]
Документы: bench/clean/*.md (8 полных чистых ТЗ: переводы, кредит, перевыпуск карты, кэшбэк, уведомления о расходах,
API оплаты, открытие счёта, депозит на казахском) и их перефразы bench/clean/paraphrased/ (python bench/clean/paraphrase.py).
Почему в каждом нет дефекта — bench/clean/README.md. Цель: 0 критичных, вердикт «можно» или «с оговорками» (не «нельзя»),
существенных ≤ 2 на документ. Каждое существенное и критичное замечание печатается с источником (правило / модель /
проход) — для разбора: ложное правило сужается, тест не трогается.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))


def docs() -> list[Path]:
    base = sorted(p for p in (HERE / "clean").glob("*.md") if p.name != "README.md")
    para = sorted((HERE / "clean" / "paraphrased").glob("*.md"))
    return base + para


def evaluate(paths: list[Path], llm, profile: str = "fast", log=print) -> dict:
    from req_review.pipeline import Options, review_document

    rows = []
    for p in paths:
        rv = review_document(p, llm, Options(profile=profile, domain="fintech"), log=lambda m: None)
        fs = [(f, rr.req.doc_id or rr.req.rid) for rr in rv.req_results for f in rr.findings] + \
             [(f, "набор") for f in rv.set_findings]
        c = Counter(f.severity for f, _ in fs)
        bad = [{"where": w, "severity": f.severity, "criterion": f.criterion, "source": f.source, "problem": f.problem[:240]}
               for f, w in fs if f.severity != "minor"]
        name = ("перефраз: " if p.parent.name == "paraphrased" else "") + p.stem
        rows.append({"doc": name, "critical": c["critical"], "major": c["major"], "minor": c["minor"],
                     "verdict": (rv.depth or {}).get("verdict", {}).get("development", ""), "requirements": len(rv.req_results),
                     "flagged": bad})
        log(f"{name}: критичных {c['critical']}, существенных {c['major']}, незначительных {c['minor']}, "
            f"вердикт {rows[-1]['verdict']}")
        for b in bad:
            log(f"    [{b['severity']}] {b['where']} · {b['source']} · {b['problem'][:160]}")
    n = len(rows)
    tot = {"docs": n, "critical": sum(r["critical"] for r in rows), "major": sum(r["major"] for r in rows),
           "minor": sum(r["minor"] for r in rows), "verdict_no": sum(r["verdict"] == "нельзя" for r in rows),
           "major_per_doc": round(sum(r["major"] for r in rows) / n, 2) if n else 0,
           "max_major": max((r["major"] for r in rows), default=0)}
    tot["goal_met"] = tot["critical"] == 0 and tot["verdict_no"] == 0 and tot["max_major"] <= 2
    return {"model": getattr(llm, "label", ""), "profile": profile, "total": tot, "rows": rows}


def md(res: dict) -> str:
    t = res["total"]
    lines = [f"## Чистые ТЗ — ложные тревоги (v13+, профиль {res['profile']})", "",
             f"*Модель:* {res['model']}. Команда: `python bench/clean_eval.py --profile {res['profile']}`. "
             "Почему в документах нет дефектов — `bench/clean/README.md`.", "",
             f"Итого на {t['docs']} документах: критичных **{t['critical']}**, существенных **{t['major']}** "
             f"({t['major_per_doc']} на документ, максимум {t['max_major']}), вердикт «нельзя» — **{t['verdict_no']} из "
             f"{t['docs']}**. Цель (0 критичных, не «нельзя», существенных ≤ 2): **{'достигнута' if t['goal_met'] else 'не достигнута'}**.",
             "", "| Документ | Требований | Критичных | Существенных | Незначительных | Вердикт |", "|---|---|---|---|---|---|"]
    for r in res["rows"]:
        lines.append(f"| {r['doc']} | {r['requirements']} | {r['critical']} | {r['major']} | {r['minor']} | {r['verdict']} |")
    flagged = [(r["doc"], b) for r in res["rows"] for b in r["flagged"]]
    if flagged:
        lines += ["", "Существенные и критичные замечания на чистых ТЗ (разбор):", ""]
        lines += [f"- {d} · {b['where']} · {b['severity']} · {b['source']}: {b['problem'][:200]}" for d, b in flagged]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse

    from dotenv import load_dotenv

    ap = argparse.ArgumentParser(prog="python bench/clean_eval.py")
    ap.add_argument("--profile", default="fast")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    load_dotenv(ROOT / ".env")
    from req_review.llm import build_llm_from_env

    res = evaluate(docs(), build_llm_from_env(), a.profile)
    text = md(res)
    print(text)
    if a.write:
        (HERE / f"clean_{a.profile}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        with open(HERE / "RESULTS.md", "a", encoding="utf-8") as fh:
            fh.write("\n" + text)
    return 0 if res["total"]["goal_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
