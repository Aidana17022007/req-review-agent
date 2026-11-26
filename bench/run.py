"""Бенчмарк точности агента на 3 документах с заранее известными дефектами (≥ 40).

Запуск:  python bench/run.py                         (модель из .env — так получаются цифры для README и слайдов)
         LLM_PROVIDER=mock python bench/run.py       (офлайн: проверяет только словарный слой и пайплайн)
Результат: bench/RESULTS.md и bench/results.html. Все числа вычисляются кодом по bench/ground_truth.json.
Повторный прогон на той же модели берётся из кэша ответов (.cache/llm) и не тратит квоту.
"""
from __future__ import annotations

import html
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from dotenv import load_dotenv  # noqa: E402

from req_review.llm import build_llm_from_env  # noqa: E402
from req_review.pipeline import ROOT, Options, agent_version, review_document  # noqa: E402

TYPE_RU = {"vague": "Размытые слова", "missing_units": "Нет значений / единиц", "open_list": "Открытое перечисление",
           "tbd": "TBD / не заполнено", "and_or": "«и/или»", "conditional": "Условность «при необходимости»",
           "design": "Проектное решение", "compound": "Составное требование", "subjective": "Субъективная оценка",
           "absolute": "Абсолютная формулировка", "vague_goal": "Цель без механизма", "passive": "Пассив без субъекта",
           "contradiction": "Противоречие", "duplicate": "Дубль"}
DOC_RU = {"payments": "Оплата услуг", "credit": "Онлайн-кредит", "onboarding": "Открытие счёта"}


def evaluate(rv, truth: dict, doc: str) -> dict:
    """TP/FN по внедрённым дефектам и FP (существенные/критичные замечания к заведомо чистым требованиям)."""
    by_doc = {rr.req.doc_id: rr for rr in rv.req_results}
    rid2doc = {rr.req.rid: rr.req.doc_id for rr in rv.req_results}
    rows, tp_ids = [], set()
    for d in truth["defects"]:
        found = False
        if d["level"] == "requirement":
            rr = by_doc.get(d["ids"][0])
            hits = [f for f in (rr.findings if rr else []) if f.criterion in d["criteria"]]
            found = bool(hits)
            tp_ids |= {id(f) for f in hits}
        else:
            want = set(d["ids"])
            found = any(f.criterion in d["criteria"] and want <= {rid2doc.get(r.req_id) for r in f.refs} for f in rv.set_findings)
        rows.append({**d, "doc": doc, "found": found})
    seeded = {i for d in truth["defects"] if d["level"] == "requirement" for i in d["ids"]}
    clean = set(truth["clean_ids"])
    fp = sum(1 for rr in rv.req_results if rr.req.doc_id in clean for f in rr.findings if f.severity != "minor")
    tp_f = sum(1 for rr in rv.req_results if rr.req.doc_id in seeded for f in rr.findings if id(f) in tp_ids)
    return {"rows": rows, "fp": fp, "tp_findings": tp_f, "clean": len(clean)}


def summarize(parts: list[dict]) -> dict:
    rows = [r for p in parts for r in p["rows"]]
    tp = sum(r["found"] for r in rows)
    fp = sum(p["fp"] for p in parts)
    tpf = sum(p["tp_findings"] for p in parts)
    recall = tp / len(rows) if rows else 0
    precision = tpf / (tpf + fp) if (tpf + fp) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    by_type = defaultdict(lambda: [0, 0])
    by_doc = defaultdict(lambda: [0, 0])
    for r in rows:
        by_type[r["type"]][0] += r["found"]
        by_type[r["type"]][1] += 1
        by_doc[r["doc"]][0] += r["found"]
        by_doc[r["doc"]][1] += 1
    return {"rows": rows, "tp": tp, "total": len(rows), "recall": recall, "precision": precision, "f1": f1,
            "fp_on_clean": fp, "clean": sum(p["clean"] for p in parts), "by_type": dict(by_type), "by_doc": dict(by_doc)}


