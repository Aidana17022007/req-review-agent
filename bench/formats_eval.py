"""v13+ A9: тот же документ в MD, DOCX и PDF — агент должен находить одно и то же.

Запуск:  python bench/formats_eval.py [--profile fast] [--limit N] [--write]
Документы: документ организаторов и варианты корпуса мутаций (bench/mutations/, python bench/mutate.py --build).
DOCX и PDF собираются из того же Markdown (bench/real/formats.py: таблицы Word / таблицы reportlab с кириллицей) во
временную папку. Метрика: разница числа замечаний между форматами (цель ≤ 1) и найден ли заложенный дефект в каждом
формате (строгий счёт bench/mutate.py::found).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "real"))


def _count(rv) -> int:
    return sum(len(rr.findings) for rr in rv.req_results) + len(rv.set_findings)


def evaluate(items: list[tuple[str, Path, list]], llm, profile: str = "fast", log=print) -> dict:
    from formats import to_docx, to_pdf
    from mutate import found

    from req_review.pipeline import Options, review_document

    rows = []
    with tempfile.TemporaryDirectory() as td:
        for name, md_path, defects in items:
            md = md_path.read_text(encoding="utf-8")
            paths = {"md": md_path, "docx": to_docx(Path(td) / f"{md_path.stem}.docx", md),
                     "pdf": to_pdf(Path(td) / f"{md_path.stem}.pdf", md)}
            res = {}
            for fmt, p in paths.items():
                rv = review_document(p, llm, Options(profile=profile, domain="fintech"), log=lambda m: None)
                res[fmt] = {"findings": _count(rv), "requirements": len(rv.req_results),
                            "defects_found": sum(found(rv, d) for d in defects)}
            spread = max(r["findings"] for r in res.values()) - min(r["findings"] for r in res.values())
            rows.append({"doc": name, "formats": res, "spread": spread, "defects": len(defects)})
            log(f"{name}: " + " · ".join(f"{k} {v['findings']} зам., дефект {v['defects_found']}/{len(defects)}"
                                         for k, v in res.items()) + f" · разброс {spread}")
    return {"model": getattr(llm, "label", ""), "profile": profile, "docs": len(rows),
            "max_spread": max((r["spread"] for r in rows), default=0),
            "within_1": sum(r["spread"] <= 1 for r in rows), "rows": rows}


def md(res: dict) -> str:
    lines = [f"## Форматы MD / DOCX / PDF (v13+, профиль {res['profile']})", "",
             f"*Модель:* {res['model']}. Команда: `python bench/formats_eval.py`.", "",
             f"Разница числа замечаний между форматами ≤ 1: **{res['within_1']} из {res['docs']}** документов "
             f"(максимум {res['max_spread']}).", "",
             "| Документ | MD | DOCX | PDF | Разброс |", "|---|---|---|---|---|"]
    for r in res["rows"]:
        f = r["formats"]
        cell = lambda k: f"{f[k]['findings']}" + (f" · дефект {f[k]['defects_found']}/{r['defects']}" if r["defects"] else "")  # noqa: E731
        lines.append(f"| {r['doc']} | {cell('md')} | {cell('docx')} | {cell('pdf')} | {r['spread']} |")
    return "\n".join(lines) + "\n"


def items(limit: int | None = None) -> list[tuple[str, Path, list]]:
    out = [("документ организаторов", HERE / "real" / "notifications.md", [])]
    man = HERE / "mutations" / "manifest.json"
    if man.exists():
        for v in json.loads(man.read_text(encoding="utf-8"))["variants"]:
            out.append((v["name"], ROOT / v["file"], v["defects"]))
    return out[: limit] if limit else out


def main(argv: list[str] | None = None) -> int:
    import argparse

    from dotenv import load_dotenv

    ap = argparse.ArgumentParser(prog="python bench/formats_eval.py")
    ap.add_argument("--profile", default="fast")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    load_dotenv(ROOT / ".env")
    from req_review.llm import build_llm_from_env

    res = evaluate(items(a.limit), build_llm_from_env(), a.profile)
    text = md(res)
    print(text)
    if a.write:
        (HERE / f"formats_{a.profile}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        with open(HERE / "RESULTS.md", "a", encoding="utf-8") as fh:
            fh.write("\n" + text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
