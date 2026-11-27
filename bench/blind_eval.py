"""Слепая оценка: документы, написанные не командой, и ключ дефектов от их автора (правила — bench/blind/README.md).

Запуск:  python bench/blind_eval.py --env .env                  — прогнать ReqLens (deep) по документам с ключом
         python bench/blind_eval.py --env .env --mode baseline  — те же документы «голой» моделью (1 запрос на документ)
         python bench/blind_eval.py --mode rules                — те же документы только правилами (без модели)
         python bench/blind_eval.py --compare --results         — оценить сохранённые отчёты всех режимов и записать
                                                                  раздел «Слепые документы» в bench/RESULTS.md
         python bench/blind_eval.py --reports DIR               — оценить готовые отчёты DIR/<имя>.json без прогона
Документы — bench/blind/docs/, ключи — bench/blind/keys/<имя>.json, отчёты прогона — bench/blind/reports/<режим>/.

Два формата ключа:
  v14 — bench/external/annotations.template.json (строки, класс, серьёзность; + source и clean): оценка
        bench/external/score.py — по месту (±1 строка) и классу, без формулировок; 95 % интервалы бутстрепом;
  v9  — bench/real/notifications.json (регулярные выражения match): оценка bench/real_eval.py::evaluate.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from real_eval import evaluate  # noqa: E402

DOC_EXT = (".md", ".txt", ".docx", ".pdf")
SECTION = "## Слепые документы (bench/blind_eval.py)"
BLIND = HERE / "blind"
MODES = {"agent": "ReqLens (deep)", "baseline": "Голая модель (1 запрос)", "rules": "Только правила"}


def _ext_score():
    spec = importlib.util.spec_from_file_location("ext_score", HERE / "external" / "score.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pairs(docs: Path, keys: Path) -> list[tuple[Path, Path]]:
    """Документы, для которых есть ключ: <имя>.<ext> ↔ keys/<имя>.json."""
    out = []
    for p in sorted(docs.iterdir()) if docs.exists() else []:
        if p.suffix.lower() in DOC_EXT and p.name.lower() != "readme.md" and (keys / f"{p.stem}.json").exists():
            out.append((p, keys / f"{p.stem}.json"))
    return out


def is_annotation_key(key: dict) -> bool:
    """v14: ключ в формате внешней разметки — у дефектов есть строки и класс (а не регулярные выражения)."""
    ds = key.get("defects") or []
    return bool(ds) and all("lines" in d and "class" in d for d in ds)


def run_agent(doc: Path, out_dir: Path, profile: str) -> dict:
    from req_review.pipeline import Options, run

    out = out_dir / f"{doc.stem}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    run(str(doc), str(out), Options(profile=profile, xlsx=False, jira=False, pdf=False), log=lambda m: None)
    return json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))


def run_baseline(doc: Path, out_dir: Path) -> dict:
    """«Голая» модель: один запрос (bench/baseline/prompt.md) на весь текст документа → report.json-совместимый вид."""
    from baseline_eval import ask

    from req_review.llm import build_llm_from_env
    from req_review.reader import read_document
    from req_review.verify import quote_in

    d = read_document(doc)
    llm = build_llm_from_env()
    llm.fallback_models = []  # голая модель — та же, что у ReqLens в паспорте, без подмены
    defects = ask(llm, d.text)
    sev = lambda s: s if s in ("critical", "major", "minor") else "major"  # noqa: E731
    reqs = [{"rid": f"B-{i:02d}", "findings": [{"criterion": str(x.get("criterion", "")), "severity": sev(str(x.get("severity", "")).lower()),
                                                "quote": str(x.get("quote", "")), "problem": str(x.get("problem", "")),
                                                "fix": str(x.get("fix", ""))}]} for i, x in enumerate(defects, 1)]
    quotes = [f["quote"] for r in reqs for f in r["findings"] if f["quote"].strip()]
    rep = {"passport": {"model": llm.label, "agent_version": "голая модель (bench/baseline/prompt.md)", "profile": "baseline",
                        "calls": llm.stats.calls, "document": doc.name,
                        "quotes_verbatim": [sum(quote_in(q, d.text) for q in quotes), len(quotes)]},
           "requirements": reqs, "set_findings": []}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{doc.stem}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return rep


def run_mode(mode: str, doc: Path, out_dir: Path, profile: str) -> dict:
    if mode == "baseline":
        return run_baseline(doc, out_dir)
    if mode == "rules":
        old = os.environ.get("LLM_PROVIDER")
        os.environ["LLM_PROVIDER"] = "rules"
        try:
            return run_agent(doc, out_dir, profile)
        finally:
            os.environ.pop("LLM_PROVIDER", None) if old is None else os.environ.__setitem__("LLM_PROVIDER", old)
    return run_agent(doc, out_dir, profile)


def score_one(key: dict, report: dict) -> dict:
    if is_annotation_key(key):
        res = _ext_score().score(key, report)
        res["model"] = report.get("passport", {}).get("model", "")
        res["version"] = report.get("passport", {}).get("agent_version", "")
        return res
    return evaluate(report, key)


# ---------------------------------------------------------------- таблицы

def _pct(x) -> str:
    return "—" if x is None else f"{round(100 * x)} %"


def _ci(c) -> str:
    return "" if not c else f" [{round(100 * c[0])}–{round(100 * c[1])} %]"


def table(results: list[tuple[str, dict, dict]]) -> list[str]:
    """v9: таблица по документам для ключей с регулярными выражениями."""
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


def doc_table(results: list[tuple[str, dict, dict]]) -> list[str]:
    """v14: по документам (формат внешней разметки)."""
    L = ["| Документ | Формат | Найдено | Критичных | Чистых с замечаниями | Ложных к чистым (сущ.) | Замечаний | Пропуски |",
         "|---|---|---|---|---|---|---|---|"]
    for name, key, r in results:
        crit = r["by_severity"].get("critical", [0, 0])
        miss = "; ".join(f"стр. {','.join(map(str, x['lines']))} {x['class']}" for x in r["rows"] if not x["found"]) or "—"
        fmt = (key.get("format") or Path(key.get("document", name)).suffix.lstrip(".")).upper()
        lang = key.get("language", "")
        L.append(f"| {key.get('title') or name} | {fmt}{', ' + lang if lang else ''} | {r['found']} из {r['total']} | "
                 f"{crit[0]} из {crit[1]} | {r['clean_flagged']} из {r['clean_total']} | {r['false_clean']} "
                 f"({r['false_clean_significant']}) | {r['findings']} | {miss} |")
    return L


def compare_table(agg: dict[str, dict]) -> list[str]:
    modes = [m for m in MODES if m in agg]
    L = ["| Показатель | " + " | ".join(MODES[m] for m in modes) + " |", "|---" * (len(modes) + 1) + "|"]
    row = lambda name, f: L.append(f"| {name} | " + " | ".join(f(agg[m]) for m in modes) + " |")  # noqa: E731
    row("Найдено дефектов ключа", lambda a: f"**{a['found']} из {a['total']}** ({_pct(a['recall'])}){_ci(a['recall_ci'])}")
    row("Критичных", lambda a: f"{a['critical_found']} из {a['critical_total']}")
    row("Чистых требований с замечаниями", lambda a: f"{a['clean_flagged']} из {a['clean_total']}")
    row("Ложных замечаний к чистым (существенных)", lambda a: f"{a['false_clean']} ({a['false_clean_significant']})")
    row("Точность по размеченным", lambda a: f"{_pct(a['precision'])}{_ci(a['precision_ci'])}")
    row("Точность строгая (всё вне ключа — ложное)", lambda a: f"{_pct(a['precision_strict'])}{_ci(a['precision_strict_ci'])}")
    row("Замечаний всего", lambda a: str(a["findings"]))
    row("Запросов к модели", lambda a: str(a.get("calls", "—")))
    return L


def _keys_commit(keys: Path) -> str:
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%h %cd", "--date=format:%Y-%m-%d %H:%M", "--", str(keys)],
                             cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        return out or "—"
    except (OSError, subprocess.SubprocessError):
        return "—"


def _replace_section(text: str, head: str, body: list[str]) -> str:
    if head in text:
        i = text.index(head)
        j = text.find("\n## ", i + len(head))
        text = text[:i].rstrip() + "\n" + (text[j:] if j >= 0 else "")
    return text.rstrip() + "\n\n" + "\n".join([head, ""] + body) + "\n"


def write_section(results: list[tuple[str, dict, dict]], path: Path) -> None:
    """v9: раздел «Слепые документы» в RESULTS.md: заменяет прежний, остальной файл не трогает."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    first = results[0][2] if results else {}
    body = [f"*Дата:* {datetime.now():%Y-%m-%d %H:%M} · *модель:* {first.get('model', '—')} · *агент:* {first.get('version', '—')}.",
            "Документы и ключи дефектов подготовлены вне команды; агент на них не настраивался (правила — "
            "`bench/blind/README.md`). Совпадение — по тексту проблемы и рекомендации замечания.", ""] + table(results)
    path.write_text(_replace_section(text, SECTION, body), encoding="utf-8")


