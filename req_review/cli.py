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
    ap.add_argument("--no-tests", action="store_true", help="не включать тест-пробу (Gherkin) в отчёт")
    ap.add_argument("--pdf", dest="pdf", action="store_true", default=None,
                    help="записать PDF-версию отчёта рядом с .md (в профиле deep — по умолчанию)")
    ap.add_argument("--no-pdf", dest="pdf", action="store_false", help="не создавать PDF-версию отчёта")
    for name, what in (("html", "интерактивный HTML-отчёт"), ("fixed", "исправленный документ"), ("xlsx", "Excel-трассировку"),
                       ("jira", "CSV для Jira"), ("json", "report.json")):
        ap.add_argument(f"--no-{name}", action="store_true", help=f"не создавать {what}")
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
    args = build_parser().parse_args(argv)

    import os

    from dotenv import load_dotenv

    load_dotenv(args.env or ROOT / ".env")

    from .console import Console
    from .llm import LLMError
    from .pipeline import apply_profile_env, run

    profile = args.profile or os.getenv("REQLENS_PROFILE", "fast")
    opts = Options(
        profile=profile,
        html=not args.no_html, fixed=not args.no_fixed, xlsx=not args.no_xlsx, jira=not args.no_jira,
        json=not args.no_json, tests=not args.no_tests, critic=args.critic, rescore=args.rescore,
        domain=args.domain or os.getenv("REQLENS_DOMAIN", "fintech"), compare=args.compare,
        batch_size=int(os.getenv("LLM_BATCH_SIZE", "20")), pdf=args.pdf,
    )
    con = Console(quiet=args.quiet)
    apply_profile_env(profile)
    try:
        from .llm import build_llm_from_env

        label = build_llm_from_env().label
    except LLMError as e:
        con.error(f"Ошибка конфигурации LLM: {e}\n{_rules_hint(args)}")
        return 2
    con.banner(args.input, label, profile)
    try:
        ctx = run(args.input, args.output, opts, log=con.log, step=con.step)
    except (FileNotFoundError, ValueError) as e:
        con.error(f"Ошибка: {e}")
        return 2 if isinstance(e, FileNotFoundError) or "не поддерживается" in str(e) or "Домен" in str(e) else 3
    except LLMError as e:
        msg = f"Ошибка обращения к модели: {e}"
        if any(x in str(e) for x in ("HTTP 400", "HTTP 401", "HTTP 403", "API key", "API_KEY")):
            msg += "\nПохоже, ключ неверен или не подходит для этой модели. " + _rules_hint(args)
        con.error(msg)
        return 4
    if args.json_out:
        from .exports import write_json

        write_json(ctx, Path(args.json_out))
    con.summary(ctx)
    if args.open and "Интерактивный отчёт (HTML)" in ctx.artifacts:
        webbrowser.open(ctx.artifacts["Интерактивный отчёт (HTML)"].resolve().as_uri())
    return 0


def _rules_hint(args) -> str:
    """Подсказка, как получить отчёт без ключа: только детерминированные правила (без модели)."""
    return ("Без ключа можно проверить документ только правилами агента (без модели):\n"
            f"  LLM_PROVIDER=rules python review.py \"{args.input}\" \"{args.output}\"\n"
            "  (Windows PowerShell: $env:LLM_PROVIDER=\"rules\"; python review.py …)")


if __name__ == "__main__":
    raise SystemExit(main())
