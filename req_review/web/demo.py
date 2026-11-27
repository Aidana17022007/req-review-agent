"""Режим «Демо» для защиты: Studio проигрывает сохранённый реальный прогон без сети и без обращения к модели.

    python -m req_review.web --demo reports/report.json [--demo-after reports/v2/report.json]

Источник — артефакты настоящего прогона: report.json (требования, замечания, баллы) и report.html рядом с ним
(таймлайн шагов ctx.trace с длительностями). События те же, что у живого прогона: step / split / batch_start /
batch_done / log / done, — поэтому интерфейс не отличает демо от реального запуска, а на экране это честно подписано.
--demo-after — отчёт исправленной версии: тогда «До / После» тоже работает офлайн.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path

ORDER = {"critical": 0, "major": 1, "minor": 2}
TARGET_S = 18.0  # длительность проигрывания: реальный прогон с паузами API сжимается до ~18 с
MIN_STEP = 0.5  # минимальная длительность шага на экране, с
DEFAULT_DUR = [0.6, 0.6, 6.0, 2.0, 1.5, 1.5, 1.0]


@dataclass
class DemoRun:
    json_path: Path
    after: Path | None = None

    @property
    def data(self) -> dict:
        return json.loads(self.json_path.read_text(encoding="utf-8"))

    def artifacts(self, path: Path | None = None) -> dict[str, Path]:
        """Файлы того же прогона рядом с report.json: <stem>.md/.html/.json, <stem>_*.{md,xlsx,csv,diff,feature}."""
        p = path or self.json_path
        stem, d = p.stem, p.parent
        names = {".md": "Отчёт (Markdown)", ".html": "Интерактивный отчёт (HTML)", ".json": "Данные (JSON)",
                 "_requirements_fixed.md": "Исправленный документ", "_traceability.xlsx": "Трассировка (Excel)",
                 "_jira_import.csv": "Импорт в Jira (CSV)", "_fixed.diff": "Diff исправлений", "_tests.feature": "Тесты (.feature)"}
        return {label: d / (stem + suf) for suf, label in names.items() if (d / (stem + suf)).exists()}

    def trace(self, path: Path | None = None) -> list[float]:
        """Длительности 7 шагов из встроенных в report.html данных (таймлайн настоящего прогона)."""
        html = (path or self.json_path).with_suffix(".html")
        try:
            m = re.search(r'<script type="application/json" id="data">(.*?)</script>', html.read_text(encoding="utf-8"), re.S)
            steps = json.loads(m.group(1).replace("<\\/", "</"))["trace"]
            durs = [float(s.get("dur") or 0) for s in steps][:7]
            if len(durs) == 7 and sum(durs) > 0:
                return durs
        except Exception:
            pass
        return list(DEFAULT_DUR)

    def describe(self) -> dict:
        d = self.data
        return {"available": True, "document": d.get("passport", {}).get("document", ""), "model": d.get("passport", {}).get("model", ""),
                "reqs": sum(1 for r in d.get("requirements", []) if r.get("kind", "requirement") == "requirement"),  # v8: без строк API и приёмки
                "started": d.get("passport", {}).get("started", ""), "has_after": bool(self.after)}


def _rows(data: dict) -> list[dict]:
    out = []
    for r in data["requirements"]:
        worst = min((f["severity"] for f in r["findings"]), key=ORDER.get, default="ok")
        out.append({"rid": r["rid"], "doc_id": r.get("doc_id"), "text": r["text"][:200], "score": r["score"], "worst": worst,
                    "n": len(r["findings"]), "test": (r.get("test") or {}).get("possible")})
    return out


def _summary(data: dict, has_fixed: bool) -> dict:
    sc = data["scores"]
    crit = sum(1 for r in data["requirements"] for f in r["findings"] if f["severity"] == "critical") + \
        sum(1 for f in data.get("set_findings", []) if f["severity"] == "critical")
    return {"score": sc["document"], "readiness": sc["readiness"], "reqs": sum(1 for r in data["requirements"] if r.get("kind", "requirement") == "requirement"), "calls": data["passport"].get("calls", 0),
            "critical": crit, "tests_ok": sc["tests"]["ok"], "tests_total": sc["tests"]["total"], "rows": _rows(data),
            "has_fixed": has_fixed, "document": data["passport"].get("document", ""), "demo": True}


def replay(job, demo: DemoRun, source: Path | None = None, compare_with: Path | None = None, batch: int = 4) -> None:
    """Проиграть прогон в job (те же события, что у живого прогона). Копирует артефакты в папку задачи."""
    src = source or demo.json_path
    data = json.loads(src.read_text(encoding="utf-8"))
    durs = demo.trace(src)
    k = min(1.0, TARGET_S / max(0.1, sum(durs)))
    durs = [max(MIN_STEP, d * k) for d in durs]

    def work():
        try:
            job.dir.mkdir(parents=True, exist_ok=True)
            arts = {}
            for label, p in demo.artifacts(src).items():
                name = "report" + p.name[len(src.stem):]
                shutil.copyfile(p, job.dir / name)
                arts[label] = name
            job.push("log", msg=f"Режим «Демо»: проигрывается сохранённый прогон ({data['passport'].get('model', '')}, "
                                f"{data['passport'].get('started', '')}) — модель не вызывается")
            reqs = data["requirements"]
            for i in range(7):
                job.push("step", i=i)
                if i == 0:
                    job.push("log", msg=f"«{data['passport'].get('document', '')}»")
                if i == 1:
                    time.sleep(durs[1] / 2)
                    job.push("log", msg=f"выделено требований: {len(reqs)}")
                    job.push("split", total=len(reqs))
                    time.sleep(durs[1] / 2)
                    continue
                if i == 2:
                    batches = [reqs[j:j + batch] for j in range(0, len(reqs), batch)] or [[]]
                    for b in batches:
                        if not b:
                            continue
                        job.push("batch_start", reqs=[{"rid": r["rid"], "doc_id": r.get("doc_id"), "text": r["text"][:200], "section": r.get("section", "")} for r in b])
                        job.push("log", msg=f"  проверка требований: {b[0]['rid']}–{b[-1]['rid']}")
                        time.sleep(durs[2] / len(batches))
                        job.push("batch_done", results=[{"rid": r["rid"], "n": len(r["findings"]),
                                                         "worst": min((f["severity"] for f in r["findings"]), key=ORDER.get, default="ok"),
                                                         "test": (r.get("test") or {}).get("possible")} for r in b])
                    continue
                time.sleep(durs[i])
            job.artifacts = arts
            job.summary = _summary(data, any(v.endswith("_requirements_fixed.md") for v in arts.values()))
            if compare_with:
                from .compare import diff_reports

                job.summary["compare"] = diff_reports(json.loads(compare_with.read_text(encoding="utf-8")), data)
            job.push("done", artifacts=job.artifacts, summary=job.summary)
        except Exception as e:  # демо не должно «падать молча»
            job.error = str(e)[:500]
            job.push("error", msg=job.error, code="error")
        finally:
            job.done = True

    threading.Thread(target=work, daemon=True).start()
