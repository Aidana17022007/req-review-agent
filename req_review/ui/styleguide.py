"""Витрина дизайн-системы: python -m req_review.ui.styleguide → design/styleguide.html (+ req_review/ui/tokens.css)."""
from __future__ import annotations

from pathlib import Path

from . import build_tokens_css_file, env, load_tokens

OUT = Path(__file__).resolve().parent.parent.parent / "design" / "styleguide.html"


def build(out: Path = OUT) -> Path:
    build_tokens_css_file()
    t = load_tokens()
    html = env().get_template("styleguide.html.j2").render(tokens=t)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    slides = out.parent.parent / "docs" / "slides.html"
    slides.write_text(env().get_template("slides.html.j2").render(), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(build())
