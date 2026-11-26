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
    "deep": {"critic": True, "rescore": True, "batch_size": 6},
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

    step(0)
    doc = read_document(path)
    log(f"«{doc.title}», строк: {len(doc.lines)}")
    step(1)
    split = split_requirements(doc)
    if not split.requirements:
        log("правила ничего не нашли — нарезка моделью")
        split.requirements = llm_split(doc, llm)
        split.method = "llm"
    if not split.requirements:
        raise ValueError("В документе не найдено ни одного требования.")
    log(f"выделено требований: {len(split.requirements)} (способ: {split.method})")
    from .depth import recover_uncovered  # v5: «дорезка» строк, не вошедших в нарезку

    recovered = recover_uncovered(doc, split, llm, log=log)
    step(2)
    # размер пакета: явный LLM_BATCH_SIZE важнее профиля; deep — 6 требований на запрос
    batch = opts.batch_size if os.getenv("LLM_BATCH_SIZE") else PROFILES.get(opts.profile, {}).get("batch_size", opts.batch_size)
    rv = run_review(doc, split, llm, batch_size=batch, log=log, on_set=lambda: step(3))
    if not opts.tests:
        for rr in rv.req_results:
            rr.test_possible, rr.test_gherkin, rr.test_blocker, rr.test_reason = None, "", "", ""
    step(4)
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
    if folded:
        log(f"  свёрнуто замечаний об оформлении пунктов без ID: {folded}")
    default_confidence(rv)
    rv.depth = depth_summary(rv, acc)
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
    return rv


def depth_summary(rv, acc: dict | None = None) -> dict:
    """v5: учёт строк, матрица «требование × критерий», покрытие приёмкой, статистика самопроверки, вердикты, план."""
    from .depth import acceptance_coverage, criteria_matrix, fix_plan, line_coverage, verdicts

    confirmed = sum(len(rr.findings) for rr in rv.req_results) + len(rv.set_findings)
    return {"line_coverage": line_coverage(rv.doc, [rr.req for rr in rv.req_results]),
            "criteria_matrix": criteria_matrix(rv),
            "acceptance_coverage": acc if acc is not None else acceptance_coverage(rv),
            "review_stats": {"proposed": confirmed + len(rv.rejected) + len(rv.dropped), "confirmed": confirmed,
                             "rejected": len(rv.rejected), "unconfirmed_quotes": len(rv.dropped)},
            "verdict": verdicts(rv), "fix_plan": fix_plan(rv)}


def _ctx_info(doc) -> dict:
    st = getattr(doc, "_ctx_stats", None) or {}
    pc = st.get("prompt_chars") or []
    return {"mode": "RAG-выборка" if st.get("mode") == "rag" else "полный текст",
            "avg_prompt_tokens": round(sum(pc) / len(pc) / 4) if pc else 0, "doc_chars": len(doc.text)}


def build_context(rv, llm, opts: Options, started: datetime, t0: float, input_path: str) -> Context:
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
        "model": llm.label, "agent_version": agent_version(), "profile": opts.profile,
        "mode": "офлайн: документ не передавался третьим лицам" if offline and llm.provider != "mock" else
                ("тестовый (mock)" if llm.provider == "mock" else
                 "только правила: модель не вызывалась, смысловые противоречия не проверялись" if llm.provider == "rules"
                 else "облачная модель"),
        "calls": llm.stats.calls, "retries": llm.stats.retries, "tokens_in": llm.stats.prompt_tokens,
        "tokens_out": llm.stats.output_tokens, "duration_s": round(time.monotonic() - t0),
        "model_switches": list(getattr(llm.stats, "switches", [])),
        "rag": getattr(rv, "rag", None) or {"enabled": False},
        "context": _ctx_info(rv.doc),
        "split_method": rv.split.method, "dropped": len(rv.dropped), "rejected": len(rv.rejected),
        "critic": rv.critic_used, "domain": opts.domain,
    }
    return ctx


def run(input_path: str, output_path: str, opts: Options, log=print, step=lambda i, label="": None, llm_wrap=None,
        make_llm=None) -> Context:
    """llm_wrap — необязательная обёртка над моделью (Studio наблюдает за пакетами для живой таблицы); логику не меняет.
    make_llm — своя фабрика модели вместо .env (ReqLens App: режим «только правила» для одного прогона)."""
    from .exports import compare, summarize_for_compare, to_json, write_jira_csv, write_json, write_xlsx
    from .llm import build_llm_from_env
    from .report import build_report

    apply_profile_env(opts.profile)
    started = datetime.now().astimezone()
    t0 = time.monotonic()
    timeline: list[dict] = []

    def tstep(i, label=""):
        timeline.append({"i": i, "t": round(time.monotonic() - t0, 2)})
        step(i, label)

    llm = make_llm() if make_llm else build_llm_from_env()
    if llm_wrap:
        llm = llm_wrap(llm)
    rv = review_document(input_path, llm, opts, log=log, step=tstep)
    if rv.dropped:  # лог трассировки: замечания модели с цитатами, которых нет в документе
        log(f"отброшено замечаний с неподтверждёнными цитатами: {len(rv.dropped)} "
            + "; ".join(f"{d['where']}: «{str(d['quote'])[:40]}»" for d in rv.dropped[:3]))
    ctx = build_context(rv, llm, opts, started, t0, input_path)
    ctx.trace = timeline

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
        ctx.passport["calls"] = llm.stats.calls

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

    tstep(6)
    ctx.passport["duration_s"] = round(time.monotonic() - t0)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    stem = out.with_suffix("")
    ctx.report_md = build_report(rv, model_label=llm.label, agent_version=ctx.passport["agent_version"], started=started,
                                 duration_s=time.monotonic() - t0, llm_stats=llm.stats, input_path=input_path, ctx=ctx)
    out.write_text(ctx.report_md, encoding="utf-8")
    ctx.artifacts["Отчёт (Markdown)"] = out
    if opts.fixed and ctx.changes:
        p = out.parent / f"{stem.name}_requirements_fixed.md"
        p.write_text(ctx.fixed_text, encoding="utf-8")
        ctx.artifacts["Исправленный документ"] = p
    if opts.fixed and ctx.changes:
        from .fixer import document_diff

        p = out.parent / f"{stem.name}_fixed.diff"
        p.write_text(document_diff(rv, ctx.fixed_text), encoding="utf-8")
        ctx.artifacts["Исправления (unified diff)"] = p
    if opts.tests and any(rr.test_possible for rr in rv.req_results):
        from .exports import feature_text

        p = out.parent / f"{stem.name}_tests.feature"
        p.write_text(feature_text(ctx), encoding="utf-8")
        ctx.artifacts["Приёмочные тесты (.feature)"] = p
    if opts.json:
        p = stem.with_suffix(".json")
        write_json(ctx, p)
        ctx.artifacts["Данные (JSON)"] = p
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
