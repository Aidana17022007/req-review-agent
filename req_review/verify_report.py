"""v13+: `python review.py verify <report.json> <вход>` — независимая перепроверка отчёта по исходному документу.

Что сверяется (без модели, только код):
  1) SHA-256 входного файла = passport.sha256 (отчёт сделан именно по этому файлу);
  2) каждая цитата каждого замечания заново ищется в исходнике (verify.quote_in): к требованию — в тексте требования
     и в документе, к набору — в документе;
  3) число требований: нарезка документа заново (детерминированная, без модели) = числу требований в отчёте
     (если отчёт нарезан моделью — пункт пропускается с пометкой);
  4) счётчики: число замечаний и критичных в отчёте = scores / verdict отчёта.
Код выхода: 0 — всё совпало, 4 — есть расхождение, 2 — нет файла.
"""
from __future__ import annotations

import json
from pathlib import Path


def verify_data(report: dict, doc, split=None) -> dict:
    from .splitter import split_requirements
    from .verify import quote_in

    reqs = {r["rid"]: r for r in report.get("requirements", [])}
    problems: list[str] = []
    total = ok = 0
    for r in report.get("requirements", []):
        for f in r.get("findings", []):
            total += 1
            q = f.get("quote", "")
            if q and (quote_in(q, r.get("text", "")) or quote_in(q, doc.text)) and quote_in(q, doc.text):
                ok += 1
            else:
                problems.append(f"цитата не найдена: {r['rid']} «{q[:80]}»")
    for i, f in enumerate(report.get("set_findings", []), 1):
        for ref in f.get("refs", []):
            total += 1
            q = ref.get("quote", "")
            src = reqs.get(ref.get("req_id"), {}).get("text", "") if ref.get("req_id") in reqs else ""
            if q and (quote_in(q, doc.text) or quote_in(q, src)):
                ok += 1
            else:
                problems.append(f"цитата не найдена: S-{i:02d} «{q[:80]}»")
    p = report.get("passport", {})
    sha_ok = p.get("sha256") == doc.sha256
    if not sha_ok:
        problems.append(f"SHA-256 входа не совпадает: в отчёте {str(p.get('sha256', ''))[:16]}…, у файла {doc.sha256[:16]}…")
    split = split or split_requirements(doc)
    n_report = len(report.get("requirements", []))
    reqs_ok = None
    if p.get("split_method") in ("ids", "modal"):
        reqs_ok = len(split.requirements) == n_report
        if not reqs_ok:
            problems.append(f"требований в отчёте {n_report}, при повторной нарезке {len(split.requirements)}")
    fs = [f for r in report.get("requirements", []) for f in r.get("findings", [])] + report.get("set_findings", [])
    n_crit = sum(f.get("severity") == "critical" for f in fs)
    verdict = (report.get("verdict") or {}).get("development")
    counts_ok = verdict is None or (verdict == "нельзя") == (n_crit > 0)
    if not counts_ok:
        problems.append(f"вердикт «{verdict}» не согласуется с числом критичных замечаний ({n_crit})")
    return {"ok": not problems, "quotes_total": total, "quotes_ok": ok, "sha_ok": sha_ok, "requirements_ok": reqs_ok,
            "requirements": n_report, "findings": len(fs), "critical": n_crit, "counts_ok": counts_ok,
            "problems": problems[:50]}


def run(report_path: str, input_path: str, out=print) -> int:
    from .reader import read_document

    rp, ip = Path(report_path), Path(input_path)
    if not rp.exists() or not ip.exists():
        out(f"Ошибка: нет файла {rp if not rp.exists() else ip}")
        return 2
    report = json.loads(rp.read_text(encoding="utf-8"))
    res = verify_data(report, read_document(ip))
    mark = "✅" if res["ok"] else "❌"
    out(f"{mark} verify: цитаты {res['quotes_ok']} из {res['quotes_total']} найдены в исходнике · SHA-256 "
        f"{'совпадает' if res['sha_ok'] else 'НЕ совпадает'} · требований {res['requirements']}"
        + ("" if res["requirements_ok"] is None else (" (совпадает с повторной нарезкой)" if res["requirements_ok"]
                                                     else " (НЕ совпадает)"))
        + f" · замечаний {res['findings']}, критичных {res['critical']}")
    for pr in res["problems"]:
        out(f"   - {pr}")
    return 0 if res["ok"] else 4
