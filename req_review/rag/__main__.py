"""CLI RAG: python -m req_review.rag build [kb/] | search "запрос" [-k 5] [--kind standards|law_kz|patterns]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from .index import KB_DIR, ROOT, get_kb


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(prog="python -m req_review.rag")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="собрать индекс базы знаний")
    b.add_argument("kb", nargs="?", default=str(KB_DIR))
    s = sub.add_parser("search", help="поиск по базе знаний")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--kind", default=None)
    a = ap.parse_args(argv)
    kb = get_kb(Path(getattr(a, "kb", KB_DIR)))
    if kb is None:
        print("База знаний недоступна (RAG=off или нет kb/).")
        return 1
    if a.cmd == "build":
        print(f"Индекс: {len(kb.chunks)} фрагментов, режим поиска: {kb.mode}")
        return 0
    for c, sc in kb.search(a.query, a.k, a.kind):
        print(f"[{sc:.3f}] {c.source} · {c.section}\n    {c.text[:220]}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
