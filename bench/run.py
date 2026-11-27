"""Бенчмарк точности агента на 5 документах с заранее известными дефектами (67): 3 на русском (Markdown),
онлайн-депозит на казахском языке и перевыпуск карты в DOCX с таблицами Word.

Запуск:  python bench/run.py                         (модель из .env — так получаются цифры для README и слайдов)
         LLM_PROVIDER=mock python bench/run.py       (офлайн: проверяет только словарный слой и пайплайн)
         python bench/run.py --save bench/baseline.json   (сохранить метрики как «было» для следующих прогонов)
Результат: bench/RESULTS.md, bench/results.html и bench/results.json (метрики по каждому документу и итог).
Если есть bench/baseline.json (или --baseline FILE), в RESULTS.md появляются колонки «было → стало».
Все числа вычисляются кодом по bench/ground_truth.json. Повторный прогон на той же модели берётся из кэша
ответов (.cache/llm) и не тратит квоту.
"""
from __future__ import annotations

import html
import json
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

KEEP_SECTIONS = ("## Реальный документ организаторов", "## Слепые документы", "## Сравнение с «голой» моделью")  # пишут real_eval.py и blind_eval.py
TYPE_RU = {"vague": "Размытые слова", "missing_units": "Нет значений / единиц", "open_list": "Открытое перечисление",
           "tbd": "TBD / не заполнено", "and_or": "«и/или»", "conditional": "Условность «при необходимости»",
           "design": "Проектное решение", "compound": "Составное требование", "subjective": "Субъективная оценка",
           "absolute": "Абсолютная формулировка", "vague_goal": "Цель без механизма", "passive": "Пассив без субъекта",
           "contradiction": "Противоречие", "duplicate": "Дубль"}
DOC_RU = {"refinance": "Рефинансирование", "qr": "Оплата по QR", "fx": "Обмен валют",
          "payments": "Оплата услуг", "credit": "Онлайн-кредит", "onboarding": "Открытие счёта",
          "deposit_kk": "Онлайн-депозит (қазақ тілі)", "cards": "Перевыпуск карты (DOCX, таблицы)"}


def _prf(tp: int, total: int, tpf: int, fp: int) -> dict:
    r = tp / total if total else 0
    p = tpf / (tpf + fp) if (tpf + fp) else 1.0
    return {"recall": r, "precision": p, "f1": 2 * p * r / (p + r) if p + r else 0, "tp": tp, "total": total, "fp": fp}


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
    # v13: каждое существенное/критичное замечание с исходом — для бутстрепа и ручной разметки несовпавших (score.py)
    set_hit = set()
    for d in truth["defects"]:
        if d["level"] == "set":
            want = set(d["ids"])
            set_hit |= {id(f) for f in rv.set_findings
                        if f.criterion in d["criteria"] and want <= {rid2doc.get(r.req_id) for r in f.refs}}
    items = []
    for rr in rv.req_results:
        for f in rr.findings:
            if f.severity == "minor":
                continue
            out = "tp" if id(f) in tp_ids else "fp" if rr.req.doc_id in clean else "unmatched"
            items.append({"where": rr.req.doc_id or rr.req.rid, "criterion": f.criterion, "severity": f.severity,
                          "quote": f.quote, "problem": f.problem, "outcome": out})
    for f in rv.set_findings:
        if f.severity == "minor":
            continue
        items.append({"where": ", ".join(sorted({rid2doc.get(r.req_id) or r.req_id for r in f.refs})), "criterion": f.criterion,
                      "severity": f.severity, "quote": " / ".join(r.quote for r in f.refs)[:200], "problem": f.problem,
                      "outcome": "tp" if id(f) in set_hit else "unmatched"})
    return {"rows": rows, "fp": fp, "tp_findings": tp_f, "clean": len(clean), "doc": doc, "items": items}


def summarize(parts: list[dict]) -> dict:
    rows = [r for p in parts for r in p["rows"]]
    tp = sum(r["found"] for r in rows)
    fp = sum(p["fp"] for p in parts)
    tpf = sum(p["tp_findings"] for p in parts)
    recall = tp / len(rows) if rows else 0
    precision = tpf / (tpf + fp) if (tpf + fp) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    cases = {p["doc"]: _prf(sum(r["found"] for r in p["rows"]), len(p["rows"]), p["tp_findings"], p["fp"]) for p in parts}
    by_type = defaultdict(lambda: [0, 0])
    by_doc = defaultdict(lambda: [0, 0])
    for r in rows:
        by_type[r["type"]][0] += r["found"]
        by_type[r["type"]][1] += 1
        by_doc[r["doc"]][0] += r["found"]
        by_doc[r["doc"]][1] += 1
    return {"rows": rows, "tp": tp, "total": len(rows), "recall": recall, "precision": precision, "f1": f1,
            "fp_on_clean": fp, "clean": sum(p["clean"] for p in parts), "by_type": dict(by_type), "by_doc": dict(by_doc),
            "cases": cases, "docs": len(parts), "parts": parts}


