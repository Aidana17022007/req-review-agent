"""Точка входа: python review.py <файл требований> <файл отчёта>"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import __version__

ROOT = Path(__file__).resolve().parent.parent


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


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(
        prog="review.py",
        description="ИИ-агент статической проверки документа требований (ISO/IEC/IEEE 29148, IEEE 830).",
    )
    ap.add_argument("input", help="путь к документу требований (.pdf, .docx, .md, .txt)")
    ap.add_argument("output", help="путь к файлу отчёта (.md)")
    ap.add_argument("--env", default=None, help="путь к .env (по умолчанию .env в корне проекта)")
    ap.add_argument("--json", dest="json_out", default=None, help="дополнительно сохранить сырые результаты в JSON")
    args = ap.parse_args(argv)

    from dotenv import load_dotenv

    load_dotenv(args.env or ROOT / ".env")

    from .checker import llm_split, run_review
    from .llm import LLMError, build_llm_from_env
    from .reader import read_document
    from .report import build_report
    from .splitter import split_requirements

    started = datetime.now().astimezone()
    t0 = time.monotonic()
    try:
        llm = build_llm_from_env()
    except LLMError as e:
        print(f"Ошибка конфигурации LLM: {e}", file=sys.stderr)
        return 2

    print(f"[1/5] Чтение документа: {args.input}")
    try:
        doc = read_document(args.input)
    except (FileNotFoundError, ValueError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2
    print(f"      «{doc.title}», строк: {len(doc.lines)}")

    print("[2/5] Нарезка требований")
    split = split_requirements(doc)
    if not split.requirements:
        print("      правила ничего не нашли — нарезка моделью")
        try:
            split.requirements = llm_split(doc, llm)
            split.method = "llm"
        except LLMError as e:
            print(f"Ошибка: {e}", file=sys.stderr)
            return 3
    if not split.requirements:
        print("Ошибка: в документе не найдено ни одного требования.", file=sys.stderr)
        return 3
    print(f"      выделено требований: {len(split.requirements)} (способ: {split.method})")

    print(f"[3/5] Проверка каждого требования ({llm.label})")
    batch = int(os.getenv("LLM_BATCH_SIZE", "8"))
    print("[4/5] Проверка набора требований выполняется следом")
    try:
        rv = run_review(doc, split, llm, batch_size=batch, log=lambda m: print("     " + m, flush=True))
    except LLMError as e:
        print(f"Ошибка обращения к модели: {e}", file=sys.stderr)
        return 4

    print("[5/5] Запись отчёта")
    report = build_report(rv, model_label=llm.label, agent_version=agent_version(), started=started,
                          duration_s=time.monotonic() - t0, llm_stats=llm.stats, input_path=args.input)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    if args.json_out:
        import dataclasses
        import json

        def conv(o):
            if dataclasses.is_dataclass(o):
                return {k: conv(v) for k, v in dataclasses.asdict(o).items() if k not in ("doc",)}
            return str(o)

        data = {
            "requirements": [dataclasses.asdict(r) for r in split.requirements],
            "req_results": [{"rid": rr.req.rid, "findings": [dataclasses.asdict(f) for f in rr.findings],
                             "rewrite": rr.rewrite, "llm_checked": rr.llm_checked} for rr in rv.req_results],
            "set_findings": [dataclasses.asdict(f) for f in rv.set_findings],
            "dropped": rv.dropped,
        }
        Path(args.json_out).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    n_f = sum(len(r.findings) for r in rv.req_results) + len(rv.set_findings)
    print(f"Готово: {out} — требований {len(split.requirements)}, нарушений {n_f}, "
          f"обращений к модели {llm.stats.calls}, отброшено неподтверждённых цитат {len(rv.dropped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
