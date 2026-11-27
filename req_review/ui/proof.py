"""v15: «Доказательства» — одни и те же цифры для сайта (scripts/build_site.py) и стартового экрана Studio.

Каждое значение берётся из файла репозитория, который пересчитывается командой (она — в строке рядом). Нет файла или
нужного поля — значение None, и интерфейс пишет «появится после прогона»: ничего не выдумывается и не округляется
в лучшую сторону (точность, пока проверены не все замечания, — диапазон «строгая – по проверенным»).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PENDING = "появится после прогона"


def _load(root: Path, rel: str) -> dict | None:
    p = root / rel
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None


def pct(x) -> str:
    """0.956 → «96 %» (обычное округление: 0.5 — вверх, как в bench/RESULTS.md)."""
    return f"{int(100 * x + 0.5)} %" if isinstance(x, (int, float)) else "—"


def _section(text: str, head: str) -> str:
    i = text.find(head)
    if i < 0:
        return ""
    j = text.find("\n## ", i + len(head))
    return text[i:j if j >= 0 else len(text)]


def md_rows(sec: str) -> list[list[str]]:
    """Строки Markdown-таблиц раздела (без шапки-разделителя), ячейки без ** и пробелов."""
    out = []
    for ln in sec.splitlines():
        s = ln.strip()
        if not s.startswith("|") or re.fullmatch(r"[\s|:-]+", s):
            continue
        out.append([re.sub(r"\*\*(.+?)\*\*", r"\1", c).strip() for c in s.strip("|").split("|")])
    return out


def _row(rows: list[list[str]], label: str) -> list[str] | None:
    return next((r for r in rows if r and r[0].lower().startswith(label.lower())), None)


def _organizers(root: Path) -> dict | None:
    rep = _load(root, "reports/requirements-report.json")
    if not rep or not (root / "bench" / "real_eval.py").exists():
        return None
    try:
        sys.path.insert(0, str(root / "bench"))
        from real_eval import evaluate  # noqa: PLC0415 — код оценки бенчмарка, тот же, что в README

        return evaluate(rep)
    except Exception:  # noqa: BLE001 — нет ключа дефектов / другой формат: строка «появится после прогона»
        return None


def evidence(root: Path | None = None) -> list[dict]:
    """Строки таблицы «Доказательства»: {"id","title","value","detail","source","cmd"}; value None — ещё не посчитано."""
    root = Path(root or ROOT)
    rows: list[dict] = []

    def add(id_, title, value, detail, source, cmd):
        rows.append({"id": id_, "title": title, "value": value, "detail": detail if value else "", "source": source, "cmd": cmd})

    ev = _organizers(root)
    add("organizers", "Документ организаторов: ожидаемые дефекты",
        f"{ev['found']} из {ev['total']}" if ev else None,
        f"критичных {ev['critical_found']} из {ev['critical_total']}" if ev else "",
        "reports/requirements-report.json", "python bench/real_eval.py")

    g = _load(root, "bench/score.json")
    if g and "recall" in g and "precision" in g:
        ci = g.get("recall_ci") or []
        rec = f"{pct(g['recall'])} ({g.get('found', '—')} из {g.get('total', '—')})"
        detail = f"95 % интервал {pct(ci[0])[:-2]}–{pct(ci[1])}" if len(ci) == 2 else ""
        if g.get("critical_total"):
            detail += f"{' · ' if detail else ''}критичных и противоречий {g.get('critical_found')} из {g['critical_total']}"
        add("gold_recall", "Эталон из 150 дефектов: полнота", rec, detail, "bench/score.json", "python bench/gold_score.py")
        checked = g.get("judged")
        total_f = g.get("findings") or ((g.get("judged") or 0) + (g.get("unjudged") or 0)) or None
        if g.get("unjudged") and isinstance(g.get("precision_strict"), (int, float)):
            prec = f"от {pct(g['precision_strict'])[:-2]} до {pct(g['precision'])}"
            pd = (f"проверено {checked} из {total_f} существенных замечаний"
                  + (f", верны {g['correct']}" if g.get("correct") is not None else "")
                  + f"; ещё {g['unjudged']} не проверены — нижняя граница считает их ложными")
        else:
            prec, pd = pct(g["precision"]), (f"проверено {checked} из {total_f} существенных замечаний" if checked else "")
        add("gold_precision", "Эталон из 150 дефектов: проверенная точность", prec, pd, "bench/score.json", "python bench/gold_score.py")
    else:
        add("gold_recall", "Эталон из 150 дефектов: полнота", None, "", "bench/score.json", "python bench/gold_score.py")
        add("gold_precision", "Эталон из 150 дефектов: проверенная точность", None, "", "bench/score.json", "python bench/gold_score.py")

    res_md = root / "bench" / "RESULTS.md"
    text = res_md.read_text(encoding="utf-8") if res_md.exists() else ""
    blind = _section(text, "## Слепые документы")
    meta = next((ln for ln in blind.splitlines() if ln.strip().startswith("*Дата:*")), "")
    brows = md_rows(blind) if blind and "mock" not in meta.lower() else []
    agent = _row(brows[1:], "ReqLens") or (brows[1] if len(brows) > 1 else None)
    add("blind", "Слепой набор: документы, которых команда не видела",
        " · ".join(f"{h} {v}" for h, v in zip(brows[0][1:], agent[1:]) if v)[:160] if agent and brows else None,
        agent[0] if agent else "", "bench/RESULTS.md", "python bench/blind_eval.py")

    base = _load(root, "bench/baseline/results.json")
    if base and all(k in base for k in ("B_bare", "C_reqlens")):
        b, c = base["B_bare"], base["C_reqlens"]
        bo, co = b.get("organizers", {}), c.get("organizers", {})
        add("baseline", "«Голая» модель против ReqLens (документ организаторов)",
            f"{bo.get('found', '—')} из {bo.get('total', '—')} → {co.get('found', '—')} из {co.get('total', '—')}",
            f"полнота на бенчмарке {pct(b.get('bench', {}).get('recall'))} → {pct(c.get('bench', {}).get('recall'))}; "
            "один промпт в ту же модель против агента", "bench/baseline/results.json", "python bench/baseline_eval.py")
    else:
        add("baseline", "«Голая» модель против ReqLens (документ организаторов)", None, "", "bench/baseline/results.json",
            "python bench/baseline_eval.py")

    ext = root / "examples" / "answers" / "external" / "RESULTS.md"
    er = _row(md_rows(ext.read_text(encoding="utf-8")), "Тип ответа определён верно") if ext.exists() else None
    add("answers", "Чужие ответы аналитика: тип ответа определён верно", er[1] if er and len(er) > 1 else None,
        "ответы написал человек вне команды" if er else "", "examples/answers/external/RESULTS.md", "python bench/answers_eval.py")

    rep = _load(root, "reports/requirements-report.json")
    pp = (rep or {}).get("passport") or {}
    te = pp.get("time_estimate") or {}
    if pp.get("duration_s"):
        sec = float(pp["duration_s"])
        val = f"{int(sec // 60)} мин {int(sec % 60 + 0.5)} с" if sec >= 60 else f"{sec:g} с"
        det = f"обращений к модели {pp.get('calls', '—')}"
        if te.get("manual_hours"):
            det += f" · вручную ≈ {te['manual_hours']} ч по норме {te.get('lines_per_hour', '—')} строк в час (оценка)"
        add("speed", "Скорость: прогон по документу организаторов", val, det, "reports/requirements-report.json",
            "python review.py bench/real/notifications.md …")
    else:
        add("speed", "Скорость: прогон по документу организаторов", None, "", "reports/requirements-report.json",
            "python review.py bench/real/notifications.md …")

    mc = md_rows(_section(text, "## DeepSeek против Gemini"))
    found = [r for r in mc if r and r[0].lower().startswith("найдено") and len(r) >= 3]
    head = next((r for r in mc if r and not r[0] and len(r) >= 3), None)
    add("models", "DeepSeek против Gemini (документ организаторов)",
        f"{head[1] if head else 'Gemini'}: {found[0][1]} · {head[2] if head else 'DeepSeek'}: {found[0][2]}" if found else None,
        " · ".join(f"{lbl} {r[1]} / {r[2]}" for r in mc for k, lbl in (("Precision", "точность на бенчмарке"),
                   ("Ложные существенные замечания к чистым требованиям", "ложных к чистым требованиям")) if len(r) >= 3 and r[0] == k),
        "bench/RESULTS.md", "python bench/real_eval.py")
    return rows


def headline(root: Path | None = None) -> list[dict]:
    """Одна строка главных цифр для стартового экрана Studio: только посчитанное (документ организаторов, эталон)."""
    keep = ("organizers", "gold_recall", "gold_precision")
    return [r for r in evidence(root) if r["id"] in keep and r["value"]]
