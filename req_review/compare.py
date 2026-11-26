"""Сравнение двух прогонов по report.json.

    python -m req_review.compare reports/v1.json reports/v2.json [--md reports/compare.md]

Без обращений к модели: дельта балла и готовности, исправленные / новые / ухудшившиеся требования,
снятые и появившиеся дефекты.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .exports import compare, summarize_for_compare

LAB = {"fixed": "✅ исправлено", "improved": "⬆️ улучшилось", "new": "⚠️ новое", "worse": "🔻 ухудшилось", "same": "без изменений"}


def _defects(data: dict) -> dict[tuple, dict]:
    """Ключ дефекта: ID требования в документе (или текст) + критерий — устойчив к перенумерации R-xxx."""
    out = {}
    for r in data["requirements"]:
        key_r = r.get("doc_id") or r["text"][:60]
        for f in r["findings"]:
            out[(key_r, f["criterion"])] = {"req": r.get("doc_id") or r["rid"], "criterion": f["criterion"],
                                            "severity": f["severity"], "quote": f.get("quote", "")}
    return out


def diff_reports(old: dict, new: dict) -> dict:
    res = compare(summarize_for_compare(old), summarize_for_compare(new))
    do, dn = _defects(old), _defects(new)
    res["defects_fixed"] = [do[k] for k in do if k not in dn]
    res["defects_new"] = [dn[k] for k in dn if k not in do]
    so, sn = old.get("scores", {}), new.get("scores", {})
    res["doc_score"] = {"before": so.get("document"), "after": sn.get("document")}
    res["readiness"] = {"before": so.get("readiness"), "after": sn.get("readiness")}
    crit = lambda d: sum(1 for r in d["requirements"] for f in r["findings"] if f["severity"] == "critical")  # noqa: E731
    res["critical"] = {"before": crit(old), "after": crit(new)}
    return res


def to_markdown(res: dict, old_name: str, new_name: str) -> str:
    d, rd, cr = res["doc_score"], res["readiness"], res["critical"]
    L = [f"# Сравнение прогонов: {old_name} → {new_name}", "",
         "| Показатель | Было | Стало |", "|---|---|---|",
         f"| Балл документа | {d['before']} | {d['after']} |",
         f"| Готовность к разработке, % | {rd['before']} | {rd['after']} |",
         f"| Критичных дефектов | {cr['before']} | {cr['after']} |", "",
         " · ".join(f"{LAB[k]}: {v}" for k, v in res["counts"].items()), ""]
    rows = [r for r in res["rows"] if r["status"] != "same"]
    if rows:
        L += ["| Требование | Статус | Балл было → стало |", "|---|---|---|"]
        for r in rows:
            name = r["rid"] + (f" ({r['doc_id']})" if r.get("doc_id") else "")
            before = r["before"] if r["before"] is not None else "—"
            L.append(f"| {name} | {LAB[r['status']]} | {before} → {r['after']} |")
        L.append("")
    for title, key in (("Снятые дефекты", "defects_fixed"), ("Новые дефекты", "defects_new")):
        if res[key]:
            L += [f"## {title} ({len(res[key])})", ""]
            L += [f"- {x['req']} · {x['criterion']} · {x['severity']}: «{x['quote']}»" for x in res[key]]
            L.append("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="python -m req_review.compare", description="Сравнение двух report.json")
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--md", help="сохранить сравнение в Markdown")
    a = ap.parse_args(argv)
    old = json.loads(Path(a.old).read_text(encoding="utf-8"))
    new = json.loads(Path(a.new).read_text(encoding="utf-8"))
    res = diff_reports(old, new)
    md = to_markdown(res, Path(a.old).name, Path(a.new).name)
    if a.md:
        Path(a.md).write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