def write_compare(per_mode: dict[str, list], agg: dict[str, dict], keys: Path, path: Path, detail: Path) -> None:
    """v14: раздел «Слепые документы» — одна таблица сравнения режимов; по документам — в bench/blind/RESULTS.md."""
    a = per_mode.get("agent") or next(iter(per_mode.values()))
    model = a[0][2].get("model", "—") if a else "—"
    version = a[0][2].get("version", "—") if a else "—"
    author = (a[0][1].get("annotator") if a else "") or "—"
    body = [f"*Дата:* {datetime.now():%Y-%m-%d %H:%M} · *модель:* {model} · *агент:* {version} · профиль deep · "
            f"*ключи закоммичены до прогона:* {_keys_commit(keys)}.",
            "",
            f"Документы ({len(a)}: {', '.join(sorted({(k.get('format') or '').upper() or p for p, k, _ in a}))}) и ключи "
            f"дефектов написал **отдельный ИИ-агент**, которому не показывали код, промпты, словари, правила, bench/ и отчёты "
            f"ReqLens ({author}). Это не человек: независимая разметка человеком — задача F (`KIT_outside_reviewer.md`). "
            "После получения документов правила, промпты и словари не менялись; результат опубликован как есть. "
            "Оценка — `bench/external/score.py`: дефект найден, если цитата замечания лежит в отмеченных строках (±1) и "
            f"критерий совместим с классом дефекта; {agg[next(iter(agg))]['method']}. По документам — "
            "`bench/blind/RESULTS.md`.", ""] + compare_table(agg)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(_replace_section(text, SECTION, body), encoding="utf-8")
    D = ["# Слепые документы: по документам", "", "Сводная таблица и условия — раздел «Слепые документы» в "
         "`bench/RESULTS.md`. Ключи — `bench/blind/keys/`, отчёты прогона — `bench/blind/reports/<режим>/`.", ""]
    for m in MODES:
        if m in per_mode:
            D += [f"## {MODES[m]}", ""] + doc_table(per_mode[m]) + [""]
    if "agent" in per_mode:
        D += ["## Замечания ReqLens к чистым требованиям (кандидаты в ложные)", ""]
        for name, key, r in per_mode["agent"]:
            D += [f"- **{name}** · {f['id']} ({f['severity']}, {f['criterion']}): {f['problem']}"
                  for f in r["agent_only"] if f.get("on_clean")]
        D.append("")
    detail.write_text("\n".join(D), encoding="utf-8")


