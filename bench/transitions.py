"""v13: реакция на исправления — исправили дефект, и замечание по нему исчезло, а новых ложных не появилось.

Запуск:  python bench/transitions.py --build   — собрать пары «до / после» в bench/transitions/ (без модели)
         python bench/transitions.py           — проверить пары агентом (модель из .env; «до» — из кэша бенчмарка)
         python bench/transitions.py --write   — то же + таблица в bench/RESULTS.md и bench/transitions.json

«До» — документ бенчмарка с внедрёнными дефектами (bench/out/<doc>_seeded.md). «После» — тот же документ, в котором
первые FIX_PER_DOC дефектов требований исправлены обратной заменой (исходная формулировка из bench/docs/<doc>.md);
остальные дефекты оставлены как есть — по ним видно, что агент не «замолкает» на всём документе.
Метрики: доля исправленных дефектов, по которым замечание исчезло; новые существенные замечания в «после» к
требованиям, у которых их не было в «до» (кандидаты в ложные); сохранились ли неисправленные дефекты.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "transitions"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

FIX_PER_DOC = 3
DOCS = ["payments", "credit", "onboarding", "deposit_kk", "cashback", "refinance", "qr", "fx"]  # Markdown-документы


def build() -> dict:
    """Пары «до / после» и список исправленных дефектов → bench/transitions/manifest.json."""
    from inject import DEFECTS, build_doc

    OUT.mkdir(exist_ok=True)
    manifest = {"fix_per_doc": FIX_PER_DOC, "docs": {}}
    for name in DOCS:
        before, truth = build_doc(name)
        after = before
        fixed = []
        for kind, rid, old, new, crit in DEFECTS[name][:FIX_PER_DOC]:
            line = next(ln for ln in after.splitlines() if f"**{rid}.**" in ln)
            assert new in line, (name, rid)
            after = after.replace(line, line.replace(new, old, 1), 1)
            fixed.append({"id": rid, "type": kind, "criteria": crit})
        kept = [d for d in truth["defects"] if d["level"] == "requirement" and d["ids"][0] not in {f["id"] for f in fixed}]
        (OUT / f"{name}_after.md").write_text(after, encoding="utf-8")
        manifest["docs"][name] = {"before": f"bench/out/{name}_seeded.md", "after": f"bench/transitions/{name}_after.md",
                                  "fixed": fixed, "kept": [{"id": d["ids"][0], "criteria": d["criteria"]} for d in kept]}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def _flags(rv) -> dict[str, list]:
    return {rr.req.doc_id: [f for f in rr.findings if f.severity != "minor"] for rr in rv.req_results if rr.req.doc_id}


def compare(before, after, fixed: list[dict], kept: list[dict]) -> dict:
    fb, fa = _flags(before), _flags(after)
    gone = [f["id"] for f in fixed if not any(g.criterion in f["criteria"] for g in fa.get(f["id"], []))]
    was_found = [f["id"] for f in fixed if any(g.criterion in f["criteria"] for g in fb.get(f["id"], []))]
    new_false = [rid for rid, fs in fa.items() if fs and not fb.get(rid) and rid not in {f["id"] for f in fixed}]
    new_on_fixed = [f["id"] for f in fixed if fa.get(f["id"]) and not any(g.criterion in f["criteria"] for g in fa[f["id"]])]
    kept_found = [k["id"] for k in kept if any(g.criterion in k["criteria"] for g in fa.get(k["id"], []))]
    return {"fixed": len(fixed), "was_found": len(was_found), "gone": len(gone),
            "gone_of_found": sum(1 for x in gone if x in was_found), "new_false": new_false, "new_on_fixed": new_on_fixed,
            "kept": len(kept), "kept_found": len(kept_found)}


def run(manifest: dict, llm, profile: str = "fast") -> dict:
    from req_review.pipeline import Options, review_document

    per = {}
    for name, m in manifest["docs"].items():
        o = Options(profile=profile, domain="none")
        b = review_document(ROOT / m["before"], llm, o, log=lambda x: None)
        a = review_document(ROOT / m["after"], llm, o, log=lambda x: None)
        per[name] = compare(b, a, m["fixed"], m["kept"])
    tot = {k: sum(p[k] for p in per.values()) for k in ("fixed", "was_found", "gone", "gone_of_found", "kept", "kept_found")}
    tot["new_false"] = sum(len(p["new_false"]) for p in per.values())
    tot["new_on_fixed"] = sum(len(p["new_on_fixed"]) for p in per.values())
    tot["docs"] = len(per)
    return {"total": tot, "per_doc": per, "model": llm.label}


def md(res: dict) -> str:
    t = res["total"]
    pct = lambda a, b: f"{100 * a / b:.0f} %" if b else "—"  # noqa: E731
    lines = ["## Реакция на исправления (v13)", "", f"*Модель:* {res['model']}. Команда: `python bench/transitions.py`.", "",
             "| Метрика | Значение |", "|---|---|",
             f"| Исправлено дефектов (по {FIX_PER_DOC} в {t['docs']} документах) | {t['fixed']} |",
             f"| Замечание исчезло после исправления | **{t['gone_of_found']} из {t['was_found']}** найденных «до» "
             f"({pct(t['gone_of_found'], t['was_found'])}) |",
             f"| Новые существенные замечания к другим требованиям (кандидаты в ложные) | {t['new_false']} "
             f"({t['new_false'] / max(1, t['docs']):.1f} на документ) |",
             f"| Новое замечание к исправленному требованию по другому критерию | {t['new_on_fixed']} |",
             f"| Неисправленные дефекты по-прежнему найдены | {t['kept_found']} из {t['kept']} |", "",
             "| Документ | Исчезло | Новые к другим | Неисправленные найдены |", "|---|---|---|---|"]
    for d, p in res["per_doc"].items():
        lines.append(f"| {d} | {p['gone_of_found']} из {p['was_found']} | {len(p['new_false'])} | {p['kept_found']} из {p['kept']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse

    from dotenv import load_dotenv

    ap = argparse.ArgumentParser(prog="python bench/transitions.py")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--profile", default="fast")
    a = ap.parse_args(argv)
    manifest = build()
    if a.build:
        print(f"пары собраны: {OUT.relative_to(ROOT)} ({sum(len(m['fixed']) for m in manifest['docs'].values())} исправлений)")
        return 0
    load_dotenv(ROOT / ".env")
    from req_review.llm import build_llm_from_env

    res = run(manifest, build_llm_from_env(), a.profile)
    text = md(res)
    print(text)
    if a.write:
        (HERE / "transitions.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        with open(HERE / "RESULTS.md", "a", encoding="utf-8") as fh:
            fh.write("\n" + text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
