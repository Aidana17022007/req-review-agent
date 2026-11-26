"""PDF-версия Markdown-отчёта (v7) — для сдачи и печати. Без внешних сервисов: reportlab + шрифт с кириллицей.

Шрифт ищется: REQLENS_PDF_FONT (путь к .ttf) → DejaVu Sans в системе (Linux, Windows, macOS) → шрифты matplotlib.
Если не найден — понятная ошибка с подсказкой. Рендер покрывает то, что пишет report.py: заголовки, абзацы, списки,
цитаты «>», таблицы Markdown, **жирный**, `код`, якоря <a id="…"></a> и ссылки [текст](#якорь) — внутри PDF это
переходы; ссылка на несуществующий якорь выводится обычным текстом.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from xml.sax.saxutils import escape

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "C:/Windows/Fonts/DejaVuSans.ttf",
    "/Library/Fonts/DejaVuSans.ttf",
    str(Path.home() / "Library/Fonts/DejaVuSans.ttf"),
    "C:/Windows/Fonts/arial.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]

_LINK = re.compile(r"\[([^\]]+)\]\((#[^)]+|https?://[^)]+)\)")
_ANCHOR = re.compile(r'<a id="([^"]+)"></a>')
# эмодзи отчёта → символы, которые есть в DejaVu Sans (иначе в PDF были бы пустые квадраты)
_EMOJI = [("⚠️", "⚠"), ("🔴", '<font color="#C62828">●</font>'), ("🟠", '<font color="#E07B00">●</font>'),
          ("🟡", '<font color="#C9A000">●</font>'), ("🟢", '<font color="#1F6B45">●</font>'),
          ("✅", '<font color="#1F6B45">✓</font>'), ("❌", '<font color="#C62828">✗</font>')]
_OTHER_EMOJI = re.compile("[\U0001F000-\U0001FAFF\uFE0F]")


class PdfFontError(RuntimeError):
    pass


def find_font() -> tuple[str, str | None]:
    env = os.getenv("REQLENS_PDF_FONT", "").strip()
    cands = ([env] if env else []) + FONT_CANDIDATES
    try:
        import matplotlib

        cands.append(str(Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf" / "DejaVuSans.ttf"))
    except Exception:
        pass
    for c in cands:
        if c and Path(c).is_file():
            bold = Path(c).with_name(Path(c).stem + "-Bold.ttf")
            if not bold.is_file() and Path(c).name.lower() == "arial.ttf":
                bold = Path(c).with_name("arialbd.ttf")
            return c, (str(bold) if bold.is_file() else None)
    raise PdfFontError("Для PDF нужен шрифт с кириллицей (DejaVu Sans). Установите его (Linux: apt install fonts-dejavu-core) "
                       "или укажите путь: REQLENS_PDF_FONT=/путь/к/шрифту.ttf. Markdown- и HTML-отчёты уже записаны.")


class _Inline:
    def __init__(self, known: set[str]):
        self.known = known

    def __call__(self, text: str) -> str:
        links: list[tuple[str, str]] = []

        def keep(m):
            links.append((m.group(1), m.group(2)))
            return f"\x00{len(links) - 1}\x00"

        # якоря внутри строки (ячейка таблицы, абзац) становятся точками перехода PDF
        text = text.replace("\\|", "|")
        t = escape(_ANCHOR.sub(lambda m: f"\x01{m.group(1)}\x01", _LINK.sub(keep, text)))
        t = re.sub("\x01([^\x01]+)\x01", r'<a name="\1"/>', t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
        t = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', t)

        def link(m):
            label, href = links[int(m.group(1))]
            label = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(label))
            ok = href.startswith("http") or href[1:] in self.known
            return f'<a href="{escape(href)}" color="#1F6B45">{label}</a>' if ok else label

        t = re.sub("\x00(\\d+)\x00", link, t)
        for k, v in _EMOJI:
            t = t.replace(k, v)
        return _OTHER_EMOJI.sub("", t)


def _cells(line: str) -> list[str]:
    s = line.strip().strip("|")
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def _slug(txt: str) -> str:
    return re.sub(r"[^\w-]+", "-", txt.lower()).strip("-")[:60]


def markdown_to_pdf(md: str, out: Path, title: str = "Отчёт ReqLens") -> Path:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.pdfmetrics import registerFontFamily
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle
    except ImportError as e:  # pragma: no cover
        raise PdfFontError("Для PDF нужен пакет reportlab: pip install reportlab") from e

    regular, bold = find_font()
    pdfmetrics.registerFont(TTFont("RLBody", regular))
    pdfmetrics.registerFont(TTFont("RLBold", bold or regular))
    registerFontFamily("RLBody", normal="RLBody", bold="RLBold", italic="RLBody", boldItalic="RLBold")

    base = ParagraphStyle("b", fontName="RLBody", fontSize=8.6, leading=11.4, spaceAfter=3)
    styles = {
        1: ParagraphStyle("h1", parent=base, fontName="RLBold", fontSize=15, leading=19, spaceBefore=4, spaceAfter=8),
        2: ParagraphStyle("h2", parent=base, fontName="RLBold", fontSize=12.5, leading=16, spaceBefore=10, spaceAfter=5,
                          textColor=colors.HexColor("#14532D")),
        3: ParagraphStyle("h3", parent=base, fontName="RLBold", fontSize=10.5, leading=13.5, spaceBefore=7, spaceAfter=3),
        4: ParagraphStyle("h4", parent=base, fontName="RLBold", fontSize=9.4, leading=12, spaceBefore=5, spaceAfter=2),
    }
    quote = ParagraphStyle("q", parent=base, leftIndent=8, textColor=colors.HexColor("#334155"),
                           backColor=colors.HexColor("#F1F5F2"), borderPadding=(3, 4, 3, 4), spaceBefore=2, spaceAfter=5)
    bullet = ParagraphStyle("li", parent=base, leftIndent=10, bulletIndent=2, spaceAfter=1.5)
    cell = ParagraphStyle("td", parent=base, fontSize=7.2, leading=9, spaceAfter=0)
    head = ParagraphStyle("th", parent=cell, fontName="RLBold")
    code = ParagraphStyle("code", parent=base, fontName="Courier", fontSize=7.2, leading=9,
                          backColor=colors.HexColor("#F6F8F7"))

    lines = md.splitlines()
    known = set(_ANCHOR.findall(md)) | {_slug(m.group(2)) for m in re.finditer(r"^(#{1,6})\s+(.*)$", md, re.M)}
    inline = _Inline(known)
    story: list = []
    pending: list[str] = []  # якоря из отдельных строк — ставятся в начало следующего элемента
    para: list[str] = []
    in_code: list[str] | None = None
    width = A4[0] - 30 * mm

    def anchors() -> str:
        a = "".join(f'<a name="{x}"/>' for x in pending)
        pending.clear()
        return a

    def flush():
        if para:
            story.append(Paragraph(anchors() + inline(" ".join(para)), base))
            para.clear()

    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if s.startswith("```"):
            flush()
            if in_code is None:
                in_code = []
            else:
                story.append(Paragraph(escape("\n".join(in_code)).replace("\n", "<br/>").replace(" ", "&nbsp;"), code))
                in_code = None
            i += 1
            continue
        if in_code is not None:
            in_code.append(ln)
            i += 1
            continue
        if not s:
            flush()
            i += 1
            continue
        if s.startswith("<!--") and s.endswith("-->"):  # служебные метки отчёта
            i += 1
            continue
        if _ANCHOR.fullmatch(s):
            flush()
            pending.extend(_ANCHOR.findall(s))
            i += 1
            continue
        h = re.match(r"^(#{1,6})\s+(.*)", s)
        if h:
            flush()
            txt = h.group(2)
            story.append(Paragraph(anchors() + f'<a name="{_slug(txt)}"/>' + inline(txt), styles[min(len(h.group(1)), 4)]))
            i += 1
            continue
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-{3,}", lines[i + 1].strip()):
            flush()
            header = _cells(s)
            n = len(header)
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append((_cells(lines[i]) + [""] * n)[:n])
                i += 1
            lens = [min(max(max([len(header[k])] + [len(r[k]) for r in rows]), 4), 80) for k in range(n)]
            data = [[Paragraph(anchors() + inline(c) if k == 0 and pending else inline(c), head) for k, c in enumerate(header)]]
            data += [[Paragraph(inline(c), cell) for c in r] for r in rows]
            t = LongTable(data, colWidths=[width * x / sum(lens) for x in lens], repeatRows=1)
            t.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C9D6CE")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7F4EC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            story += [t, Spacer(1, 5)]
            continue
        if s.startswith(">"):
            flush()
            block = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                block.append(lines[i].strip().lstrip(">").strip())
                i += 1
            story.append(Paragraph(anchors() + inline(" ".join(block)), quote))
            continue
        m = re.match(r"^(\s*)(?:[-*]|(\d+)\.)\s+(.*)", ln)
        if m:
            flush()
            st = ParagraphStyle("li2", parent=bullet, leftIndent=10 + 8 * (len(m.group(1)) // 2))
            story.append(Paragraph(anchors() + inline(m.group(3)), st, bulletText=(m.group(2) + ".") if m.group(2) else "•"))
            i += 1
            continue
        if s in ("---", "***"):
            flush()
            story.append(Spacer(1, 6))
            i += 1
            continue
        para.append(s)
        i += 1
    flush()
    if pending:  # якорь в самом конце документа
        story.append(Paragraph(anchors(), base))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("RLBody", 7)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(15 * mm, 8 * mm, title[:110])
        canvas.drawRightString(A4[0] - 15 * mm, 8 * mm, f"стр. {doc.page}")
        canvas.restoreState()

    out.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=13 * mm,
                            bottomMargin=14 * mm, title=title, author="ReqLens", subject="Отчёт о проверке требований")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out
