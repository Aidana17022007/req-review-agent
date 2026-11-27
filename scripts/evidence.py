"""v15: таблица «Доказательства» в начале README — только измеренные числа, каждое со ссылкой на файл, из которого взято.

Запуск:  python scripts/evidence.py           — напечатать таблицу
         python scripts/evidence.py --write   — переписать README между метками evidence:start / evidence:end

Источники (каждый необязателен — нет файла, значит строка «ещё не измерено» с командой, которая это измерит):
  reports/requirements-report.json   — документ организаторов (bench/real_eval.py)
  bench/score.json                   — эталон из 150 дефектов: полнота и проверенная точность (bench/gold_score.py)
  bench/blind/results.json           — слепой набор: ReqLens, голая модель, правила (bench/blind_eval.py)
  bench/baseline/results.json        — голая модель на бенчмарке и документе организаторов (bench/baseline_eval.py)
  examples/answers/external/run/answers_eval.json — чужие ответы аналитика (bench/answers_eval.py)
  bench/speed.json                   — замер скорости (медиана прогонов); пока его нет — раздел «Замер v12» RESULTS.md
  bench/RESULTS.md                   — разделы «Замер v12» и «DeepSeek против Gemini»
Чисел руками в README не пишем: после нового замера — снова python scripts/evidence.py --write.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))

START, END = "<!-- evidence:start -->", "<!-- evidence:end -->"
SRC = {
    "report": "reports/requirements-report.json",
    "score": "bench/score.json",
    "blind": "bench/blind/results.json",
    "baseline": "bench/baseline/results.json",
    "answers": "examples/answers/external/run/answers_eval.json",
    "speed": "bench/speed.json",
    "results": "bench/RESULTS.md",
}


def _pct(x: float) -> str:
    return f"{100 * x:.0f} %"


def _ci(c) -> str:
    a, b = f"{100 * c[0]:.0f}", f"{100 * c[1]:.0f}"
    return f"[{a} %]" if a == b else f"[{a}–{b} %]"


def _load(root: Path, key: str):
    p = root / SRC[key]
    if not p.exists():
        return None
    if p.suffix == ".json":
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return p.read_text(encoding="utf-8")


def _link(key: str, text: str | None = None) -> str:
    return f"[`{text or SRC[key]}`]({SRC[key]})"


def _todo(cmd: str) -> str:
    return f"ещё не измерено — `{cmd}`"


def _section(md: str, title: str) -> str:
    m = re.search(rf"^## {re.escape(title)}.*?(?=^## |\Z)", md, re.S | re.M)
    return m[0] if m else ""


def _cell(section: str, row: str, col: int = 1) -> str | None:
    """Ячейка таблицы Markdown: строка, первая колонка которой начинается с row."""
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) > col and cells[0].startswith(row):
            return cells[col]
    return None


def rows(root: Path = ROOT) -> list[tuple[str, str, str]]:
    """[(что проверяли, результат, где проверить)] — только из файлов результатов."""
    out = []
    rep = _load(root, "report")
    if rep:
        from real_eval import evaluate

        ev = evaluate(rep)
        p = rep.get("passport", {})
        out.append(("Документ организаторов (26 ожидаемых дефектов, список составлен командой)",
                    f"**{ev['found']} из {ev['total']}**, критичных **{ev['critical_found']} из {ev['critical_total']}**; "
                    f"профиль {p.get('profile', '—')}, {p.get('model', '—')}, {p.get('calls', '—')} запросов"
                    f"{', без кэша' if p.get('calls') and not p.get('cached') else ''}, {p.get('duration_s', '—')} с",
                    f"[отчёт](reports/requirements-report.md) · `python bench/real_eval.py {SRC['report']}`"))
    else:
        out.append(("Документ организаторов", _todo("python review.py bench/real/notifications.md reports/requirements-report.md"), "—"))

    sc = _load(root, "score")
    if sc:
        from gold_score import precision_text

        out.append((f"Эталон из {sc['total']} дефектов (9 вымышленных документов + документ организаторов)",
                    f"полнота **{_pct(sc['recall'])}** {_ci(sc['recall_ci'])} ({sc['found']} из {sc['total']}), критичных и "
                    f"противоречий **{sc['critical_found']} из {sc['critical_total']}**",
                    f"{_link('score')} · `python bench/gold_score.py`"))
        out.append(("Точность на эталоне (каждое замечание проверено?)", precision_text(sc),
                    "[`bench/unmatched.md`](bench/unmatched.md) · разметка людьми — "
                    "[`bench/label_sheet.html`](bench/label_sheet.html)"))
    else:
        out.append(("Эталон из 150 дефектов", _todo("python bench/run.py && python bench/gold_score.py --write"), "—"))

    bl = _load(root, "blind")
    if bl and bl.get("agent"):
        a = bl["agent"]
        out.append(("Слепой набор: 3 финтех-ТЗ (MD, DOCX на казахском, PDF без ID); документы и ключ написал отдельный ИИ, "
                    "не видевший код и промпты; ключ закоммичен до прогона",
                    f"найдено **{a['found']} из {a['total']}** ({_pct(a['recall'])}) {_ci(a['recall_ci'])}, критичных "
                    f"{a['critical_found']} из {a['critical_total']}; ложных существенных замечаний к {a['clean_total']} "
                    f"заведомо чистым требованиям — **{a['false_clean_significant']}** (замечания есть у "
                    f"{a['clean_flagged']} из {a['clean_total']}). Разметка ИИ, не человека",
                    "[`bench/blind/RESULTS.md`](bench/blind/RESULTS.md) · проверка человеком — "
                    "[`bench/blind/README.md`](bench/blind/README.md)"))
    else:
        out.append(("Слепой набор (документы и ключ — не команда)", _todo("python bench/blind_eval.py --results"),
                    "[`bench/blind/README.md`](bench/blind/README.md)"))

    parts = []
    if bl and bl.get("baseline"):
        b = bl["baseline"]
        parts.append(f"слепой набор — **{b['found']} из {b['total']}** ({_pct(b['recall'])}) {_ci(b['recall_ci'])}, "
                     f"ложных к чистым {b['false_clean_significant']}")
    base = _load(root, "baseline")
    if base and base.get("B_bare") and base.get("C_reqlens"):
        bb, cr = base["B_bare"], base["C_reqlens"]
        parts.append(f"бенчмарк ({len(base.get('docs', []))} документов) — {bb['bench']['tp']} из {bb['bench']['total']} "
                     f"против {cr['bench']['tp']} из {cr['bench']['total']} у ReqLens")
        parts.append(f"документ организаторов — {bb['organizers']['found']} из {bb['organizers']['total']} против "
                     f"{cr['organizers']['found']} из {cr['organizers']['total']}")
    out.append(("Голая модель: та же модель одним запросом, без ReqLens",
                "; ".join(parts) if parts else _todo("python bench/baseline_eval.py"),
                " · ".join(x for x in ((_link("blind") if bl and bl.get("baseline") else ""),
                                       (_link("baseline") if base else "")) if x) or "—"))

    an = _load(root, "answers")
    if an and an.get("total"):
        bt = an.get("by_type", {})
        con = bt.get("contradictory", [0, 0])
        s = an.get("summary", {})
        before, after = an.get("before", {}), an.get("after", {})
        out.append(("Ответы аналитика, написанные не командой (отдельный ИИ как владелец ТЗ)",
                    f"тип ответа определён верно **{an['ok']} из {an['total']}**; противоречивых **{con[0]} из {con[1]}**; "
                    f"закрыто блокеров {s.get('blockers_closed', '—')} из {s.get('blockers_total', '—')}; критичных "
                    f"{before.get('critical', '—')} → {after.get('critical', '—')}",
                    f"{_link('answers', 'answers_eval.json')} · "
                    f"[`examples/answers/external/`](examples/answers/external/)"))
    else:
        out.append(("Ответы аналитика, написанные не командой",
                    _todo("python bench/answers_eval.py --report … --key examples/answers/external/key.json"), "—"))

    md = _load(root, "results") or ""
    sp = _load(root, "speed")
    if sp and sp.get("median_s") is not None:
        out.append(("Скорость (документ организаторов, без кэша)",
                    f"медиана **{sp['median_s']:.0f} с** по {sp.get('runs', '—')} прогонам, {sp.get('calls', '—')} запросов; "
                    f"профиль {sp.get('profile', '—')}", _link("speed")))
    else:
        v12 = _section(md, "Замер v12")
        t, c = _cell(v12, "Время"), _cell(v12, "Запросов к модели")
        if t and c:
            out.append(("Скорость (документ организаторов, профиль fast, без кэша)",
                        f"{t.split(':')[0]}, {c.split(' (')[0]} запросов (один прогон, v12; медианы 3 прогонов ещё нет)",
                        f"{_link('results')}, раздел «Замер v12»"))
        else:
            out.append(("Скорость", _todo("python review.py bench/real/notifications.md r.md --profile fast --no-cache"), "—"))

    ds = _section(md, "DeepSeek против Gemini")
    found = _cell(ds, "Найдено", 1), _cell(ds, "Найдено", 2)
    noise = _cell(ds, "Ложные существенные замечания к чистым", 1), _cell(ds, "Ложные существенные замечания к чистым", 2)
    if all(found) and all(noise):
        out.append(("DeepSeek против Gemini (тот же код, без кэша)",
                    f"документ организаторов: Gemini {found[0]}, DeepSeek {found[1]}; ложных существенных к чистым "
                    f"требованиям бенчмарка: Gemini **{noise[0]}**, DeepSeek **{noise[1]}**",
                    f"{_link('results')}, раздел «DeepSeek против Gemini»"))
    return out


def table(root: Path = ROOT) -> str:
    lines = ["| Что проверяли | Результат | Где проверить |", "|---|---|---|"]
    for what, res, where in rows(root):
        lines.append(f"| {what} | {res} | {where} |".replace("\n", " "))
    return "\n".join(lines)


def block(root: Path = ROOT) -> str:
    return (f"{START}\n## Доказательства\n\nТолько измеренные числа; каждое — со ссылкой на файл, из которого взято. "
            f"Таблицу собирает `python scripts/evidence.py --write`, руками её не правим.\n\n{table(root)}\n{END}")


def write(readme: Path = ROOT / "README.md", root: Path = ROOT) -> bool:
    """Переписать блок между метками; если меток нет — вставить перед «## В двух словах». True — README изменён."""
    t = readme.read_text(encoding="utf-8")
    new_block = block(root)
    pat = re.compile(re.escape(START) + ".*?" + re.escape(END), re.S)
    if pat.search(t):
        new = pat.sub(lambda _: new_block, t, count=1)
    elif "## В двух словах" in t:
        new = t.replace("## В двух словах", new_block + "\n\n## В двух словах", 1)
    else:
        new = t.rstrip("\n") + "\n\n" + new_block + "\n"
    if new != t:
        readme.write_text(new, encoding="utf-8")
    return new != t


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python scripts/evidence.py")
    ap.add_argument("--write", action="store_true", help="переписать таблицу в README.md")
    a = ap.parse_args(argv)
    if a.write:
        print("README обновлён" if write() else "README уже актуален")
    else:
        print(block())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
