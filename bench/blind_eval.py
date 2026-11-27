"""Слепая оценка: документы, написанные не командой, и ключ дефектов от их автора (правила — bench/blind/README.md).

Запуск:  python bench/blind_eval.py                       — прогнать агента по документам с ключом и напечатать таблицу
         python bench/blind_eval.py --results             — то же + раздел «Слепые документы» в bench/RESULTS.md
         python bench/blind_eval.py --reports reports/blind   — оценить готовые отчёты <имя>.json без нового прогона
         python bench/blind_eval.py --docs DIR --keys DIR — свои папки документов и ключей
Ключ — формат bench/real/notifications.json; совпадение ищется функцией evaluate() из bench/real_eval.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from real_eval import evaluate  # noqa: E402

DOC_EXT = (".md", ".txt", ".docx", ".pdf")
SECTION = "## Слепые документы (bench/blind_eval.py)"


def pairs(docs: Path, keys: Path) -> list[tuple[Path, Path]]:
    """Документы, для которых есть ключ: <имя>.<ext> ↔ keys/<имя>.json."""
    out = []
    for p in sorted(docs.iterdir()) if docs.exists() else []:
        if p.suffix.lower() in DOC_EXT and p.name.lower() != "readme.md" and (keys / f"{p.stem}.json").exists():
            out.append((p, keys / f"{p.stem}.json"))
    return out


def run_agent(doc: Path, out_dir: Path, profile: str) -> dict:
    from dotenv import load_dotenv

    from req_review.pipeline import ROOT, Options, run

    load_dotenv(ROOT / ".env")
    out = out_dir / f"{doc.stem}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    run(str(doc), str(out), Options(profile=profile, xlsx=False, jira=False, pdf=False), log=lambda m: None)
    return json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))


def table(results: list[tuple[str, dict, dict]]) -> list[str]:
    lines = ["| Документ | Найдено | Критичных | Замечаний агента | Не найдено |", "|---|---|---|---|---|"]
    tf = tt = cf = ct = 0
    for name, key, r in results:
        miss = ", ".join(f"{x['id']} {x['title']}" for x in r["rows"] if not x["found"]) or "—"
        lines.append(f"| {key.get('title') or name} | {r['found']} из {r['total']} ({round(100 * r['recall'])} %) | "
                     f"{r['critical_found']} из {r['critical_total']} | {r['findings']} | {miss} |")
        tf, tt, cf, ct = tf + r["found"], tt + r["total"], cf + r["critical_found"], ct + r["critical_total"]
    if len(results) > 1:
        lines.append(f"| **Итого** | **{tf} из {tt}** ({round(100 * tf / max(1, tt))} %) | **{cf} из {ct}** | | |")
    return lines


def write_section(results: list[tuple[str, dict, dict]], path: Path) -> None:
    """Раздел «Слепые документы» в RESULTS.md: заменяет прежний, остальной файл не трогает."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if SECTION in text:
        i = text.index(SECTION)
        j = text.find("\n## ", i + len(SECTION))
        text = text[:i].rstrip() + "\n" + (text[j:] if j >= 0 else "")
    first = results[0][2] if results else {}
    lines = ["", SECTION, "",
             f"*Дата:* {datetime.now():%Y-%m-%d %H:%M} · *модель:* {first.get('model', '—')} · *агент:* {first.get('version', '—')}.",
             "Документы и ключи дефектов подготовлены вне команды; агент на них не настраивался (правила — "
             "`bench/blind/README.md`). Совпадение — по тексту проблемы и рекомендации замечания.", ""]
    lines += table(results) + [""]
    path.write_text(text.rstrip() + "\n" + "\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python bench/blind_eval.py", description="Слепая оценка ReqLens")
    ap.add_argument("--docs", default=str(HERE / "blind"), help="папка документов (по умолчанию bench/blind)")
    ap.add_argument("--keys", default=None, help="папка ключей (по умолчанию <docs>/keys)")
    ap.add_argument("--reports", default=None, help="готовые отчёты <имя>.json — без нового прогона")
    ap.add_argument("--out", default=None, help="куда писать отчёты прогона (по умолчанию reports/blind)")
    ap.add_argument("--profile", default="deep")
    ap.add_argument("--results", nargs="?", const=str(HERE / "RESULTS.md"), default=None,
                    help="записать раздел «Слепые документы» (по умолчанию в bench/RESULTS.md)")
    a = ap.parse_args(argv)
    docs = Path(a.docs)
    keys = Path(a.keys) if a.keys else docs / "keys"
    todo = pairs(docs, keys)
    if not todo:
        print(f"Нет документов с ключом: документы — {docs}, ключи — {keys}/<имя>.json. Правила — bench/blind/README.md.")
        return 2
    results = []
    for doc, key_path in todo:
        key = json.loads(key_path.read_text(encoding="utf-8"))
        if a.reports:
            rp = Path(a.reports) / f"{doc.stem}.json"
            if not rp.exists():
                print(f"{doc.name}: нет отчёта {rp} — пропущен")
                continue
            report = json.loads(rp.read_text(encoding="utf-8"))
        else:
            report = run_agent(doc, Path(a.out) if a.out else HERE.parent / "reports" / "blind", a.profile)
        r = evaluate(report, key)
        results.append((doc.stem, key, r))
        print(f"{doc.name}: {r['found']}/{r['total']} ({round(100 * r['recall'])} %), критичных "
              f"{r['critical_found']}/{r['critical_total']}, замечаний {r['findings']} · {r['model']}")
    if not results:
        return 2
    print()
    print("\n".join(table(results)))
    if a.results:
        write_section(results, Path(a.results))
        print(f"\nРаздел «Слепые документы» → {a.results}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