def write_results(res: dict, label: str, version: str, base: dict | None = None) -> None:
    pct = lambda x: f"{round(100 * x)} %"  # noqa: E731
    lines = [
        "# Бенчмарк точности ReqLens", "",
        f"*Модель:* {label} · *агент:* {version} · *дата:* {datetime.now():%Y-%m-%d %H:%M}", "",
        f"{res['docs']} вымышленных документов (`bench/docs/`: на русском, 1 на казахском, 1 DOCX с таблицами) "
        f"с **{res['total']} заранее известными дефектами** (`bench/inject.py`). "
        "Recall — доля внедрённых дефектов, найденных агентом по нужному критерию. Precision — доля верных замечаний среди",
        "существенных и критичных замечаний к дефектным и заведомо чистым требованиям (замечания к чистым требованиям считаются ложными).",
        "Замечания, не совпавшие с эталоном, в Precision не входят — точность с проверкой каждого замечания и диапазоном",
        "«проверено N из M» — в разделе «Единый замер» (`python bench/gold_score.py`).", "",
        "| Метрика | Значение |", "|---|---|",
        f"| Recall | **{pct(res['recall'])}** ({res['tp']} из {res['total']}) |",
        f"| Precision | **{pct(res['precision'])}** |",
        f"| F1 | **{pct(res['f1'])}** |",
        f"| Ложные существенные замечания к {res['clean']} чистым требованиям | {res['fp_on_clean']} |", "",
        "## По типам дефектов", "", "| Тип дефекта | Найдено | Recall |", "|---|---|---|",
    ]
    for t, (f, n) in sorted(res["by_type"].items(), key=lambda x: -x[1][0] / x[1][1]):
        lines.append(f"| {TYPE_RU.get(t, t)} | {f} из {n} | {pct(f / n)} |")
    bc = (base or {}).get("cases", {})
    was = (lambda d, k: f"{pct(bc[d][k])} → " if d in bc else "")  # noqa: E731
    lines += ["", "## По документам", ""]
    if base:
        lines += [f"Было — {base.get('label', 'базовый прогон')} ({base.get('version', '')}); стало — этот прогон.", ""]
    lines += ["| Документ | Найдено | Recall | Precision | Ложные к чистым |", "|---|---|---|---|---|"]
    for d, c in res["cases"].items():
        lines.append(f"| {DOC_RU.get(d, d)} | {c['tp']} из {c['total']} | {was(d, 'recall')}**{pct(c['recall'])}** | "
                     f"{was(d, 'precision')}**{pct(c['precision'])}** | {c['fp']} |")
    if base:
        lines.append(f"| **Итого** | {res['tp']} из {res['total']} | {pct(base['recall'])} → **{pct(res['recall'])}** | "
                     f"{pct(base['precision'])} → **{pct(res['precision'])}** | {res['fp_on_clean']} |")
    lines += ["", "## Все дефекты", "", "| Документ | Тип | Требования | Найден |", "|---|---|---|---|"]
    for r in res["rows"]:
        lines.append(f"| {DOC_RU.get(r['doc'], r['doc'])} | {TYPE_RU.get(r['type'], r['type'])} | {', '.join(r['ids'])} | "
                     f"{'✅' if r['found'] else '❌'} |")
    if "mock" in label:
        lines += ["", "> ⚠️ Прогон в режиме mock: модель не вызывалась, работают только словарные правила, детектор числовых "
                      "противоречий и эвристики. Для итоговых цифр запустите `python bench/run.py` с ключом модели."]
    old = (HERE / "RESULTS.md").read_text(encoding="utf-8") if (HERE / "RESULTS.md").exists() else ""
    keep = [old.index(h) for h in KEEP_SECTIONS if h in old]  # разделы real_eval.py и blind_eval.py не теряются
    tail = ("\n" + old[min(keep):].rstrip() + "\n") if keep else ""
    (HERE / "RESULTS.md").write_text("\n".join(lines) + "\n" + tail, encoding="utf-8")

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
<p class="muted" style="margin-bottom:24px">{{ res.docs }} документов · {{ res.total }} заранее известных дефектов · {{ res.clean }} заведомо чистых требований</p>
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


