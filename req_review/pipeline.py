"""Оркестрация прогона: используется и CLI, и веб-интерфейсом ReqLens Studio."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import __version__

ROOT = Path(__file__).resolve().parent.parent

PROFILES = {
    # fast — по умолчанию: минимум обращений к модели (бесплатный тариф)
    "fast": {"critic": False, "rescore": False},
    "full": {"critic": True, "rescore": True},
    "offline": {"critic": True, "rescore": False},
    # deep — для финального отчёта: малые пакеты (6 требований — модель внимательнее к каждому), критик на все
    # замечания (дубли, калибровка), повторная проверка исправленного документа
    # v6: + узкие проходы (по одному классу дефектов на запрос) и самосогласованность (повторная проверка требований)
    "deep": {"critic": True, "rescore": True, "batch_size": 6, "focused": True, "self_check": True, "pdf": True},
}

STEPS = ["Чтение", "Нарезка", "Проверка требований", "Проверка набора", "Домен и глоссарий", "Критик", "Отчёты"]


@dataclass
class Options:
    profile: str = "fast"
    html: bool = True
    fixed: bool = True
    xlsx: bool = True
    jira: bool = True
    json: bool = True
    tests: bool = True
    critic: bool | None = None  # None — по профилю
    rescore: bool | None = None
    domain: str = "fintech"
    compare: str | None = None
    batch_size: int = 8
    pdf: bool | None = None  # PDF-версия отчёта; None — по профилю (deep — да)
    ensemble: str = ""  # v7: «модель1,модель2» — два прогона и объединение подтверждённых замечаний
    strong: str = ""  # v13: «провайдер:модель» сильной модели (--strong) — для честной строки паспорта
    runs: int = 1  # v13: N независимых прогонов (разная температура) — «найдено в k из N», устойчивые замечания
    fix_loop: bool = False  # v7: «исправил → проверил заново» — блок «До / После» и файл <отчёт>_before_after.md
    cascade: str = ""  # v9: «быстрая,сильная» — быстрая проверяет всё, сильная — подозрительные требования и набор
    decisions_llm: bool = False  # v9: модель перефразирует повестку решений на бизнес-язык (иначе — формулировки кода)
    rules: str = ""  # v10: чек-лист банка в YAML (--rules fintech | путь к .rules.yaml | REQLENS_RULES)
    answers: str = ""  # v9: файл ответов аналитика (шаблон <отчёт>_answers_template.md) — перепроверка с учётом ответов


@dataclass
class Context:
    rv: object = None
    scores: object = None
    questions: list = field(default_factory=list)
    changes: list = field(default_factory=list)
    fixed_text: str = ""
    graph: dict = field(default_factory=dict)
    passport: dict = field(default_factory=dict)
    compare: dict | None = None
    rescore: dict | None = None
    artifacts: dict = field(default_factory=dict)
    llm_stats: object = None
    model_label: str = ""
    trace: list = field(default_factory=list)  # [{"i": шаг, "t": секунды от начала}] — таймлайн «Трассировка агента»
    report_md: str = ""
    answers: dict | None = None  # v9: --answers — {"source","items","before","after"} (SCHEMA 2.4)
    decisions: list = field(default_factory=list)  # v9: повестка решений для владельца продукта


def agent_version() -> str:
    """Версия агента: git-тег/коммит, иначе версия пакета."""
    try:
        desc = subprocess.run(["git", "describe", "--tags", "--always", "--dirty"], cwd=ROOT,
                              capture_output=True, text=True, timeout=5)
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                capture_output=True, text=True, timeout=5)
        if commit.returncode == 0:
            d = desc.stdout.strip()
            c = commit.stdout.strip()
            return f"v{__version__}, коммит {c}" + (f" ({d})" if d and d != c else "")
    except Exception:
        pass
    return f"v{__version__} (вне git-репозитория)"


def code_state() -> dict:
    """Состояние кода агента для паспорта: коммит и есть ли незакоммиченные изменения в отслеживаемых файлах."""
    try:
        c = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5)
        st = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True,
                            text=True, timeout=5)
        if c.returncode == 0 and st.returncode == 0:
            return {"commit": c.stdout.strip(), "clean": not st.stdout.strip()}
    except Exception:
        pass
    return {"commit": "", "clean": None}


def apply_profile_env(profile: str) -> None:
    """Профиль offline: локальная модель через OpenAI-совместимый API (Ollama)."""
    if profile == "offline":
        os.environ["LLM_PROVIDER"] = os.getenv("OFFLINE_PROVIDER", "openai")
        os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
        if os.getenv("OFFLINE_MODEL"):
            os.environ["OPENAI_MODEL"] = os.environ["OFFLINE_MODEL"]
        elif not os.getenv("OPENAI_MODEL"):
            os.environ["OPENAI_MODEL"] = "qwen2.5:14b"
        os.environ.setdefault("LLM_MIN_INTERVAL", "0")


def review_document(path, llm, opts: Options, log=print, step=lambda i, label="": None):
    """Чтение → нарезка → проверка требований → набор → домен/глоссарий → критик. Возвращает ReviewResult."""
    from .checker import llm_split, run_review
    from .critic import default_confidence, run_critic
    from .extras import load_domain, run_extras
    from .reader import read_document
    from .splitter import split_requirements

    stt: dict[str, tuple] = {}  # v12: время этапов {этап: (начало, конец, обращений к модели)}
    calls = lambda: getattr(getattr(llm, "stats", None), "calls", 0)  # noqa: E731
    a, c = time.monotonic(), calls()
    step(0)
    doc = read_document(path)
    stt["Чтение"] = (a, time.monotonic(), 0)
    a, c = time.monotonic(), calls()
    log(f"«{doc.title}», строк: {len(doc.lines)}")
    step(1)
    split = split_requirements(doc)
    if not split.requirements:
        log("правила ничего не нашли — нарезка моделью")
        split.requirements = llm_split(doc, llm)
        split.method = "llm"
    if not split.requirements:
        from .errors import DocumentError

        raise DocumentError("В документе не найдено ни одного требования.",
                            "проверьте, что это документ требований: агент ищет пункты с ID (FR-01, Ф-2), нумерованные "
                            "пункты и формулировки «должен / должна»; в режиме «только правила» модель не помогает с "
                            "нарезкой — запустите с ключом модели.", kind="noreqs")
    log(f"выделено требований: {len(split.requirements)} (способ: {split.method})")
    from .depth import recover_uncovered  # v5: «дорезка» строк, не вошедших в нарезку

    recovered = recover_uncovered(doc, split, llm, log=log)
    stt["Нарезка"] = (a, time.monotonic(), calls() - c)
    step(2)
    c = calls()
    # размер пакета: явный LLM_BATCH_SIZE важнее профиля; deep — 6 требований на запрос
    batch = opts.batch_size if os.getenv("LLM_BATCH_SIZE") else PROFILES.get(opts.profile, {}).get("batch_size", opts.batch_size)
    rv = run_review(doc, split, llm, batch_size=batch, log=log, on_set=lambda: step(3))
    stt.update({k: (*v, None) for k, v in rv.stage_times.items()})  # параллельные ветки: обращения — общим числом ниже
    stt["Проверка требований ‖ набора (обращений)"] = (0, 0, calls() - c)
    prof = PROFILES.get(opts.profile, {})
    if prof.get("self_check"):
        from .focus import self_consistency

        a, c = time.monotonic(), calls()
        rv.self_check = self_consistency(rv, llm, batch, log=log)
        stt["Самосогласованность"] = (a, time.monotonic(), calls() - c)
    if prof.get("focused"):
        from .focus import focused_passes

        a, c = time.monotonic(), calls()
        rv.focus = focused_passes(split, doc, llm, rv.dropped, rv.set_findings, log=log)
        rv.set_findings.sort(key=lambda f: {"critical": 0, "major": 1, "minor": 2}[f.severity])
        stt["Узкие проходы"] = (a, time.monotonic(), calls() - c)
    if not opts.tests:
        for rr in rv.req_results:
            rr.test_possible, rr.test_gherkin, rr.test_blocker, rr.test_reason = None, "", "", ""
    step(4)
    a, c = time.monotonic(), calls()
    domain = load_domain(opts.domain)
    run_extras(rv, llm, domain, log=log)
    # R4: категории требований и карта покрытия процесса (без обращений к модели)
    from .categories import apply_categories, coverage_map
    from .checker import SetFinding, SetRef
    from .extras import _anchor

    rv.categories = apply_categories(rv)
    rv.coverage = coverage_map(rv, domain)
    gaps = [s for s in rv.coverage if not s["covered"]]
    if gaps:
        rv.set_findings.append(SetFinding(
            "gap", "set_complete", [SetRef("DOC", _anchor(rv))],
            "Шаги типового процесса не покрыты ни одним требованием: " + "; ".join(s["title"] for s in gaps) + ".",
            "major" if len(gaps) >= 3 else "minor",
            "Добавить требования или явно указать, что шаг вне рамок. Вопросы аналитику: "
            + " ".join(f"{s['title']}: {s['question']}" for s in gaps), "карта покрытия"))
    # v5: покрытие правил критериями приёмки (после перекрёстной проверки — её связи «пример ↔ правило» учитываются)
    from .depth import acceptance_coverage, acceptance_gap

    acc = acceptance_coverage(rv)
    if gap := acceptance_gap(rv, acc):
        rv.set_findings.append(gap)
    critic = PROFILES[opts.profile]["critic"] if opts.critic is None else opts.critic
    stt["Домен, глоссарий, покрытие"] = (a, time.monotonic(), calls() - c)
    a, c = time.monotonic(), calls()
    step(5)
    if critic:
        run_critic(rv, llm, log=log)
    elif os.getenv("REQLENS_CRITIC_CRITICAL", "1") != "0" and any(
            f.severity == "critical" for rr in rv.req_results for f in rr.findings):
        # self-consistency: даже в fast критичные замечания перепроверяются вторым проходом (1 запрос)
        run_critic(rv, llm, log=log, only_critical=True)
    # Шум: «не по шаблону / нет субъекта» к пунктам без ID (шаги логики, строки таблиц, критерии приёмки) — это одно
    # системное свойство документа, а не дефект каждого пункта; оставляем существенные замечания, мелкие сворачиваем.
    folded = 0
    for rr in rv.req_results:
        if rr.req.doc_id is None:
            keep = []
            for f in rr.findings:
                if f.criterion == "conforming" and f.severity == "minor":
                    rv.rejected.append({"where": rr.req.rid, "quote": f.quote, "problem": f.problem,
                                        "reason": "свёрнуто: оформление пунктов без ID оценивается на уровне набора (трассируемость)"})
                    folded += 1
                else:
                    keep.append(f)
            rr.findings = keep
    stt["Критик"] = (a, time.monotonic(), calls() - c)
    a = time.monotonic()
    if folded:
        log(f"  свёрнуто замечаний об оформлении пунктов без ID: {folded}")
    from .depth import calibrate_severity  # v8: тест-проба только к требованиям, дубли с S-xx, потолок серьёзности

    rv.calibration = calibrate_severity(rv)
    if any(rv.calibration.values()):
        log(f"  калибровка серьёзности: тест-проб снято {rv.calibration['test_probe_dropped']}, понижено "
            f"{rv.calibration['capped']}, дублей S-xx свёрнуто {rv.calibration['folded']}")
    from .bank_rules import rules_spec

    if spec := rules_spec(opts.rules):  # v10: чек-лист банка — после критика и калибровки, чтобы правила не снимались
        from .bank_rules import apply_rules, load_rules

        rv.bank_rules = apply_rules(rv, load_rules(spec), log=log)
    if os.getenv("REQLENS_TRACE", "1") != "0":  # v12: граф трассировки (код, без модели) — разрывы как замечания набора
        from .traceability import build as build_trace

        rv.traceability = build_trace(rv)
        ts = rv.traceability["stats"]
        log(f"  трассировка: узлов {sum(ts['nodes'].values())}, связей {sum(ts['edges'].values())}, разрывов "
            f"{ts['gaps']} (новых замечаний {ts['new_findings']}, связано с найденными {ts['linked']})")
    if os.getenv("REQLENS_COMPLIANCE", "1") != "0":  # v13: комплаенс и безопасность (правила, нормы kb/law_kz)
        from .compliance import run as run_compliance

        rv.compliance = run_compliance(rv)
        log(f"  комплаенс и безопасность: нарушений {rv.compliance['fired']}, новых замечаний {rv.compliance['findings']}")
    default_confidence(rv)
    rv.depth = depth_summary(rv, acc)
    rv.depth["review_stats"]["calibration"] = rv.calibration  # v8: калибровка серьёзности
    rv.depth["review_stats"]["self_check"] = rv.self_check or None  # v6: самосогласованность
    rv.depth["review_stats"]["focused"] = rv.focus or None  # v6: узкие проходы {task: добавлено}
    rv.depth["line_coverage"]["recovered"] = recovered.get("recovered", 0)
    rv.depth["line_coverage"]["uncovered_before_recovery"] = recovered.get("uncovered_before", 0)
    # RAG: основания замечаний из базы знаний (стандарты, нормы РК, шаблоны). RAG=off или нет kb/ — пропускаем
    try:
        from .rag.basis import attach_basis
        from .rag.index import get_kb

        kb = get_kb()
        if kb is not None:
            st = attach_basis(rv, kb, log=log)
            rv.rag = {"kb_chunks": len(kb.chunks), "search": kb.mode,
                      "embedder": kb.embedder.label if kb.embedder else "none", **st}
    except Exception as e:  # RAG никогда не ломает основной прогон
        log(f"база знаний недоступна: {e}")
    from .depth import fix_plan  # после RAG: к пунктам плана подставляются шаблоны правок kb/patterns

    rv.depth["fix_plan"] = fix_plan(rv)
    stt["Калибровка, RAG, план"] = (a, time.monotonic(), 0)
    rv.stage_times = stt
    return rv


def stage_report(st: dict) -> dict:
    """v12: время каждого этапа и «критический путь» — цепочка этапов, определяющая длительность прогона
    (из параллельных веток — самая долгая). sum_s > critical_path_s — выигрыш от параллельности."""
    rows = sorted(((k, v) for k, v in st.items() if v[1] > 0), key=lambda kv: kv[1][0])
    if not rows:
        return {}
    base = rows[0][1][0]
    pair_calls = st.get("Проверка требований ‖ набора (обращений)", (0, 0, None))[2]
    stages, groups = [], []
    for name, (s, e, n) in rows:
        stages.append({"stage": name, "start_s": round(s - base, 2), "seconds": round(e - s, 2), "calls": n})
        if groups and s < groups[-1][1] - 1e-6:  # перекрывается с предыдущей группой — параллельная ветка
            groups[-1][1] = max(groups[-1][1], e)
            groups[-1][2].append(stages[-1])
        else:
            groups.append([s, e, [stages[-1]]])
    for g in groups:
        if len(g[2]) > 1:
            for x in g[2]:
                x["parallel"] = True
    path = [max(g[2], key=lambda x: x["seconds"]) for g in groups]
    return {"stages": stages, "critical_path": [x["stage"] for x in path],
            "critical_path_s": round(sum(x["seconds"] for x in path), 2),
            "sum_s": round(sum(x["seconds"] for x in stages), 2), "parallel_calls": pair_calls}


def depth_summary(rv, acc: dict | None = None) -> dict:
    """v5: учёт строк, матрица «требование × критерий», покрытие приёмкой, статистика самопроверки, вердикты, план."""
    from .depth import acceptance_coverage, citation_audit, criteria_matrix, fix_plan, line_coverage, verdicts

    confirmed = sum(len(rr.findings) for rr in rv.req_results) + len(rv.set_findings)
    return {"line_coverage": line_coverage(rv.doc, [rr.req for rr in rv.req_results]),
            "criteria_matrix": criteria_matrix(rv),
            "acceptance_coverage": acc if acc is not None else acceptance_coverage(rv),
            "review_stats": {"proposed": confirmed + len(rv.rejected) + len(rv.dropped), "confirmed": confirmed,
                             "rejected": len(rv.rejected), "unconfirmed_quotes": len(rv.dropped)},
            "verdict": verdicts(rv), "fix_plan": fix_plan(rv), "citation_audit": citation_audit(rv)}


def _sev_counts(rv) -> dict:
    fs = [f for rr in rv.req_results for f in rr.findings] + list(rv.set_findings)
    return {s: sum(1 for f in fs if f.severity == s) for s in ("critical", "major", "minor")} | {"total": len(fs)}


def _before_after(rv, rv2, ctx, ctx2) -> dict:
    from .exports import compare, summarize_for_compare, to_json

    cmp = compare(summarize_for_compare(to_json(ctx)), summarize_for_compare(to_json(ctx2)))
    v1, v2 = (rv.depth or {}).get("verdict") or {}, (rv2.depth or {}).get("verdict") or {}
    return {"counts_before": _sev_counts(rv), "counts_after": _sev_counts(rv2),
            "verdict_before": v1, "verdict_after": v2, "compare": cmp, "changes": len(ctx.changes),
            "remaining": ([{"rid": rr.req.rid, "doc_id": rr.req.doc_id, "problem": f.problem}
                           for rr in rv2.req_results for f in rr.findings if f.severity == "critical"] +
                          [{"rid": f"S-{i:02d}", "doc_id": None, "problem": f.problem}
                           for i, f in enumerate(rv2.set_findings, 1) if f.severity == "critical"])[:15]}


def before_after_md(ctx) -> str:
    rs = ctx.rescore or {}
    b, a = rs.get("counts_before", {}), rs.get("counts_after", {})
    lab = {"fixed": "✅ исправлено", "improved": "⬆️ улучшилось", "new": "⚠️ новое", "worse": "🔻 ухудшилось", "same": "без изменений"}
    L = [f"# До / После: {ctx.rv.doc.title}", "",
         f"Агент применил {rs.get('changes', 0)} исправлений формулировок (файл *_requirements_fixed.md) и проверил "
         "исправленный документ заново той же моделью.", "",
         "| Показатель | До | После |", "|---|---|---|",
         f"| Балл документа | {rs.get('before')} | **{rs.get('after')}** |",
         f"| Готовность к разработке | {rs.get('readiness_before')} % | **{rs.get('readiness_after')} %** |"]
    for k, name in (("critical", "Критичных"), ("major", "Существенных"), ("minor", "Незначительных"), ("total", "Всего замечаний")):
        L.append(f"| {name} | {b.get(k, '—')} | **{a.get(k, '—')}** |")
    vb, va = rs.get("verdict_before") or {}, rs.get("verdict_after") or {}
    if vb and va:
        L.append(f"| Вердикт: разработка / тестирование | {vb.get('development')} / {vb.get('testing')} | "
                 f"**{va.get('development')} / {va.get('testing')}** |")
    c = rs.get("compare") or {}
    if c:
        L += ["", "**По требованиям:** " + " · ".join(f"{lab.get(k, k)}: {v}" for k, v in c.get("counts", {}).items())]
    if rs.get("remaining"):
        L += ["", "**Что осталось критичным после автоисправления** (нужно решение аналитика — данных в документе нет):", ""]
        L += [f"- {x['doc_id'] or x['rid']}: {x['problem'][:200]}" for x in rs["remaining"]]
    L += ["", "Автоисправление не придумывает бизнес-значения: где в документе нет данных (порог, код, срок), "
          "агент ставит плейсхолдер и вопрос аналитику — такие пункты остаются в «что осталось»."]
    return "\n".join(L) + "\n"


LINES_PER_HOUR = 40  # норма ручного ревью по умолчанию: ≈ 1 страница (≈ 40 строк) в час


def time_estimate(doc, duration_s: float) -> dict:
    """v10: оценка экономии времени — строки документа ÷ норма ручного ревью против фактического времени агента.

    Норма — REVIEW_LINES_PER_HOUR из .env (по умолчанию 40 строк/ч). Это оценка, а не замер: в отчёте подписана так."""
    try:
        rate = max(1, int(os.getenv("REVIEW_LINES_PER_HOUR", "") or LINES_PER_HOUR))
        src = "REVIEW_LINES_PER_HOUR" if os.getenv("REVIEW_LINES_PER_HOUR") else "по умолчанию"
    except ValueError:
        rate, src = LINES_PER_HOUR, "по умолчанию (REVIEW_LINES_PER_HOUR не число)"
    lines = sum(1 for line in doc.lines if line.text.strip())
    return {"doc_lines": lines, "lines_per_hour": rate, "norm_source": src, "manual_hours": round(lines / rate, 1),
            "agent_minutes": max(0.1, round(duration_s / 60, 1)), "estimate": True}


def _ctx_info(doc) -> dict:
    st = getattr(doc, "_ctx_stats", None) or {}
    pc = st.get("prompt_chars") or []
    return {"mode": "RAG-выборка" if st.get("mode") == "rag" else "полный текст",
            "avg_prompt_tokens": round(sum(pc) / len(pc) / 4) if pc else 0, "doc_chars": len(doc.text)}


def build_context(rv, llm, opts: Options, started: datetime, t0: float, input_path: str,
                  code: dict | None = None, version: str | None = None) -> Context:
    from .fixer import build_fixed_document
    from .graph import build_graph
    from .questions import build_questions
    from .scoring import compute

    ctx = Context(rv=rv, llm_stats=llm.stats, model_label=llm.label)
    ctx.scores = compute(rv)
    ctx.questions = build_questions(rv)
    ctx.fixed_text, ctx.changes = build_fixed_document(rv)
    ctx.graph = build_graph(rv)
    offline = opts.profile == "offline" or any(h in os.getenv("OPENAI_BASE_URL", "") for h in ("localhost", "127.0.0.1"))
    ctx.passport = {
        "document": rv.doc.title, "file": str(input_path), "format": rv.doc.fmt.upper(), "pages": rv.doc.pages,
        "sha256": rv.doc.sha256, "started": started.strftime("%Y-%m-%d %H:%M:%S %Z").strip(),
        "model": llm.label, "agent_version": version or agent_version(), "code": code or code_state(), "profile": opts.profile,
        "mode": "офлайн: документ не передавался третьим лицам" if offline and llm.provider != "mock" else
                ("тестовый (mock)" if llm.provider == "mock" else
                 "только правила: модель не вызывалась, смысловые противоречия не проверялись" if llm.provider == "rules"
                 else "облачная модель"),
        **({"strong": {"model": opts.strong, "note": "прогон на сильной модели (--strong); отчёт для сдачи — на "
                                                      "бесплатной модели"}} if getattr(opts, "strong", "") else {}),
        "calls": llm.stats.calls, "cached": llm.stats.cached, "retries": llm.stats.retries, "tokens_in": llm.stats.prompt_tokens,
        "tokens_out": llm.stats.output_tokens, "duration_s": round(time.monotonic() - t0),
        "model_switches": list(getattr(llm.stats, "switches", [])),
        "rag": getattr(rv, "rag", None) or {"enabled": False},
        "context": _ctx_info(rv.doc),
        "time_estimate": time_estimate(rv.doc, time.monotonic() - t0),  # v10: оценка, не замер
        "split_method": rv.split.method, "dropped": len(rv.dropped), "rejected": len(rv.rejected),
        "critic": rv.critic_used, "domain": opts.domain,
    }
    return ctx


def _apply_answers(rv, llm, path: str, log) -> dict:
    """Учесть ответы аналитика в результате проверки; вопросы и срез «до» — по прогону без ответов."""
    from .answers import apply_answers, parse_answers, summary_state
    from .ensemble import refresh_depth
    from .questions import build_questions
    from .scoring import compute

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Файл ответов не найден: {path}")
    parsed = parse_answers(p.read_text(encoding="utf-8"))
    if not parsed:
        raise ValueError(f"В файле ответов {p.name} нет ни одного ответа под заголовком «### Q-xx». "
                         "Возьмите шаблон <отчёт>_answers_template.md и впишите ответы под вопросами.")
    questions = build_questions(rv)
    before = summary_state(rv, compute(rv))
    all_before = [f for rr in rv.req_results for f in rr.findings] + list(rv.set_findings)
    result = apply_answers(rv, questions, parsed, llm=llm, log=log)
    # v12: исправленная редакция ТЗ — «было → стало», новые требования, критерии приёмки, что осталось уточнить
    from . import revised as rev

    revised = rev.write(rv, rev.plan(rv, questions, result, result["closed_list"]), llm=llm, log=log)
    refresh_depth(rv)
    open_after = sum(len(rr.findings) for rr in rv.req_results) + len(rv.set_findings)
    blockers = [c for c in result["closed_list"] if c["severity"] == "critical"]
    summary = {"blockers_total": sum(f.severity == "critical" for f in all_before), "blockers_closed": len(blockers),
               "open_before": len(all_before), "open_after": open_after, "closed_blockers": blockers}
    return {"questions": questions, "before": before, "result": result, "revised": revised, "summary": summary}


def run(input_path: str, output_path: str, opts: Options, log=print, step=lambda i, label="": None, llm_wrap=None,
        make_llm=None) -> Context:
    """llm_wrap — необязательная обёртка над моделью (Studio наблюдает за пакетами для живой таблицы); логику не меняет.
    make_llm — своя фабрика модели вместо .env (ReqLens App: режим «только правила» для одного прогона).
    v9: рядом с отчётом пишется журнал прогона <отчёт>.log (и при ошибке — до места, где она случилась)."""
    from .runlog import RunLog

    rl = RunLog()

    def log_(m):
        rl.add(m)
        log(m)

    def step_(i, label=""):
        rl.stage(STEPS[i] if 0 <= i < len(STEPS) else (label or f"этап {i}"))
        step(i, label)

    log_path = Path(output_path).with_suffix(".log")
    try:
        ctx = _run(input_path, output_path, opts, log_, step_, llm_wrap, make_llm, log_path)
    except Exception as e:
        try:
            rl.write(log_path, error=str(e))
        except OSError:
            pass
        raise
    rl.write(log_path, ctx)
    return ctx


def _run(input_path, output_path, opts: Options, log, step, llm_wrap, make_llm, log_path: Path) -> Context:
    from .exports import compare, summarize_for_compare, to_json, write_jira_csv, write_json, write_xlsx
    from .llm import build_llm_from_env
    from .report import build_report

    apply_profile_env(opts.profile)
    started = datetime.now().astimezone()
    t0 = time.monotonic()
    # версия и состояние кода — на момент старта: правки во время долгого прогона не меняют паспорт задним числом
    started_code, started_version = code_state(), agent_version()
    timeline: list[dict] = []

    def tstep(i, label=""):
        timeline.append({"i": i, "t": round(time.monotonic() - t0, 2)})
        step(i, label)

    from .ensemble import model_env, parse

    models = [] if make_llm else parse(opts.ensemble)
    cascade = None
    if models:
        with model_env(models[0]):
            llm = build_llm_from_env()
    elif opts.cascade and not make_llm:
        from .cascade import build_cascade

        llm = cascade = build_cascade(opts.cascade)
        log(f"каскад моделей: быстрая {cascade.fast.label}, сильная {cascade.strong.label}")
    else:
        llm = make_llm() if make_llm else build_llm_from_env()
    if llm_wrap:
        llm = llm_wrap(llm)
    rv = review_document(input_path, llm, opts, log=log, step=tstep)
    runs_info, runs_brief = None, []
    if opts.runs > 1:  # v13: стабильность — ещё N−1 прогонов с другой температурой, сопоставление без новых запросов
        from .stability import brief, mark, temperatures

        temps = temperatures(opts.runs)
        others = []
        old_t = getattr(llm, "temperature", 0.0)
        try:
            for k, t in enumerate(temps[1:], start=2):
                log(f"стабильность: прогон {k} из {opts.runs} (температура {t})")
                if hasattr(llm, "temperature"):
                    llm.temperature = t
                others.append(review_document(input_path, llm, opts, log=lambda m: log("  [run] " + m)))
        finally:
            if hasattr(llm, "temperature"):
                llm.temperature = old_t
        runs_info = mark(rv, others)
        runs_brief = [brief(x) for x in [rv, *others]]
        log(f"стабильность: устойчивых замечаний {runs_info['stable']}, найдено в одном прогоне {runs_info['unstable']}")
    ens_info = None
    if models:  # v7: второй прогон другой моделью и объединение подтверждённых замечаний
        from .ensemble import merge, refresh_depth

        log(f"ансамбль: второй прогон моделью {models[1]}")
        with model_env(models[1]):
            llm_b = build_llm_from_env()
        rv_b = review_document(input_path, llm_b, opts, log=lambda m: log("  [B] " + m))
        st = merge(rv, rv_b, f"модель A ({models[0]})", f"модель B ({models[1]})")
        refresh_depth(rv)
        for k in ("calls", "retries", "prompt_tokens", "output_tokens", "cached"):
            if hasattr(llm.stats, k) and hasattr(llm_b.stats, k):
                setattr(llm.stats, k, getattr(llm.stats, k) + getattr(llm_b.stats, k))
        ens_info = {"models": [llm.label, llm_b.label], "only_a": st["a"], "only_b": st["b_added"], "both": st["both"],
                    "rules": st["rules"]}
        log(f"ансамбль: только A — {st['a']}, только B — {st['b_added']}, обе — {st['both']}, правила — {st['rules']}")
    if rv.dropped:  # лог трассировки: замечания модели с цитатами, которых нет в документе
        log(f"отброшено замечаний с неподтверждёнными цитатами: {len(rv.dropped)} "
            + "; ".join(f"{d['where']}: «{str(d['quote'])[:40]}»" for d in rv.dropped[:3]))
    ans_state = None
    if opts.answers:  # v9: ответы аналитика — до построения отчёта, чтобы закрытые замечания не попали в разделы 3–6
        ans_state = _apply_answers(rv, llm, opts.answers, log)
    ctx = build_context(rv, llm, opts, started, t0, input_path, started_code, started_version)
    ctx.trace = timeline
    if cascade is not None:
        ctx.passport["cascade"] = cascade.passport()
        log(f"каскад: на сильную модель ушло {ctx.passport['cascade']['strong_reqs']} из "
            f"{ctx.passport['cascade']['checked_reqs']} требований; обращения: быстрая {ctx.passport['cascade']['calls']['fast']}, "
            f"сильная {ctx.passport['cascade']['calls']['strong']}")
    ctx.passport["log"] = log_path.name  # v9: журнал прогона рядом с отчётом
    ctx.artifacts["Журнал прогона"] = log_path
    if ans_state:
        from .answers import answers_json, summary_state

        ctx.questions = ans_state["questions"]  # исходные вопросы: Q-xx и closes — по нумерации до ответов
        ctx.answers = answers_json(Path(opts.answers).name, ans_state["result"], ans_state["before"],
                                   summary_state(rv, ctx.scores))
        ctx.answers["revised"] = ans_state["revised"]  # v12: исправленная редакция ТЗ (SCHEMA 2.5)
        ctx.answers["summary"] = ans_state["summary"]
        ctx.passport["answers"] = {"file": Path(opts.answers).name, "items": len(ctx.answers["items"]),
                                   "closed": ans_state["result"]["closed"]}
    from .decisions import build_decisions, rephrase
    from .exports import to_json as _to_json

    ctx.decisions = build_decisions(_to_json(ctx))  # v9: повестка решений — код из подтверждённых замечаний
    if opts.decisions_llm:
        ctx.decisions = rephrase(ctx.decisions, llm, log)
    if runs_info:  # v13: стабильность по N прогонам
        ctx.passport["runs"] = runs_info
    if ens_info:
        ctx.passport["ensemble"] = ens_info
        ctx.passport["model"] = " + ".join(ens_info["models"]) + " (ансамбль)"

    rescore = PROFILES[opts.profile]["rescore"] if opts.rescore is None else opts.rescore
    if rescore and ctx.changes:
        log("повторная проверка исправленного документа (--rescore)")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "requirements_fixed.md"
            p.write_text(ctx.fixed_text, encoding="utf-8")
            o2 = Options(**{**opts.__dict__, "critic": False, "rescore": False, "compare": None})
            rv2 = review_document(p, llm, o2, log=lambda m: log("  [rescore] " + m))
            from .scoring import compute

            s2 = compute(rv2)
            ctx.rescore = {"before": ctx.scores.doc_score, "after": s2.doc_score,
                           "readiness_before": ctx.scores.readiness, "readiness_after": s2.readiness}
            if opts.fix_loop:  # v7: подробное «До / После» — без новых обращений к модели сверх одного повторного прогона
                ctx2 = build_context(rv2, llm, o2, started, t0, str(p))
                ctx.rescore.update(_before_after(rv, rv2, ctx, ctx2))
        ctx.passport["calls"] = llm.stats.calls
        ctx.passport["cached"] = llm.stats.cached

    if opts.compare:
        log(f"сравнение с предыдущей версией: {opts.compare}")
        cp = Path(opts.compare)
        if cp.suffix.lower() == ".json":
            old = summarize_for_compare(json.loads(cp.read_text(encoding="utf-8")))
        else:
            o2 = Options(**{**opts.__dict__, "critic": False, "rescore": False, "compare": None})
            rv_old = review_document(cp, llm, o2, log=lambda m: log("  [compare] " + m))
            ctx_old = build_context(rv_old, llm, o2, started, t0, str(cp))
            old = summarize_for_compare(to_json(ctx_old))
        ctx.compare = compare(old, summarize_for_compare(to_json(ctx)))
        ctx.passport["calls"] = llm.stats.calls
        ctx.passport["cached"] = llm.stats.cached

    tstep(6)
    ctx.passport["duration_s"] = round(time.monotonic() - t0)
    from .cost import estimate  # v13: оценка стоимости прогона по config/prices.yaml

    ctx.passport["cost"] = estimate(ctx.passport.get("model", llm.label), llm.stats.prompt_tokens, llm.stats.output_tokens,
                                    llm.stats.calls)
    if sr := stage_report(rv.stage_times):  # v12: время этапов и критический путь
        from .parallel import concurrency

        ctx.passport["stages"] = sr["stages"]
        ctx.passport["critical_path"] = {"stages": sr["critical_path"], "seconds": sr["critical_path_s"],
                                         "stages_sum_s": sr["sum_s"], "concurrency": concurrency()}
        log("этапы: " + " · ".join(f"{x['stage']} {x['seconds']:.1f} с" + (" ‖" if x.get("parallel") else "")
                                   for x in sr["stages"])
            + f" | критический путь {sr['critical_path_s']:.1f} с: " + " → ".join(sr["critical_path"]))
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    stem = out.with_suffix("")
    ctx.report_md = build_report(rv, model_label=ctx.passport["model"], agent_version=ctx.passport["agent_version"], started=started,
                                 duration_s=time.monotonic() - t0, llm_stats=llm.stats, input_path=input_path, ctx=ctx)
    out.write_text(ctx.report_md, encoding="utf-8")
    ctx.artifacts["Отчёт (Markdown)"] = out
    if opts.fix_loop and (ctx.rescore or {}).get("counts_after"):
        ba = out.with_name(out.stem + "_before_after.md")
        ba.write_text(before_after_md(ctx), encoding="utf-8")
        ctx.artifacts["До / После (исправленный документ)"] = ba
    if opts.pdf if opts.pdf is not None else PROFILES.get(opts.profile, {}).get("pdf", False):
        try:  # v7: PDF-версия для сдачи и печати; без шрифта или reportlab прогон не падает
            from .pdf_report import PdfFontError, markdown_to_pdf

            ctx.artifacts["Отчёт (PDF)"] = markdown_to_pdf(ctx.report_md, out.with_suffix(".pdf"),
                                                          f"Отчёт ReqLens — {rv.doc.title}")
        except PdfFontError as e:
            log(f"PDF не создан: {e}")
    if opts.fixed and ctx.changes:
        p = out.parent / f"{stem.name}_requirements_fixed.md"
        p.write_text(ctx.fixed_text, encoding="utf-8")
        ctx.artifacts["Исправленный документ"] = p
    if opts.fixed and ctx.changes:
        from .fixer import document_diff

        p = out.parent / f"{stem.name}_fixed.diff"
        p.write_text(document_diff(rv, ctx.fixed_text), encoding="utf-8")
        ctx.artifacts["Исправления (unified diff)"] = p
    if ctx.answers and ctx.answers.get("revised"):  # v12: исправленная редакция ТЗ после ответов
        from .revised import agent_suggestions, revised_md

        done = {c["rid"] for c in ctx.answers["revised"]["changed"]}
        p = out.parent / f"{stem.name}_revised.md"
        ctx.answers["revised"]["suggestions"] = agent_suggestions(rv, done)
        p.write_text(revised_md(rv.doc.title, ctx.answers["revised"], ctx.answers["summary"],
                                ctx.answers["revised"]["suggestions"]), encoding="utf-8")
        ctx.artifacts["Исправленная редакция ТЗ"] = p
        if opts.pdf if opts.pdf is not None else PROFILES.get(opts.profile, {}).get("pdf", False):
            try:
                from .pdf_report import PdfFontError, markdown_to_pdf

                ctx.artifacts["Исправленная редакция ТЗ (PDF)"] = markdown_to_pdf(
                    p.read_text(encoding="utf-8"), p.with_suffix(".pdf"), f"Исправленная редакция — {rv.doc.title}")
            except PdfFontError as e:
                log(f"PDF исправленной редакции не создан: {e}")
    if ctx.decisions:  # v9: повестка решений для владельца продукта
        from .decisions import decisions_file

        p = out.parent / f"{stem.name}_decisions.md"
        p.write_text(decisions_file(ctx.decisions, rv.doc.title), encoding="utf-8")
        ctx.artifacts["Решения для владельца продукта"] = p
    if ctx.questions:  # v9: шаблон ответов аналитика — вписать ответы и запустить --answers
        from .answers import question_options, template_md

        set_values = {f"S-{i:02d}": [str(v.get("value", "")) for v in f.values if v.get("value")]
                      for i, f in enumerate(rv.set_findings, 1) if f.values}
        p = out.parent / f"{stem.name}_answers_template.md"
        p.write_text(template_md(ctx.questions, rv.doc.title, question_options(ctx.questions, ctx.decisions, set_values)),
                     encoding="utf-8")
        ctx.artifacts["Шаблон ответов аналитика"] = p
    if opts.tests and any(rr.test_possible for rr in rv.req_results):
        from .exports import feature_text

        p = out.parent / f"{stem.name}_tests.feature"
        p.write_text(feature_text(ctx), encoding="utf-8")
        ctx.artifacts["Приёмочные тесты (.feature)"] = p
    if opts.json:
        p = stem.with_suffix(".json")
        write_json(ctx, p)
        ctx.artifacts["Данные (JSON)"] = p
    if runs_brief:  # v13: краткие копии каждого прогона — для bench/stability.py (среднее и разброс полноты)
        import json as _json

        p = out.parent / f"{stem.name}_runs.json"
        p.write_text(_json.dumps({"runs": runs_brief, "info": runs_info}, ensure_ascii=False, indent=1), encoding="utf-8")
        ctx.artifacts["Прогоны для оценки стабильности (JSON)"] = p
    if opts.xlsx:
        p = out.parent / f"{stem.name}_traceability.xlsx"
        write_xlsx(ctx, p)
        ctx.artifacts["Трассировка (Excel)"] = p
    if opts.jira:
        p = out.parent / f"{stem.name}_jira_import.csv"
        write_jira_csv(ctx, p)
        ctx.artifacts["Импорт в Jira (CSV)"] = p
    if opts.html:
        from .html_report import write_html

        p = stem.with_suffix(".html")
        timeline.append({"i": 7, "t": round(time.monotonic() - t0, 2)})  # конец записи отчётов
        write_html(ctx, p)
        ctx.artifacts["Интерактивный отчёт (HTML)"] = p
    return ctx
