"""Комментарий ReqLens в Pull Request: что изменилось в требованиях между base и веткой PR.

    python scripts/pr_comment.py --new pr/report.json [--old base/report.json] --doc docs/requirements.md \
        [--artifact-url URL] [--out comment.md] [--gate]

Сравнивает подтверждённые замечания двух прогонов агента: новые дефекты (появились в PR) и исправленные (были в base,
исчезли). Ключ замечания — критерий + нормализованная цитата (к требованию) или вид + цитаты (к набору), поэтому
сдвиг строк и перенумерация требований не дают ложных «новых». Комментарий — Markdown до 60 строк с меткой
<!-- reqlens-pr-review -->, по которой workflow обновляет один и тот же комментарий. --gate: код возврата 1, если в PR
появился новый критичный дефект (для обязательной проверки PR).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MARKER = "<!-- reqlens-pr-review -->"
MAX_LINES = 60
SEV = {"critical": "🔴", "major": "🟠", "minor": "🟡"}
ORDER = {"critical": 0, "major": 1, "minor": 2}


def _norm(s: str) -> str:
    s = str(s or "").lower().replace("ё", "е")
    return re.sub(r"[\s«»\"'`*_.,;:()\-–—]+", " ", s).strip()


def findings(data: dict) -> list[dict]:
    """Плоский список замечаний с ключом сравнения, меткой требования, строкой и цитатой."""
    out = []
    for r in data.get("requirements", []):
        for f in r.get("findings", []):
            line = (f.get("span") or {}).get("line") or r.get("line_start")
            out.append({"key": ("req", f.get("criterion"), _norm(f.get("quote"))), "severity": f.get("severity", "minor"),
                        "label": r.get("doc_id") or r.get("rid"), "line": line, "quote": f.get("quote", ""),
                        "problem": f.get("problem", "")})
    for f in data.get("set_findings", []):
        refs = f.get("refs") or []
        line = next(((x.get("span") or {}).get("line") for x in refs if (x.get("span") or {}).get("line")), None)
        out.append({"key": ("set", f.get("kind"), tuple(sorted(_norm(x.get("quote")) for x in refs))),
                    "severity": f.get("severity", "minor"), "label": "набор", "line": line,
                    "quote": refs[0].get("quote", "") if refs else "", "problem": f.get("problem", "")})
    return out


def summary(data: dict | None) -> dict:
    if not data:
        return {}
    fs = findings(data)
    v = data.get("verdict") or {}
    return {"dev": v.get("development", "—"), "test": v.get("testing", "—"),
            "critical": sum(1 for f in fs if f["severity"] == "critical"), "total": len(fs),
            "model": (data.get("passport") or {}).get("model", "")}


def diff(old: dict | None, new: dict) -> tuple[list[dict], list[dict]]:
    nf = findings(new)
    if not old:
        return nf, []
    of = findings(old)
    ok, nk = {f["key"] for f in of}, {f["key"] for f in nf}
    added = [f for f in nf if f["key"] not in ok]
    fixed = [f for f in of if f["key"] not in nk]
    return added, fixed


def _short(s: str, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _item(f: dict) -> str:
    where = f"строка {f['line']}" if f.get("line") else "документ"
    return (f"- {SEV.get(f['severity'], '•')} **{f['label']}** ({where}) — {_short(f['problem'], 140)}"
            + (f" — «{_short(f['quote'], 70)}»" if f.get("quote") else ""))


def build(new: dict, old: dict | None, doc: str, artifact_url: str = "", rules_only: bool = False) -> tuple[str, bool]:
    added, fixed = diff(old, new)
    added.sort(key=lambda f: ORDER.get(f["severity"], 3))
    fixed.sort(key=lambda f: ORDER.get(f["severity"], 3))
    s_new, s_old = summary(new), summary(old)
    gate = any(f["severity"] == "critical" for f in added) if old else s_new.get("critical", 0) > 0
    L = [MARKER, f"## ReqLens · ревью требований: `{doc}`", ""]
    if old:
        L += ["| | Было (base) | Стало (PR) |", "|---|---|---|",
              f"| Разработка | {s_old['dev']} | **{s_new['dev']}** |",
              f"| Тестирование | {s_old['test']} | **{s_new['test']}** |",
              f"| Критичных дефектов | {s_old['critical']} | **{s_new['critical']}** |",
              f"| Всего замечаний | {s_old['total']} | **{s_new['total']}** |", ""]
    else:
        L += [f"Документ новый — сравнивать не с чем. Разработка: **{s_new['dev']}**, тестирование: **{s_new['test']}**, "
              f"критичных дефектов: **{s_new['critical']}**, всего замечаний: **{s_new['total']}**.", ""]
    shown_new, shown_fixed = added[:8], fixed[:6]
    if added:
        L += [f"**🆕 Новые дефекты ({len(added)})**" if old else f"**Дефекты ({len(added)})**", *[_item(f) for f in shown_new], ""]
    elif old:
        L += ["**🆕 Новых дефектов нет.**", ""]
    if fixed:
        L += [f"**✅ Исправлены ({len(fixed)})**", *[_item(f) for f in shown_fixed], ""]
    rest = added[len(shown_new):] + fixed[len(shown_fixed):]
    if rest:
        L += [f"<details><summary>Ещё {len(rest)}</summary>", "", *[_item(f) for f in rest[:20]], "", "</details>", ""]
    mode = "только детерминированные правила (секрета GEMINI_API_KEY нет)" if rules_only else (s_new.get("model") or "модель")
    tail = f"Режим: {mode}."
    if artifact_url:
        tail += f" Полный отчёт (md, html, pdf): [артефакт прогона]({artifact_url})."
    if gate:
        tail += " ⛔ В PR появился новый критичный дефект." if old else " ⛔ В документе есть критичные дефекты."
    L.append(tail)
    if len(L) > MAX_LINES:  # жёсткий предел длины комментария: детали сокращаются, итог остаётся
        L = L[: MAX_LINES - 2] + ["", tail]
    return "\n".join(L) + "\n", gate


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Комментарий ReqLens в Pull Request")
    ap.add_argument("--new", required=True, help="report.json прогона ветки PR")
    ap.add_argument("--old", help="report.json прогона base (если документ уже был)")
    ap.add_argument("--doc", required=True, help="путь к документу в репозитории (для заголовка)")
    ap.add_argument("--artifact-url", default="")
    ap.add_argument("--rules-only", action="store_true", help="прогон без модели (нет секрета)")
    ap.add_argument("--out", default="")
    ap.add_argument("--gate", action="store_true", help="код 1 при новом критичном дефекте")
    a = ap.parse_args(argv)
    new = json.loads(Path(a.new).read_text(encoding="utf-8"))
    old = json.loads(Path(a.old).read_text(encoding="utf-8")) if a.old and Path(a.old).exists() else None
    text, gate = build(new, old, a.doc, a.artifact_url, a.rules_only)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 1 if (a.gate and gate) else 0


if __name__ == "__main__":
    raise SystemExit(main())