def write_results(res: dict, label: str, version: str) -> None:
    pct = lambda x: f"{round(100 * x)} %"  # noqa: E731
    lines = [
        "# Бенчмарк точности ReqLens", "",
        f"*Модель:* {label} · *агент:* {version} · *дата:* {datetime.now():%Y-%m-%d %H:%M}", "",
        f"3 вымышленных документа (`bench/docs/`) с **{res['total']} заранее известными дефектами** (`bench/inject.py`). "
        "Recall — доля внедрённых дефектов, найденных агентом по нужному критерию. Precision — доля верных замечаний среди",
        "существенных и критичных замечаний к дефектным и заведомо чистым требованиям (замечания к чистым требованиям считаются ложными).", "",
        "| Метрика | Значение |", "|---|---|",
        f"| Recall | **{pct(res['recall'])}** ({res['tp']} из {res['total']}) |",
        f"| Precision | **{pct(res['precision'])}** |",
        f"| F1 | **{pct(res['f1'])}** |",
        f"| Ложные существенные замечания к {res['clean']} чистым требованиям | {res['fp_on_clean']} |", "",
        "## По типам дефектов", "", "| Тип дефекта | Найдено | Recall |", "|---|---|---|",
    ]
    for t, (f, n) in sorted(res["by_type"].items(), key=lambda x: -x[1][0] / x[1][1]):
        lines.append(f"| {TYPE_RU.get(t, t)} | {f} из {n} | {pct(f / n)} |")
    lines += ["", "## По документам", "", "| Документ | Найдено |", "|---|---|"]
    for d, (f, n) in res["by_doc"].items():
        lines.append(f"| {DOC_RU.get(d, d)} | {f} из {n} |")
    lines += ["", "## Все дефекты", "", "| Документ | Тип | Требования | Найден |", "|---|---|---|---|"]
    for r in res["rows"]:
        lines.append(f"| {DOC_RU.get(r['doc'], r['doc'])} | {TYPE_RU.get(r['type'], r['type'])} | {', '.join(r['ids'])} | "
                     f"{'✅' if r['found'] else '❌'} |")
    if "mock" in label:
        lines += ["", "> ⚠️ Прогон в режиме mock: модель не вызывалась, работают только словарные правила, детектор числовых "
                      "противоречий и эвристики. Для итоговых цифр запустите `python bench/run.py` с ключом модели."]
    (HERE / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    from req_review.ui import env

    tpl = env().from_string(HTML)
    types = sorted(res["by_type"].items(), key=lambda x: -x[1][0] / x[1][1])
    (HERE / "results.html").write_text(tpl.render(res=res, label=label, version=version, types=types, TYPE_RU=TYPE_RU,
                                                  DOC_RU=DOC_RU, pct=pct, esc=html.escape), encoding="utf-8")


HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ReqLens · Бенчмарк</title><style>{{ tokens_css()|safe }}{{ asset("base.css")|safe }}
.wrap-b{max-width:1100px;margin:0 auto;padding:24px}.tr{display:grid;grid-template-columns:220px 1fr 90px;gap:12px;align-items:center;margin:10px 0}
@media (max-width:640px){.tr{grid-template-columns:1fr 70px}.tr .bar{grid-column:1/-1}}</style></head><body>
<header class="pagebar"><div class="logo"><span class="logo-mark">{{ icon("lens", 18) }}</span><span>ReqLens<small>Бенчмарк точности</small></span></div></header>
<main class="wrap-b">
<div class="caption">{{ label }} · {{ version }}</div><h1 class="display" style="margin:8px 0 6px">Насколько точен агент</h1>
<p class="muted" style="margin-bottom:24px">3 документа · {{ res.total }} заранее известных дефектов · {{ res.clean }} заведомо чистых требований</p>
<div class="grid g-4" style="margin-bottom:24px">
 <article class="kpi kpi-hero"><span class="lbl">Recall</span><div class="kpi-num">{{ pct(res.recall) }}</div><div class="sub">найдено {{ res.tp }} из {{ res.total }}</div></article>
 <article class="kpi"><span class="lbl">Precision</span><div class="kpi-num">{{ pct(res.precision) }}</div><div class="sub">доля верных существенных замечаний</div></article>
 <article class="kpi"><span class="lbl">F1</span><div class="kpi-num">{{ pct(res.f1) }}</div><div class="sub">гармоническое среднее</div></article>
 <article class="kpi"><span class="lbl">Ложные срабатывания</span><div class="kpi-num">{{ res.fp_on_clean }}</div><div class="sub">на {{ res.clean }} чистых требованиях</div></article></div>
<div class="grid g-2" style="align-items:start">
<div class="card"><div class="card-title"><span class="h2">По типам дефектов</span></div>
{% for t, fn in types %}<div class="tr"><span class="small">{{ TYPE_RU.get(t, t) }}</span><div class="bar"><i style="width:{{ (100 * fn[0] / fn[1])|round }}%;background:{{ 'var(--ok-accent)' if fn[0] == fn[1] else 'var(--major-accent)' if fn[0] else 'var(--critical-accent)' }}"></i></div>
<b class="small" style="text-align:right">{{ fn[0] }} из {{ fn[1] }}</b></div>{% endfor %}</div>
<div class="card"><div class="card-title"><span class="h2">Все дефекты</span></div>
<div class="table-wrap"><table class="tbl"><thead><tr><th>Документ</th><th>Тип</th><th>Требования</th><th>Найден</th></tr></thead><tbody>
{% for r in res.rows %}<tr><td class="small">{{ DOC_RU.get(r.doc, r.doc) }}</td><td class="small">{{ TYPE_RU.get(r.type, r.type) }}</td><td class="small">{{ r.ids|join(", ") }}</td>
<td>{% if r.found %}<span class="chip sev-ok">✓ да</span>{% else %}<span class="chip sev-critical">✕ нет</span>{% endif %}</td></tr>{% endfor %}
</tbody></table></div></div></div>
{% if "mock" in label %}<div class="banner-mock" style="margin-top:24px">Режим mock: работают только правила и эвристики. Итоговые цифры — после прогона на модели.</div>{% endif %}
</main></body></html>"""


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    load_dotenv(ROOT / ".env")
    from inject import build_all

    truth = build_all()
    llm = build_llm_from_env()
    parts = []
    for name, t in truth["documents"].items():
        print(f"[{name}] проверка bench/out/{name}_seeded.md")
        rv = review_document(HERE / "out" / f"{name}_seeded.md", llm, Options(profile="fast", domain="none"),
                             log=lambda m: print("   " + m))
        parts.append(evaluate(rv, t, name))
    res = summarize(parts)
    write_results(res, llm.label, agent_version())
    print(f"Recall {res['recall']:.0%} ({res['tp']}/{res['total']}) · Precision {res['precision']:.0%} · F1 {res['f1']:.0%} "
          f"→ bench/RESULTS.md, bench/results.html · обращений к модели: {llm.stats.calls}, из кэша: {llm.stats.cached}")


if __name__ == "__main__":
    main()