def compare(docs: Path, keys: Path, reports: Path) -> tuple[dict, dict]:
    sc = _ext_score()
    per_mode, agg = {}, {}
    for m in MODES:
        rs = []
        calls = 0
        for doc, kp in pairs(docs, keys):
            key = json.loads(kp.read_text(encoding="utf-8"))
            rp = reports / m / f"{doc.stem}.json"
            if not is_annotation_key(key) or not rp.exists():
                continue
            rep = json.loads(rp.read_text(encoding="utf-8"))
            calls += int(rep.get("passport", {}).get("calls") or 0)
            rs.append((doc.stem, key, score_one(key, rep)))
        if rs:
            per_mode[m] = rs
            agg[m] = {**sc.aggregate([r for _, _, r in rs]), "calls": calls, "model": rs[0][2].get("model", "")}
    return per_mode, agg


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python bench/blind_eval.py", description="Слепая оценка ReqLens")
    ap.add_argument("--docs", default=str(BLIND / "docs"), help="папка документов (по умолчанию bench/blind/docs)")
    ap.add_argument("--keys", default=None, help="папка ключей (по умолчанию <docs>/keys или bench/blind/keys)")
    ap.add_argument("--reports", default=None, help="готовые отчёты <имя>.json — без нового прогона")
    ap.add_argument("--out", default=None, help="куда писать отчёты прогона (по умолчанию bench/blind/reports/<режим>)")
    ap.add_argument("--mode", choices=list(MODES), default="agent")
    ap.add_argument("--profile", default="deep")
    ap.add_argument("--env", default=None, help="путь к .env с ключом модели (ключ не печатается)")
    ap.add_argument("--compare", action="store_true", help="оценить сохранённые отчёты всех режимов (без прогона)")
    ap.add_argument("--results", nargs="?", const=str(HERE / "RESULTS.md"), default=None,
                    help="записать раздел «Слепые документы» (по умолчанию в bench/RESULTS.md)")
    a = ap.parse_args(argv)
    from dotenv import load_dotenv

    load_dotenv(a.env or ROOT / ".env")
    docs = Path(a.docs)
    keys = Path(a.keys) if a.keys else (docs / "keys" if (docs / "keys").exists() else BLIND / "keys")
    todo = pairs(docs, keys)
    if not todo:
        print(f"Нет документов с ключом: документы — {docs}, ключи — {keys}/<имя>.json. Правила — bench/blind/README.md.")
        return 2
    if a.compare:
        reports = Path(a.reports) if a.reports else BLIND / "reports"
        per_mode, agg = compare(docs, keys, reports)
        if not agg:
            print("Нет сохранённых отчётов: сначала прогон --mode agent / baseline / rules.")
            return 2
        print("\n".join(compare_table(agg)))
        # итог рядом с отчётами: bench/blind/results.json и bench/blind/RESULTS.md (по документам)
        (reports.parent / "results.json").write_text(json.dumps(agg, ensure_ascii=False, indent=1), encoding="utf-8")
        if a.results:
            write_compare(per_mode, agg, keys, Path(a.results), reports.parent / "RESULTS.md")
            print(f"\nРаздел «Слепые документы» → {a.results}; по документам → {reports.parent / 'RESULTS.md'}")
        return 0
    out_dir = Path(a.out) if a.out else BLIND / "reports" / a.mode
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
            report = run_mode(a.mode, doc, out_dir, a.profile)
        r = score_one(key, report)
        results.append((doc.stem, key, r))
        crit = (f"{r['critical_found']}/{r['critical_total']}" if "critical_found" in r
                else "/".join(map(str, r["by_severity"].get("critical", [0, 0]))))
        print(f"{doc.name}: {r['found']}/{r['total']} ({round(100 * r['recall'])} %), критичных {crit}, "
              f"замечаний {r['findings']} · {r['model']}")
    if not results:
        return 2
    print()
    if all(is_annotation_key(k) for _, k, _ in results):
        print("\n".join(doc_table(results)))
    else:
        print("\n".join(table(results)))
        if a.results:
            write_section(results, Path(a.results))
            print(f"\nРаздел «Слепые документы» → {a.results}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
