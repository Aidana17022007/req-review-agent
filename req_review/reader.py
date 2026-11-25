"""Чтение документа требований: PDF, DOCX, Markdown, TXT.

Результат — список строк с привязкой к месту (страница для PDF, номер строки),
чтобы каждое замечание в отчёте ссылалось на конкретное место документа.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED = {".pdf", ".docx", ".md", ".markdown", ".txt"}


@dataclass
class Line:
    text: str
    lineno: int  # сквозной номер строки в извлечённом тексте (с 1)
    page: int | None = None  # номер страницы (только PDF)


@dataclass
class Document:
    path: Path
    fmt: str
    lines: list[Line]
    sha256: str
    title: str = ""
    pages: int | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_text(path: Path) -> list[tuple[str, int | None]]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1251", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return [(t, None) for t in text.splitlines()]


def _read_pdf(path: Path) -> tuple[list[tuple[str, int | None]], int]:
    import pdfplumber

    out: list[tuple[str, int | None]] = []
    with pdfplumber.open(str(path)) as pdf:
        n = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=1.5, y_tolerance=3) or ""
            for t in text.splitlines():
                out.append((t, i))
            out.append(("", i))  # граница страницы
    return out, n


def _read_docx(path: Path) -> list[tuple[str, int | None]]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(path))
    out: list[tuple[str, int | None]] = []
    body = d.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            text = p.text.strip()
            style = (p.style.name or "").lower() if p.style is not None else ""
            if style.startswith("heading") or style.startswith("заголовок"):
                level = "".join(ch for ch in style if ch.isdigit()) or "1"
                text = "#" * min(int(level), 6) + " " + text if text else text
            elif "list" in style and text:
                text = "- " + text
            out.append((text, None))
        elif tag == "tbl":
            t = Table(child, d)
            for row in t.rows:
                cells = []
                for c in row.cells:
                    ct = " ".join(c.text.split())
                    if not cells or cells[-1] != ct:  # объединённые ячейки
                        cells.append(ct)
                out.append(("| " + " | ".join(cells) + " |", None))
            out.append(("", None))
    return out


def read_document(path: str | Path) -> Document:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(
            f"Формат {ext or '(без расширения)'} не поддерживается. Поддерживаются: "
            + ", ".join(sorted(SUPPORTED))
        )
    pages = None
    if ext == ".pdf":
        raw, pages = _read_pdf(path)
    elif ext == ".docx":
        raw = _read_docx(path)
    else:
        raw = _read_text(path)

    lines = [Line(text=t.rstrip(), lineno=i, page=p) for i, (t, p) in enumerate(raw, start=1)]
    doc = Document(path=path, fmt=ext.lstrip("."), lines=lines, sha256=_sha256(path), pages=pages)
    if not any(l.text.strip() for l in lines):
        doc.warnings.append(
            "Из документа не извлечён текст (возможно, PDF состоит из сканов). Нужен текстовый PDF или OCR."
        )
    doc.title = _guess_title(doc)
    return doc


def _guess_title(doc: Document) -> str:
    for l in doc.lines[:40]:
        t = l.text.strip()
        if t.startswith("#"):
            return t.lstrip("#").strip()
    for l in doc.lines[:10]:
        t = l.text.strip()
        if t and len(t) < 150:
            return t
    return doc.path.name