def run_once(truth: dict, llm, rag: str, profile: str = "fast", only: list[str] | None = None) -> dict:
    import os

    os.environ["RAG"] = rag
    parts = []
    for name, t in truth["documents"].items():
        if only and name not in only:
            continue
        path = ROOT / t.get("file", f"bench/out/{name}_seeded.md")
        print(f"[{name}] RAG={rag}: проверка {path.relative_to(ROOT)}")
        rv = review_document(path, llm, Options(profile=profile, domain="none"), log=lambda m: print("   " + m))
        parts.append(evaluate(rv, t, name))
        parts[-1]["basis"] = sum(1 for rr in rv.req_results for f in rr.findings if getattr(f, "basis", None))
    res = summarize(parts)
    res["basis"] = sum(p["basis"] for p in parts)
    return res


def main(argv: list[str] | None = None):
    import argparse

    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="python bench/run.py")
    ap.add_argument("--rag", choices=["on", "off", "both"], default="on",
                    help="с базой знаний (on), без неё (off) или сравнить оба режима (both)")
    ap.add_argument("--profile", default="fast", help="профиль проверки (fast — по умолчанию, deep — финальный)")
    ap.add_argument("--only", nargs="*", help="проверить только эти документы (payments credit onboarding deposit_kk cards)")
    ap.add_argument("--baseline", help="метрики «было» (по умолчанию bench/baseline.json, если есть)")
    ap.add_argument("--save", help="сохранить метрики этого прогона как базовые (например, bench/baseline.json)")
    a = ap.parse_args(argv)
    load_dotenv(ROOT / ".env")
    from inject import build_all

    truth = build_all()
    llm = build_llm_from_env()
    modes = ["off", "on"] if a.rag == "both" else [a.rag]
    results = {m: run_once(truth, llm, m, a.profile, a.only) for m in modes}
    res = results[modes[-1]]
    label = llm.label + f" · RAG={modes[-1]} · профиль {a.profile}"
    if llm.stats.switches:
        label += " · переключения: " + "; ".join(llm.stats.switches)
    bpath = Path(a.baseline) if a.baseline else HERE / "baseline.json"
    base = json.loads(bpath.read_text(encoding="utf-8")) if bpath.exists() and not a.save else None
    write_results(res, label, agent_version(), base)
    summary = {"label": label, "version": agent_version(), "date": f"{datetime.now():%Y-%m-%d %H:%M}",
               **{k: res[k] for k in ("recall", "precision", "f1", "tp", "total", "fp_on_clean", "clean", "cases")}}
    (HERE / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    # v13: построчные исходы (каждый дефект и каждое замечание) — вход для bench/score.py (интервалы, разметка)
    detail = {"label": label, "version": agent_version(), "rows": res["rows"],
              "items": [{**i, "doc": p["doc"]} for p in res["parts"] for i in p["items"]]}
    (HERE / "results_detail.json").write_text(json.dumps(detail, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.save:
        Path(a.save).write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.rag == "both":
        off, on = results["off"], results["on"]
        pct = lambda x: f"{round(100 * x)} %"  # noqa: E731
        extra = ["", "## С базой знаний и без", "", "| Метрика | Без RAG | С базой знаний (RAG) |", "|---|---|---|",
                 f"| Recall | {pct(off['recall'])} | {pct(on['recall'])} |",
                 f"| Precision | {pct(off['precision'])} | {pct(on['precision'])} |",
                 f"| F1 | {pct(off['f1'])} | {pct(on['f1'])} |",
                 f"| Замечаний с основанием из kb/ | {off['basis']} | {on['basis']} |", "",
                 "RAG не меняет сами замечания на коротких документах (контекст — полный текст); он добавляет основания "
                 "(пункт стандарта / норма РК) и шаблоны правок, а на длинных документах сокращает запросы."]
        with open(HERE / "RESULTS.md", "a", encoding="utf-8") as fh:
            fh.write("\n".join(extra) + "\n")
    print(f"Recall {res['recall']:.0%} ({res['tp']}/{res['total']}) · Precision {res['precision']:.0%} · F1 {res['f1']:.0%} "
          f"→ bench/RESULTS.md, bench/results.html · обращений к модели: {llm.stats.calls}, из кэша: {llm.stats.cached}")


if __name__ == "__main__":
    main()
