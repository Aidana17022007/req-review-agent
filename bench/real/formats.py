"""Версии документа организаторов в DOCX и PDF — для проверки, что агент одинаково читает все форматы.

Запуск: python bench/real/formats.py [папка]  →  notifications.docx и notifications.pdf (по умолчанию reports/formats/).
DOCX собирается той же логикой, что DOCX бенчмарка (bench/inject.py: таблицы Word); PDF — reportlab (platypus) с
настоящими таблицами и шрифтом с кириллицей (DejaVuSans). Файлы не коммитятся — их всегда можно собрать заново.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "notifications.md"
FONTS = [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("C:/Windows/Fonts/DejaVuSans.ttf"),
         Path("C:/Windows/Fonts/arial.ttf"), Path("/Library/Fonts/Arial Unicode.ttf")]


def to_docx(path: Path, md: str | None = None) -> Path:
    sys.path.insert(0, str(HERE.parent))
    from inject import write_docx

    write_docx(md or SRC.read_text(encoding="utf-8"), path)
    return path


def to_pdf(path: Path, md: str | None = None) -> Path:
    from xml.sax.saxutils import escape

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font = next((f for f in FONTS if f.exists()), None)
    if font is None:
        raise RuntimeError("нет шрифта с кириллицей (DejaVuSans или Arial)")
    pdfmetrics.registerFont(TTFont("Cyr", str(font)))
    body = ParagraphStyle("b", fontName="Cyr", fontSize=9.5, leading=12)
    cell = ParagraphStyle("c", fontName="Cyr", fontSize=8, leading=10)
    heads = {n: ParagraphStyle(f"h{n}", fontName="Cyr", fontSize=20 - 2 * n, leading=24 - 2 * n, spaceBefore=6, spaceAfter=3)
             for n in range(1, 5)}
    clean = lambda t: escape(re.sub(r"\*\*|`", "", t))  # noqa: E731
    story, rows = [], []

    def flush():
        if rows:
            n = max(len(r) for r in rows)
            data = [[Paragraph(clean(c), cell) for c in r + [""] * (n - len(r))] for r in rows]
            t = Table(data, colWidths=[A4[0] * 0.8 / n] * n, repeatRows=0)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, "#888888"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story.extend([t, Spacer(1, 6)])
            rows.clear()

    for line in (md or SRC.read_text(encoding="utf-8")).splitlines():
        s = line.strip()
        if s.startswith("```"):
            continue
        if s.startswith("|"):
            if not re.match(r"^\|?\s*:?-{3,}", s):
                rows.append([c.strip() for c in s.strip("|").split("|")])
            continue
        flush()
        if not s or s == "---":
            continue
        h = re.match(r"^(#{1,6})\s+(.*)", s)
        if h:
            story.append(Paragraph(clean(h.group(2)), heads[min(4, len(h.group(1)))]))
        else:
            story.append(Paragraph(clean(s.lstrip("> ")), body))
    flush()
    SimpleDocTemplate(str(path), pagesize=A4, title="Уведомление о расходах по карте", author="ReqLens bench",
                      leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40).build(story)
    return path


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else HERE.parent.parent / "reports" / "formats")
    out.mkdir(parents=True, exist_ok=True)
    print(to_docx(out / "notifications.docx"))
    print(to_pdf(out / "notifications.pdf"))
