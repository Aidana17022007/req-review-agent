"""v13: независимая проверка находок отчёта — другая модель вслепую и человек.

Запуск:  VERIFY_MODEL=openai:deepseek-chat python bench/verify_findings.py [ОТЧЁТ.json] [--write] [--all]
         (VERIFY_MODEL — «провайдер:модель» другой модели; ключ этого провайдера — в .env, в чат его не вставлять)
По умолчанию проверяется отчёт для сдачи reports/requirements-report.json, существенные и критичные замечания
(--all — и незначительные). Проверяющая модель видит только текст требования, цитату и формулировку проблемы — не
видит серьёзность, источник, уверенность и вывод агента. Промпт фиксирован (SYSTEM ниже), ответ: «да» / «нет» /
«спорно» + почему. Итог: bench/real/verify.json и раздел в bench/RESULTS.md (с --write).
Ручная проверка: bench/real/human_check.md — те же замечания, колонка «Человек» (да / нет / спорно) заполняется
вручную и сохраняется при пересборке (по ключу строки).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
HUMAN = HERE / "real" / "human_check.md"
BATCH = 10

SYSTEM = """Ты — независимый эксперт по требованиям (ISO/IEC/IEEE 29148). Тебе дают фрагменты документа требований и
замечания к ним. Для КАЖДОГО замечания реши: это настоящий дефект требований? «да» — проблема реально есть в
приведённом тексте и мешает реализации или проверке; «нет» — проблемы нет или она надумана; «спорно» — зависит от
контекста, которого нет. Оценивай только по тексту. Пиши по-русски, коротко. Верни ТОЛЬКО JSON:
{"items":[{"n":1,"verdict":"да|нет|спорно","why":"..."}]}"""


def _key(where: str, problem: str) -> str:
    return hashlib.sha1(f"{where}|{' '.join(problem.split())[:200]}".encode()).hexdigest()[:10]


def items_of(report: dict, include_minor: bool = False) -> list[dict]:
    reqs = {r["rid"]: r for r in report.get("requirements", [])}
    out = []
    for r in report.get("requirements", []):
        for f in r.get("findings", []):
            if include_minor or f.get("severity") != "minor":
                out.append({"where": r.get("doc_id") or r["rid"], "text": r["text"][:600], "quote": f.get("quote", ""),
                            "problem": f.get("problem", ""), "severity": f.get("severity")})
    for i, f in enumerate(report.get("set_findings", []), 1):
        if include_minor or f.get("severity") != "minor":
            ctx = " | ".join(f"{x['req_id']}: {reqs[x['req_id']]['text'][:300]}" if x["req_id"] in reqs else x.get("quote", "")
                             for x in f.get("refs", []))
            out.append({"where": f"S-{i:02d}", "text": ctx[:900], "quote": " / ".join(x.get("quote", "") for x in f.get("refs", [])),
                        "problem": f.get("problem", ""), "severity": f.get("severity")})
    for it in out:
        it["key"] = _key(it["where"], it["problem"])
    return out


def verify(items: list[dict], llm, log=print) -> list[dict]:
    from req_review.parallel import pmap

    batches = [items[i:i + BATCH] for i in range(0, len(items), BATCH)]

    def one(job):
        bi, batch = job
        payload = [{"n": bi * BATCH + k + 1, "requirement_text": x["text"], "quote": x["quote"], "problem": x["problem"]}
                   for k, x in enumerate(batch)]
        try:
            return llm.generate_json(SYSTEM, "ЗАМЕЧАНИЯ (JSON):\n" + json.dumps(payload, ensure_ascii=False, indent=1),
                                     task="verify", context={"items": payload})
        except Exception as e:  # noqa: BLE001 — непроверенное так и помечаем
            log(f"проверка пакета {bi + 1}: {str(e)[:100]}")
            return {}

    got = {}
    for data in pmap(one, list(enumerate(batches))):
        for v in (data or {}).get("items", []) or []:
            try:
                got[int(v.get("n"))] = v
            except (TypeError, ValueError):
                continue
    for n, it in enumerate(items, 1):
        v = got.get(n) or {}
        verdict = str(v.get("verdict", "")).strip().lower().replace("ё", "е")
        it["model_verdict"] = verdict if verdict in ("да", "нет", "спорно") else "не проверено"
        it["model_why"] = str(v.get("why", "")).strip()
    return items


def load_human(path: Path = HUMAN) -> dict[str, str]:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and re.fullmatch(r"[0-9a-f]{10}", cells[0]):
                v = cells[-1].lower()
                out[cells[0]] = next((w for w in ("да", "нет", "спорно") if v.startswith(w)), "")
    return out


def write_human(items: list[dict], path: Path = HUMAN) -> None:
    old = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and re.fullmatch(r"[0-9a-f]{10}", cells[0]):
                old[cells[0]] = cells[-1]
    out = ["# Ручная проверка находок отчёта для сдачи", "",
           "В последней колонке — **да** (настоящий дефект), **нет** или **спорно**, можно с комментарием. Проверяйте по",
           "тексту документа (bench/real/notifications.md), не глядя на вердикт модели. Файл пересобирается",
           "`python bench/verify_findings.py`, вписанное сохраняется по ключу строки. Удобнее — в `bench/real/human_check.html`",
           "(текст требования рядом), затем `python bench/gold_score.py --labels human_labels.json`.", "",
           "| Ключ | Где | Серьёзность | Замечание | Человек |", "|---|---|---|---|---|"]
    for it in items:
        out.append(f"| {it['key']} | {it['where']} | {it['severity']} | {' '.join(it['problem'].split())[:240].replace('|', '/')} | "
                   f"{old.get(it['key'], '')} |")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def summary(items: list[dict], human: dict[str, str]) -> dict:
    from collections import Counter

    mv = Counter(it.get("model_verdict", "не проверено") for it in items)
    hv = Counter(human.get(it["key"], "") for it in items)
    checked = sum(mv[k] for k in ("да", "нет", "спорно"))
    hchecked = sum(hv[k] for k in ("да", "нет", "спорно"))
    return {"total": len(items), "model": dict(mv), "model_checked": checked,
            "model_confirmed_share": mv["да"] / checked if checked else None,
            "human": {k: v for k, v in hv.items() if k}, "human_checked": hchecked,
            "human_confirmed_share": hv["да"] / hchecked if hchecked else None}


def md(s: dict, label: str) -> str:
    pct = lambda x: "—" if x is None else f"{100 * x:.0f} %"  # noqa: E731
    m, h = s["model"], s["human"]
    return "\n".join([
        "## Независимая проверка находок (v13)", "", f"*{label}.* Команда: `python bench/verify_findings.py`.", "",
        "| Кто проверял | Подтверждено «да» | «нет» | «спорно» | Доля «да» |", "|---|---|---|---|---|",
        f"| Другая модель (вслепую) | {m.get('да', 0)} из {s['model_checked']} | {m.get('нет', 0)} | {m.get('спорно', 0)} | "
        f"**{pct(s['model_confirmed_share'])}** |",
        f"| Человек (bench/real/human_check.md) | {h.get('да', 0)} из {s['human_checked']} | {h.get('нет', 0)} | "
        f"{h.get('спорно', 0)} | **{pct(s['human_confirmed_share'])}** |", ""])


def main(argv: list[str] | None = None) -> int:
    import argparse

    from dotenv import load_dotenv

    ap = argparse.ArgumentParser(prog="python bench/verify_findings.py")
    ap.add_argument("report", nargs="?", default=str(ROOT / "reports" / "requirements-report.json"))
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--all", action="store_true", help="включить незначительные замечания")
    a = ap.parse_args(argv)
    load_dotenv(ROOT / ".env")
    from req_review.ensemble import model_env
    from req_review.llm import build_llm_from_env

    report = json.loads(Path(a.report).read_text(encoding="utf-8"))
    items = items_of(report, a.all)
    spec = os.getenv("VERIFY_MODEL", "")
    if spec:
        with model_env(spec):
            llm = build_llm_from_env()
    else:
        llm = build_llm_from_env()
    made_by = report.get("passport", {}).get("model", "")
    if llm.label in made_by:
        print(f"⚠ проверяющая модель {llm.label} совпадает с моделью отчёта — задайте VERIFY_MODEL=провайдер:модель")
    verify(items, llm)
    write_human(items)
    s = summary(items, load_human())
    label = f"Отчёт: {Path(a.report).name} ({made_by}); проверяла: {llm.label}; замечаний: {len(items)}"
    text = md(s, label)
    print(text)
    if a.write:
        (HERE / "real" / "verify.json").write_text(json.dumps({"label": label, "summary": s, "items": items},
                                                              ensure_ascii=False, indent=1), encoding="utf-8")
        with open(HERE / "RESULTS.md", "a", encoding="utf-8") as fh:
            fh.write("\n" + text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
