"""Сравнение ReqLens с «голой» моделью: та же модель, один простой промпт на весь документ.

Запуск:  python bench/baseline_eval.py --env <путь к .env>     — прогон «голой» модели (≈ 1 запрос на документ),
                                                                 оценка и раздел в bench/RESULTS.md
         python bench/baseline_eval.py --no-model             — пересчитать без модели (B — по bench/baseline/answers/)
         python bench/baseline_eval.py --env <.env> --refresh — заново спросить модель (≈ 6 запросов)

Что сравнивается на одних и тех же документах и одним и тем же кодом оценки:
  A. ReqLens без модели (LLM_PROVIDER=rules) — считается заново, бесплатно;
  B. «Голая» модель — один запрос: текст документа + список критериев → JSON со списком дефектов. Без нарезки,
     правил, проверки цитат, критика и базы знаний. Промпт — bench/baseline/prompt.md (ничего не скрыто);
  C. ReqLens полностью — сохранённые результаты: bench/results.json (бенчмарк) и reports/requirements-report.json
     (документ организаторов). Модель для B берётся та же, что записана в C.
Бенчмарк оценивается функцией bench/run.py::evaluate (recall по внедрённым дефектам, ложные существенные замечания к
заведомо чистым требованиям), документ организаторов — bench/real_eval.py::evaluate (26 дефектов). Дополнительно для
B считается доля дословных цитат: сколько процитированных моделью фрагментов действительно есть в документе
(у ReqLens это 100 % по построению — цитата без совпадения отбрасывается).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

PROMPT = HERE / "baseline" / "prompt.md"
OUT = HERE / "baseline" / "results.json"
ANSWERS = HERE / "baseline" / "answers"  # сырые ответы «голой» модели + модель, которая ответила
SECTION = "## Сравнение с «голой» моделью"
DOCS = ("payments", "credit", "onboarding", "deposit_kk", "cards")  # документы сохранённого результата ReqLens


def _norm_id(s: str) -> str:
    return re.sub(r"[\s‐-―−_.]+", "-", str(s or "").strip().upper()).strip("-")


def load_prompt() -> tuple[str, str]:
    text = PROMPT.read_text(encoding="utf-8")
    system = text.split("## Системный промпт", 1)[1].split("## Запрос", 1)[0].strip().strip("`").strip()
    user = text.split("## Запрос", 1)[1].strip().strip("`").strip()
    return system, user


def ask(llm, doc_text: str) -> list[dict]:
    from req_review.criteria import INDIVIDUAL, SET

    system, user = load_prompt()
    crit = "\n".join(f"- {k}: {v[0]}" for k, v in {**INDIVIDUAL, **SET}.items())
    data = llm.generate_json(system.replace("{criteria}", crit), user.replace("{document}", doc_text), task="baseline")
    items = data.get("defects") if isinstance(data, dict) else data
    return [x for x in (items or []) if isinstance(x, dict)]


def as_review(defects: list[dict], known_ids: set[str]):
    """Ответ модели → объект с интерфейсом ReviewResult, который понимает bench/run.py::evaluate."""
    known = {_norm_id(i): i for i in known_ids}
    reqs: dict[str, SimpleNamespace] = {}
    sets = []

    def rr(i):
        doc_id = known.get(_norm_id(i), str(i))
        if doc_id not in reqs:
            reqs[doc_id] = SimpleNamespace(req=SimpleNamespace(doc_id=doc_id, rid=doc_id), findings=[])
        return reqs[doc_id]

    for d in defects:
        ids = [i for i in (d.get("ids") or []) if str(i).strip()]
        f = SimpleNamespace(criterion=str(d.get("criterion", "")), severity=str(d.get("severity", "major")).lower(),
                            quote=str(d.get("quote", "")), problem=str(d.get("problem", "")), fix=str(d.get("fix", "")))
        if f.severity not in ("critical", "major", "minor"):
            f.severity = "major"
        if len(ids) == 1:
            rr(ids[0]).findings.append(f)
        elif ids:
            for i in ids:
                rr(i)
            sets.append(SimpleNamespace(criterion=f.criterion, severity=f.severity, problem=f.problem, fix=f.fix,
                                        refs=[SimpleNamespace(req_id=rr(i).req.rid, quote=f.quote) for i in ids]))
        else:
            sets.append(SimpleNamespace(criterion=f.criterion, severity=f.severity, problem=f.problem, fix=f.fix, refs=[]))
    return SimpleNamespace(req_results=list(reqs.values()), set_findings=sets)


def quote_rate(defects: list[dict], text: str) -> tuple[int, int]:
    from req_review.verify import quote_in

    qs = [str(d.get("quote") or "") for d in defects if str(d.get("quote") or "").strip()]
    return sum(1 for q in qs if quote_in(q, text)), len(qs)


def as_report_json(rv) -> dict:
    """Объект ревью → минимальный report.json для bench/real_eval.py::evaluate (тексты проблемы и рекомендации)."""
    return {"requirements": [{"findings": [{"problem": f.problem, "fix": f.fix} for f in rr.findings]}
                             for rr in rv.req_results],
            "set_findings": [{"problem": f.problem, "fix": f.fix} for f in rv.set_findings]}


def _model_of(label: str) -> str:
    m = re.search(r"gemini-[\w.\-]+", label or "")
    return m.group(0) if m else ""


def run(use_model: bool, env: str | None, refresh: bool = False) -> dict:
    import real_eval
    from dotenv import load_dotenv
    from run import evaluate, summarize

    from req_review.pipeline import Options, review_document
    from req_review.reader import read_document

    if env:
        load_dotenv(env)
    truth = json.loads((HERE / "ground_truth.json").read_text(encoding="utf-8"))["documents"]
    saved = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    final = json.loads((ROOT / "reports" / "requirements-report.json").read_text(encoding="utf-8"))
    res = {"docs": list(DOCS), "A_rules": {}, "B_bare": {}, "C_reqlens": {}}

    # A. ReqLens без модели
    os.environ["LLM_PROVIDER"] = "rules"
    from req_review.llm import build_llm_from_env

    rules = build_llm_from_env()
    parts = []
    for name in DOCS:
        rv = review_document(ROOT / truth[name]["file"], rules, Options(domain="none", critic=False), log=lambda m: None)
        parts.append(evaluate(rv, truth[name], name))
    res["A_rules"]["bench"] = _short(summarize(parts))
    rv = review_document(ROOT / "bench" / "real" / "notifications.md", rules, Options(critic=False), log=lambda m: None)
    res["A_rules"]["organizers"] = _real(real_eval.evaluate(as_report_json(rv)))

    # C. ReqLens полностью — сохранённые прогоны
    res["C_reqlens"]["bench"] = {**_short(saved), "model": saved.get("label", ""), "version": saved.get("version", "")}
    res["C_reqlens"]["organizers"] = {**_real(real_eval.evaluate(final)), "model": final["passport"]["model"],
                                      "version": final["passport"].get("agent_version", "")}
    res["C_reqlens"]["quotes"] = "100 % (цитата без совпадения с документом отбрасывается кодом)"

    # B. «Голая» модель — та же модель, что в C. Ответы сохраняются в bench/baseline/answers/<документ>.json вместе с
    # моделью, которая ответила на самом деле (при исчерпании квоты агент переключается на резервную); пересчёт идёт по
    # этим файлам без обращений к модели, --refresh — свежий прогон.
    b_parts, q_ok, q_all, calls, models = [], 0, 0, 0, {}
    for scope, model, docs in (("bench", _model_of(saved.get("label", "")), DOCS),
                               ("organizers", _model_of(final["passport"]["model"]), ("organizers",))):
        llm = None
        for name in docs:
            path = ROOT / "bench" / "real" / "notifications.md" if name == "organizers" else ROOT / truth[name]["file"]
            doc = read_document(path)
            ans = ANSWERS / f"{name}.json"
            if ans.exists() and not refresh:
                saved_ans = json.loads(ans.read_text(encoding="utf-8"))
            elif use_model:
                if llm is None:
                    os.environ.update(LLM_PROVIDER="gemini", GEMINI_MODEL=model, LLM_CACHE="refresh")
                    llm = build_llm_from_env()
                print(f"[B] {name}: {llm.model} …", flush=True)
                defects = ask(llm, doc.text)
                saved_ans = {"document": name, "model": llm.model, "requested_model": model, "defects": defects}
                ANSWERS.mkdir(parents=True, exist_ok=True)
                ans.write_text(json.dumps(saved_ans, ensure_ascii=False, indent=1), encoding="utf-8")
            else:
                continue
            defects, models[name] = saved_ans["defects"], saved_ans["model"]
            ok, n = quote_rate(defects, doc.text)
            q_ok, q_all = q_ok + ok, q_all + n
            if name == "organizers":
                res["B_bare"]["organizers"] = {**_real(real_eval.evaluate(as_report_json(as_review(defects, set())))),
                                               "model": saved_ans["model"], "defects": len(defects),
                                               "quotes_verbatim": [ok, n]}
            else:
                t = truth[name]
                known = {i for d in t["defects"] for i in d["ids"]} | set(t["clean_ids"])
                p = evaluate(as_review(defects, known), t, name)
                p["quotes"] = [ok, n]
                b_parts.append(p)
        if llm is not None:
            calls += llm.stats.calls
        if scope == "bench" and len(b_parts) == len(DOCS):
            s = _short(summarize(b_parts))
            s["quotes_verbatim"] = [sum(p["quotes"][0] for p in b_parts), sum(p["quotes"][1] for p in b_parts)]
            res["B_bare"]["bench"] = {**s, "model": _models_label({k: v for k, v in models.items() if k in DOCS})}
    if models:
        res["B_bare"].update(quotes_verbatim=[q_ok, q_all], calls=calls, models=models)
    return res


def _models_label(models: dict) -> str:
    """{документ: модель} → «gemini-3.1-flash-lite (credit, cards); gemini-3.5-flash-lite (payments)»."""
    by: dict[str, list[str]] = {}
    for doc, m in models.items():
        by.setdefault(m, []).append(doc)
    if len(by) == 1:
        return next(iter(by))
    return "; ".join(f"{m} ({', '.join(d)})" for m, d in sorted(by.items()))


def _short(s: dict) -> dict:
    return {k: s.get(k) for k in ("recall", "precision", "f1", "tp", "total", "fp_on_clean", "clean", "cases")}


def _real(e: dict) -> dict:
    return {k: e[k] for k in ("found", "total", "critical_found", "critical_total", "findings")}


def section(res: dict) -> str:
    pct = lambda x: "—" if x is None else f"{round(100 * x)} %"  # noqa: E731
    a, b, c = res["A_rules"], res.get("B_bare") or {}, res["C_reqlens"]
    L = [SECTION, "",
         "Одни и те же документы, один и тот же код оценки. **A** — ReqLens без модели (только правила). **B** — «голая» "
         "модель: тот же Gemini, один запрос «вот документ и критерии — верни список дефектов» (промпт целиком — "
         "`bench/baseline/prompt.md`), без нарезки, правил, проверки цитат, критика и базы знаний. **C** — ReqLens "
         "полностью (сохранённые прогоны: `bench/results.json`, `reports/requirements-report.json`). Для B модель та же, "
         "что записана в C. Пересчёт: `python bench/baseline_eval.py`.", ""]
    bb, ab, cb = b.get("bench") or {}, a["bench"], c["bench"]
    L += [f"**Бенчмарк** ({len(res['docs'])} документов, {cb.get('total')} внедрённых дефектов, "
          f"{cb.get('clean')} заведомо чистых требований)", "",
          "| | A. Только правила | B. «Голая» модель | C. ReqLens |", "|---|---|---|---|",
          f"| Recall (найдено дефектов) | {pct(ab['recall'])} ({ab['tp']} из {ab['total']}) | "
          + (f"{pct(bb['recall'])} ({bb['tp']} из {bb['total']})" if bb else "—")
          + f" | {pct(cb['recall'])} ({cb['tp']} из {cb['total']}) |",
          f"| Precision | {pct(ab['precision'])} | {pct(bb.get('precision'))} | {pct(cb['precision'])} |",
          f"| F1 | {pct(ab['f1'])} | {pct(bb.get('f1'))} | {pct(cb['f1'])} |",
          f"| Ложные существенные замечания к чистым требованиям | {ab['fp_on_clean']} | {bb.get('fp_on_clean', '—')} | "
          f"{cb['fp_on_clean']} |"]
    ao, bo, co = a["organizers"], b.get("organizers") or {}, c["organizers"]
    L += ["", "**Документ организаторов** (26 ожидаемых дефектов, из них 7 критичных; `bench/real/notifications.json`)", "",
          "| | A. Только правила | B. «Голая» модель | C. ReqLens |", "|---|---|---|---|",
          f"| Найдено дефектов | {ao['found']} из {ao['total']} | "
          + (f"{bo['found']} из {bo['total']}" if bo else "—") + f" | {co['found']} из {co['total']} |",
          f"| Из них критичных | {ao['critical_found']} из {ao['critical_total']} | "
          + (f"{bo['critical_found']} из {bo['critical_total']}" if bo else "—")
          + f" | {co['critical_found']} из {co['critical_total']} |",
          f"| Замечаний в отчёте | {ao['findings']} | {bo.get('findings', '—')} | {co['findings']} |"]
    qv = b.get("quotes_verbatim")
    L += ["", "**Дословность цитат**: у ReqLens 100 % — цитата, которой нет в документе, отбрасывается кодом. У «голой» "
          "модели " + (f"дословны {qv[0]} из {qv[1]} процитированных фрагментов ({round(100 * qv[0] / qv[1]) if qv[1] else 0} %); "
                       "остальные не совпадают с текстом документа, и найти их место в документе нельзя." if qv else "— (не запускалась)."),
          "", f"*Модели:* B — {bb.get('model', '—')} (бенчмарк), {bo.get('model', '—')} (документ организаторов); "
          f"C — {cb.get('model', '')}; {co.get('model', '')}. Оговорка: C на бенчмарке — сохранённый прогон версии "
          f"{cb.get('version', '')}; B и A — текущая версия кода.", "",
          "**Оговорки.** 1) Если квота основной модели кончилась, агент переходит на резервную — какая модель ответила "
          "на каждый документ, видно выше и в `bench/baseline/answers/*.json`; для честного сравнения на одной модели — "
          "`python bench/baseline_eval.py --env <.env> --refresh`, когда квота обновится. 2) На документе организаторов "
          "дефект засчитывается, если текст замечания подходит под регулярные выражения из `bench/real/notifications.json`; "
          "их составила команда, поэтому для чужих формулировок счёт может быть занижен. Сырые ответы «голой» модели лежат "
          "в `bench/baseline/answers/` — каждый может проверить их вручную. 3) Бенчмарк размечен командой (см. "
          "`bench/external/PROTOCOL.md` и слепую оценку — для независимой проверки).", ""]
    return "\n".join(L)


def write_section(text: str) -> None:
    p = HERE / "RESULTS.md"
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    if SECTION in old:
        start = old.index(SECTION)
        nxt = old.find("\n## ", start + len(SECTION))
        old = old[:start].rstrip() + "\n" + (old[nxt:] if nxt >= 0 else "")
    p.write_text(old.rstrip() + "\n\n" + text.rstrip() + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Сравнение ReqLens с «голой» моделью")
    ap.add_argument("--env", default=None, help="путь к .env с ключом Gemini")
    ap.add_argument("--no-model", action="store_true", help="не обращаться к модели (B — по сохранённым ответам)")
    ap.add_argument("--refresh", action="store_true", help="заново спросить модель, даже если ответы сохранены")
    a = ap.parse_args(argv)
    res = run(not a.no_model, a.env, a.refresh)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    text = section(res)
    write_section(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
