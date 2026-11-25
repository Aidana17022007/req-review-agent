"""Бенчмарк точности агента на документе с заранее известными дефектами.

Запуск:  python bench/run.py            (модель из .env — так получаются цифры для README)
         LLM_PROVIDER=mock python bench/run.py   (офлайн: проверяет только словарный слой и пайплайн)
Результат: bench/RESULTS.md и bench/results.html. Все числа вычисляются кодом по ground_truth.json.
"""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from dotenv import load_dotenv  # noqa: E402

from req_review.llm import build_llm_from_env  # noqa: E402
from req_review.pipeline import ROOT, Options, agent_version, review_document  # noqa: E402

TYPE_RU = {"vague": "Размытые слова", "missing_units": "Нет единиц/значений", "open_list": "Открытое перечисление",
           "tbd": "TBD / не заполнено", "and_or": "«и/или»", "conditional": "Условность «при необходимости»",
           "design": "Проектное решение", "compound": "Составное требование", "subjective": "Субъективная оценка",
           "absolute": "Абсолютная формулировка", "contradiction": "Противоречие", "duplicate": "Дубль"}


def evaluate(rv, truth) -> dict:
    by_doc = {rr.req.doc_id: rr for rr in rv.req_results}
    rid2doc = {rr.req.rid: rr.req.doc_id for rr in rv.req_results}
    rows, tp_findings = [], set()
    for d in truth["defects"]:
        found = False
        if d["level"] == "requirement":
            rr = by_doc.get(d["ids"][0])
            hits = [f for f in (rr.findings if rr else []) if f.criterion in d["criteria"]]
            found = bool(hits)
            tp_findings |= {id(f) for f in hits}
        else:
            want = set(d["ids"])
            for f in rv.set_findings:
                got = {rid2doc.get(r.req_id) for r in f.refs}
                if f.criterion in d["criteria"] and want <= got:
                    found = True
            # дубль/противоречие также засчитываются, если найдены на уровне требования с упоминанием второго ID
        rows.append({**d, "found": found})
    seeded_ids = {i for d in truth["defects"] if d["level"] == "requirement" for i in d["ids"]}
    clean = set(truth["clean_ids"])
    fp = sum(1 for rr in rv.req_results if rr.req.doc_id in clean for f in rr.findings if f.severity != "minor")
    tp_major = sum(1 for rr in rv.req_results if rr.req.doc_id in seeded_ids for f in rr.findings if id(f) in tp_findings)
    tp = sum(1 for r in rows if r["found"])
    recall = tp / len(rows) if rows else 0
    precision = tp_major / (tp_major + fp) if (tp_major + fp) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    return {"rows": rows, "recall": recall, "precision": precision, "f1": f1, "tp": tp, "total": len(rows),
            "fp_on_clean": fp, "clean": len(clean)}


def write_results(res: dict, label: str, version: str) -> None:
    pct = lambda x: f"{round(100 * x)} %"
    lines = [
        "# Бенчмарк точности ReqLens", "",
        f"*Модель:* {label} · *агент:* {version} · *дата:* {datetime.now():%Y-%m-%d %H:%M}", "",
        "Документ `bench/seeded.md` — вымышленный документ с **заранее известными** дефектами (`bench/inject.py`).",
        "Recall — доля внедрённых дефектов, найденных агентом по нужному критерию. Precision — доля верных замечаний среди",
        "существенных и критичных замечаний к дефектным и заведомо чистым требованиям (замечания к чистым требованиям считаются ложными).", "",
        "| Метрика | Значение |", "|---|---|",
        f"| Recall | **{pct(res['recall'])}** ({res['tp']} из {res['total']}) |",
        f"| Precision | **{pct(res['precision'])}** |",
        f"| F1 | **{pct(res['f1'])}** |",
        f"| Ложные существенные замечания к {res['clean']} чистым требованиям | {res['fp_on_clean']} |", "",
        "| Тип дефекта | Требования | Найден |", "|---|---|---|",
    ]
    for r in res["rows"]:
        lines.append(f"| {TYPE_RU.get(r['type'], r['type'])} | {', '.join(r['ids'])} | {'✅' if r['found'] else '❌'} |")
    if "mock" in label:
        lines += ["", "> ⚠️ Прогон в режиме mock: модель не вызывалась, работают только словарные правила и эвристики. "
                      "Для итоговых цифр запустите `python bench/run.py` с ключом Gemini."]
    (HERE / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    from req_review.ui import env

    tpl = env().from_string(HTML)
    (HERE / "results.html").write_text(tpl.render(res=res, label=label, version=version, types=TYPE_RU,
                                                  pct=pct, esc=html.escape), encoding="utf-8")


HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ReqLens · Бенчмарк</title><style>{{ tokens_css()|safe }}{{ asset("base.css")|safe }}</style></head><body>
<header class="topbar"><div class="container"><div class="logo"><span class="logo-mark">{{ icon("lens", 18) }}</span>ReqLens<small>Бенчмарк точности</small></div></div></header>
<main class="container" style="padding:40px 24px">
<div class="caption">{{ label }} · {{ version }}</div><h1 class="display" style="margin:8px 0 24px">Насколько точен агент</h1>
<div class="grid g-4" style="margin-bottom:32px">
 <div class="stat"><div class="caption">Recall</div><div class="v" style="color:var(--ok)">{{ pct(res.recall) }}</div></div>
 <div class="stat"><div class="caption">Precision</div><div class="v">{{ pct(res.precision) }}</div></div>
 <div class="stat"><div class="caption">F1</div><div class="v">{{ pct(res.f1) }}</div></div>
 <div class="stat"><div class="caption">Найдено</div><div class="v">{{ res.tp }}<small>из {{ res.total }}</small></div></div></div>
<div class="card">{% for r in res.rows %}<div class="bar-row"><span class="small">{{ types.get(r.type, r.type) }} <span class="faint">· {{ r.ids|join(", ") }}</span></span>
 <div class="bar"><i style="width:{{ 100 if r.found else 4 }}%;background:{{ 'var(--ok-accent)' if r.found else '#E5484D' }}"></i></div>
 <b class="small">{{ "✓" if r.found else "✗" }}</b></div>{% endfor %}</div>
{% if "mock" in label %}<div class="banner-mock">Режим mock: работают только словарные правила. Итоговые цифры — с моделью.</div>{% endif %}
</main></body></html>"""


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    load_dotenv(ROOT / ".env")
    from inject import build  # noqa: E402

    text, truth = build()
    (HERE / "seeded.md").write_text(text, encoding="utf-8")
    (HERE / "ground_truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    llm = build_llm_from_env()
    rv = review_document(HERE / "seeded.md", llm, Options(profile="fast", domain="none"), log=lambda m: print("  " + m))
    res = evaluate(rv, truth)
    write_results(res, llm.label, agent_version())
    print(f"Recall {res['recall']:.0%} · Precision {res['precision']:.0%} · F1 {res['f1']:.0%} → bench/RESULTS.md, bench/results.html")


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
