"""Витрина дизайн-системы и слайды питча.

    python -m req_review.ui.styleguide  →  design/styleguide.html, docs/slides.html (+ req_review/ui/tokens.css)

Слайды берут метрики из bench/RESULTS.md и состав команды из docs/team.yaml.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import build_tokens_css_file, env, load_tokens

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "design" / "styleguide.html"


def bench_metrics(path: Path = ROOT / "bench" / "RESULTS.md") -> dict:
    """Метрики бенчмарка для слайда: recall / precision / F1 / ложные срабатывания и пометка о модели."""
    m = {"recall": "—", "precision": "—", "f1": "—", "false_pos": "—", "recall_note": "найдено внедрённых дефектов",
         "false_note": "к заведомо чистым требованиям", "model_note": "Бенчмарк ещё не запускался."}
    if not path.exists():
        return m
    t = path.read_text(encoding="utf-8")
    g = lambda pat: (re.search(pat, t) or [None, None])[1]  # noqa: E731
    m["recall"] = (g(r"\|\s*Recall\s*\|\s*\*\*([\d\s]+%)") or "—").replace(" ", "")
    m["precision"] = (g(r"\|\s*Precision\s*\|\s*\*\*([\d\s]+%)") or "—").replace(" ", "")
    m["f1"] = (g(r"\|\s*F1\s*\|\s*\*\*([\d\s]+%)") or "—").replace(" ", "")
    if (x := re.search(r"\|\s*Recall\s*\|[^(]*\((\d+) из (\d+)\)", t)):
        m["recall_note"] = f"найдено {x[1]} из {x[2]} внедрённых дефектов"
    if (x := re.search(r"Ложные существенные замечания к (\d+) чистым требованиям\s*\|\s*(\d+)", t)):
        m["false_pos"], m["false_note"] = x[2], f"существенных замечаний к {x[1]} заведомо чистым требованиям"
    model = g(r"\*Модель:\*\s*([^·\n]+)")
    mock = "mock" in (model or "") or "режиме mock" in t
    if mock:
        # Цифры mock-прогона (только словарь, без модели) на слайд не выводим: жюри видит лишь измеренное на модели
        m.update({"recall": "—", "precision": "—", "f1": "—", "false_pos": "—",
                  "recall_note": "появится после прогона на модели", "false_note": "появится после прогона на модели",
                  "model_note": "Бенчмарк на модели ещё не запускался (есть только mock-прогон словарных правил)."})
        return m
    m["model_note"] = f"Модель: {model.strip()}." if model else ""
    return m


PLACEHOLDER_NAMES = {"", "имя фамилия", "участник", "name surname"}


def team(path: Path = ROOT / "docs" / "team.yaml") -> list[dict]:
    members = []
    if path.exists():
        import yaml

        members = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("team") or []
    out = []
    for x in members[:8]:
        name = str((x or {}).get("name", "")).strip()
        if name.lower() in PLACEHOLDER_NAMES:
            continue  # незаполненные заготовки на слайд не попадают
        initials = "".join(p[0] for p in name.split()[:2]).upper()
        out.append({"name": name, "role": str(x.get("role", "")).strip(), "initials": initials})
    return out


def build(out: Path = OUT) -> Path:
    build_tokens_css_file()
    t = load_tokens()
    html = env().get_template("styleguide.html.j2").render(tokens=t)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    slides = ROOT / "docs" / "slides.html"
    slides.write_text(env().get_template("slides.html.j2").render(bench=bench_metrics(), bench_rag=bench_metrics(ROOT / "bench" / "RESULTS_RAG.md"), team=team()), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(build())
