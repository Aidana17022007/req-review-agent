"""Точка входа: python review.py <файл требований> <файл отчёта> [опции]"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from .pipeline import PROFILES, ROOT, Options, agent_version  # noqa: F401  (agent_version — обратная совместимость)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="review.py",
        description="ReqLens — ИИ-агент статической проверки документа требований (ISO/IEC/IEEE 29148, IEEE 830).",
    )
    ap.add_argument("input", help="путь к документу требований (.pdf, .docx, .md, .txt)")
    ap.add_argument("output", help="путь к файлу отчёта (.md); остальные артефакты ложатся рядом")
    ap.add_argument("--env", default=None, help="путь к .env (по умолчанию .env в корне проекта)")
    ap.add_argument("--profile", choices=list(PROFILES), default=None,
                    help="fast — минимум запросов (по умолчанию); full — критик и повторная оценка; deep — для финального отчёта "
                         "(критик на все замечания, повторная оценка); offline — локальная модель (Ollama)")
    ap.add_argument("--domain", default=None, help="доменный чек-лист полноты: fintech (по умолчанию) или none")
    ap.add_argument("--compare", default=None, metavar="СТАРЫЙ", help="предыдущая версия: документ или report.json прошлого прогона")
    ap.add_argument("--critic", dest="critic", action="store_true", default=None, help="включить критик-агента")
    ap.add_argument("--no-critic", dest="critic", action="store_false", help="выключить критик-агента")
    ap.add_argument("--rescore", dest="rescore", action="store_true", default=None,
                    help="повторно проверить исправленный документ («было → стало»)")
    ap.add_argument("--no-rescore", dest="rescore", action="store_false",
                    help="не перепроверять исправленный документ (экономит запросы к модели)")
    ap.add_argument("--no-cache", action="store_true",
                    help="не брать ответы модели из кэша: свежий прогон (для отчёта, который сдаётся); "
                         "ответы при этом записываются в кэш — повторный прогон того же документа квоту не тратит")
    ap.add_argument("--no-tests", action="store_true", help="не включать тест-пробу (Gherkin) в отчёт")
    ap.add_argument("--pdf", dest="pdf", action="store_true", default=None,
                    help="записать PDF-версию отчёта рядом с .md (в профиле deep — по умолчанию)")
    ap.add_argument("--no-pdf", dest="pdf", action="store_false", help="не создавать PDF-версию отчёта")
    ap.add_argument("--ensemble", default=None, metavar="M1,M2",
                    help="ансамбль двух моделей: два прогона и объединение подтверждённых замечаний (или LLM_ENSEMBLE)")
    ap.add_argument("--strong", action="store_true",
                    help="прогон на сильной модели из STRONG_MODEL=провайдер:модель (профиль deep по умолчанию); "
                         "отчёт для сдачи остаётся на бесплатной модели — этот кладите рядом, например reports/strong/")
    ap.add_argument("--runs", type=int, default=1, metavar="N",
                    help="N независимых прогонов (разная температура): у замечаний «найдено в k из N», устойчивые — в ≥ 2")
    ap.add_argument("--answers", default=None, metavar="ОТВЕТЫ.md",
                    help="ответы аналитика (шаблон <отчёт>_answers_template.md): перепроверка, конкретные ответы закрывают замечания")
    ap.add_argument("--rules", default=None, metavar="ФАЙЛ",
                    help="чек-лист банка в YAML: fintech (пример) или путь к .rules.yaml (также REQLENS_RULES)")
    ap.add_argument("--cascade", default=None, metavar="FAST,STRONG",
                    help="каскад моделей: быстрая проверяет всё, сильная — подозрительные требования и набор (или LLM_CASCADE)")
    ap.add_argument("--decisions-llm", action="store_true",
                    help="модель перефразирует «Решения для владельца продукта» на бизнес-язык (иначе — формулировки кода)")
    ap.add_argument("--fix-loop", action="store_true",
                    help="исправить формулировки, проверить исправленный документ заново и записать «До / После»")
    for name, what in (("html", "интерактивный HTML-отчёт"), ("fixed", "исправленный документ"), ("xlsx", "Excel-трассировку"),
                       ("jira", "CSV для Jira"), ("json", "report.json")):
        ap.add_argument(f"--no-{name}", action="store_true", help=f"не создавать {what}")
    ap.add_argument("--no-journal", action="store_true",
                    help="не писать журнал прогона <папка отчёта>/runs/<id>/ (вход и выход каждого обращения к модели)")
    ap.add_argument("--replay", default=None, metavar="runs/<id>",
                    help="повторить прогон из журнала: ответы модели берутся из runs/<id>, без сети и квоты")
    ap.add_argument("--fail-on", choices=["blocker", "partial"], default=None,
                    help="для CI: код 1, если blocker — есть критичные замечания (как --gate), partial — есть "
                         "критичные или существенные (вердикт «нельзя» или «с оговорками»)")
    ap.add_argument("--gate", action="store_true",
                    help="гейт для CI: код выхода 1, если разработку начинать нельзя (есть критичные замечания); "
                         "0 — можно или с оговорками. Без флага — 0 при любом вердикте")
    ap.add_argument("--open", action="store_true", help="открыть HTML-отчёт в браузере после прогона")
    ap.add_argument("--quiet", action="store_true", help="минимальный вывод")
    ap.add_argument("--json", dest="json_out", default=None, help=argparse.SUPPRESS)  # совместимость с v1
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("verify", "doctor"):  # v13+: служебные команды
        return _service(argv)
    args = build_parser().parse_args(argv)

    import os

    from dotenv import load_dotenv

    load_dotenv(args.env or ROOT / ".env")
    if args.no_cache:
        os.environ["LLM_CACHE"] = "refresh"  # не читать кэш (свежий прогон), но записать ответы для повторов
    if args.strong:  # v13: сильная модель — на время прогона подменяются провайдер и модель
        spec = os.getenv("STRONG_MODEL", "").strip()
        if not spec:
            sys.stderr.write("Ошибка: для --strong задайте STRONG_MODEL=провайдер:модель в .env (например "
                             "openrouter:<модель> или openai:deepseek-chat) и ключ этого провайдера.\n")
            return 2
        from .ensemble import model_env

        with model_env(spec):
            return _main(args, strong=spec)
    return _main(args)


def _main(args, strong: str = "") -> int:
    import os

    from .console import Console
    from .errors import DocumentError
    from .llm import LLMError
    from .pipeline import apply_profile_env, run

    profile = args.profile or ("deep" if strong else os.getenv("REQLENS_PROFILE", "fast"))
    opts = Options(
        profile=profile,
        html=not args.no_html, fixed=not args.no_fixed, xlsx=not args.no_xlsx, jira=not args.no_jira,
        json=not args.no_json, tests=not args.no_tests, critic=args.critic,
        rescore=True if args.fix_loop else args.rescore, fix_loop=args.fix_loop, answers=args.answers or "", rules=args.rules or os.getenv("REQLENS_RULES", ""), decisions_llm=args.decisions_llm,
        ensemble=args.ensemble or os.getenv("LLM_ENSEMBLE", ""), runs=max(1, args.runs),
        cascade=args.cascade or os.getenv("LLM_CASCADE", ""),
        domain=args.domain or os.getenv("REQLENS_DOMAIN", "fintech"), compare=args.compare,
        batch_size=int(os.getenv("LLM_BATCH_SIZE", "20")), pdf=args.pdf, strong=strong,
        journal="" if args.no_journal else str(Path(args.output).resolve().parent / "runs"), replay=args.replay or "",
    )
    con = Console(quiet=args.quiet)
    if opts.rules:  # v10: файл правил проверяется до прогона — понятная ошибка без трейсбека и без трат квоты
        from .bank_rules import RulesError, load_rules

        try:
            load_rules(opts.rules)
        except RulesError as e:
            con.error(f"Ошибка в чек-листе банка: {e}")
            return 2
    apply_profile_env(profile)
    try:
        from .llm import build_llm_from_env

        label = f"повтор журнала {args.replay}" if args.replay else build_llm_from_env().label
    except LLMError as e:
        con.error(f"Ошибка конфигурации LLM: {e}\n{_rules_hint(args)}")
        return 2
    con.banner(args.input, label, profile)
    try:
        ctx = run(args.input, args.output, opts, log=con.log, step=con.step)
    except DocumentError as e:  # v9: «сломанный» входной файл — что случилось и что сделать, без трейсбека
        con.error(f"Ошибка: {e.message}\nЧто сделать: {e.hint[:1].upper()}{e.hint[1:]}")
        return e.code
    except (FileNotFoundError, ValueError) as e:
        con.error(f"Ошибка: {e}")
        return 2 if isinstance(e, FileNotFoundError) or "не поддерживается" in str(e) or "Домен" in str(e) else 3
    except LLMError as e:
        msg = f"Ошибка обращения к модели: {e}"
        if any(x in str(e) for x in ("HTTP 400", "HTTP 401", "HTTP 403", "API key", "API_KEY")):
            msg += "\nПохоже, ключ неверен или не подходит для этой модели. " + _rules_hint(args)
        if os.getenv("REQLENS_FALLBACK_RULES", "1") == "0":
            con.error(msg)
            return 4
        # v13+: модель недоступна — отчёт собирается правилами (с пометкой в паспорте), код выхода 3
        con.error(msg + "\nМодель недоступна — собираю отчёт только правилами (код выхода 3).")
        old_provider = os.environ.get("LLM_PROVIDER")
        os.environ["LLM_PROVIDER"] = "rules"
        try:
            ctx = run(args.input, args.output, opts, log=con.log, step=con.step)
        except Exception as e2:  # noqa: BLE001
            con.error(f"Отчёт правилами тоже не собран: {e2}")
            return 4
        finally:
            if old_provider is None:
                os.environ.pop("LLM_PROVIDER", None)
            else:
                os.environ["LLM_PROVIDER"] = old_provider
        ctx.fallback_rules = True
    if args.json_out:
        from .exports import write_json

        write_json(ctx, Path(args.json_out))
    con.summary(ctx)
    if not args.quiet:
        for line in five_lines(ctx):
            print(line, flush=True)
    if args.open and "Интерактивный отчёт (HTML)" in ctx.artifacts:
        webbrowser.open(ctx.artifacts["Интерактивный отчёт (HTML)"].resolve().as_uri())
    code = gate_code(ctx, args.gate or args.fail_on == "blocker", con)
    if args.fail_on == "partial" and code == 0:
        v = ((ctx.rv.depth or {}).get("verdict") or {}).get("development", "")
        if v in ("нельзя", "с оговорками"):
            print(f"Гейт (partial): NO-GO — разработку начинать {v}", flush=True)
            code = 1
    return 3 if code == 0 and getattr(ctx, "fallback_rules", False) else code


def five_lines(ctx) -> list[str]:
    """v13+: итог прогона в 5 строк — вердикт, 3 главных блокера, число замечаний, время и вызовы, пути к файлам."""
    rv = ctx.rv
    v = (rv.depth or {}).get("verdict") or {}
    fs = [(rr.req.doc_id or rr.req.rid, f) for rr in rv.req_results for f in rr.findings] + \
         [(f"S-{i:02d}", f) for i, f in enumerate(rv.set_findings, 1)]
    crit = [(w, f) for w, f in fs if f.severity == "critical"]
    top = "; ".join(f"{w}: {' '.join(f.problem.split())[:70]}" for w, f in crit[:3]) or "нет"
    cnt = {s: sum(f.severity == s for _, f in fs) for s in ("critical", "major", "minor")}
    p = ctx.passport
    files = ", ".join(str(x) for k, x in ctx.artifacts.items() if k.startswith(("Отчёт (Markdown)", "Данные (JSON)",
                                                                                  "Интерактивный отчёт")))
    return ["── Итог ──",
            f"1. Вердикт: разработка — {v.get('development', '—')}, тестирование — {v.get('testing', '—')}",
            f"2. Главные блокеры: {top}",
            f"3. Замечаний {len(fs)}: критичных {cnt['critical']}, существенных {cnt['major']}, незначительных {cnt['minor']}",
            f"4. Время {p.get('duration_s', '—')} с, обращений к модели {p.get('calls', 0)} ({p.get('model', '')})",
            f"5. Файлы: {files}"]


def _service(argv: list[str]) -> int:
    """`verify <report.json> <вход>` и `doctor [--live] [--env ФАЙЛ]`."""
    import argparse as _ap
    import os

    from dotenv import load_dotenv

    cmd, rest = argv[0], argv[1:]
    if cmd == "verify":
        p = _ap.ArgumentParser(prog="review.py verify", description="перепроверка отчёта по исходному документу")
        p.add_argument("report")
        p.add_argument("input")
        a = p.parse_args(rest)
        from .verify_report import run as verify_run

        return verify_run(a.report, a.input)
    p = _ap.ArgumentParser(prog="review.py doctor", description="проверка настройки модели (ключ не печатается)")
    p.add_argument("--live", action="store_true")
    p.add_argument("--env", default=None)
    a = p.parse_args(rest)
    load_dotenv(a.env or ROOT / ".env")
    os.environ.setdefault("LLM_MIN_INTERVAL", "0")
    from .doctor import run as doctor_run

    return doctor_run(live=a.live)


def gate_code(ctx, gate: bool, con=None) -> int:
    """v12: коды выхода для CI. 0 — можно / с оговорками; 1 — нельзя (есть критичные замечания), только с --gate.
    Остальные коды — до отчёта: 2 — файл не найден или формат не поддерживается (и ошибка настройки модели),
    3 — файл не читается или в нём нет требований, 4 — ошибка обращения к модели."""
    v = ((ctx.rv.depth or {}).get("verdict") or {}).get("development", "")
    crit = sum(f.severity == "critical" for rr in ctx.rv.req_results for f in rr.findings) + \
        sum(f.severity == "critical" for f in ctx.rv.set_findings)
    if not gate:
        return 0
    verdict = "NO-GO" if v == "нельзя" else "GO"
    msg = f"Гейт: {verdict} — разработку начинать {v or 'можно'} (критичных замечаний: {crit})"
    if con is not None and verdict == "NO-GO":
        con.error(msg)
    else:
        print(msg, flush=True)
    return 1 if verdict == "NO-GO" else 0


def _rules_hint(args) -> str:
    """Подсказка, как получить отчёт без ключа: только детерминированные правила (без модели)."""
    return ("Без ключа можно проверить документ только правилами агента (без модели):\n"
            f"  LLM_PROVIDER=rules python review.py \"{args.input}\" \"{args.output}\"\n"
            "  (Windows PowerShell: $env:LLM_PROVIDER=\"rules\"; python review.py …)")


if __name__ == "__main__":
    raise SystemExit(main())
