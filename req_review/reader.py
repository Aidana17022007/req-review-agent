"""Чтение документа требований: PDF, DOCX, Markdown, TXT.

Результат — список строк с привязкой к месту (страница для PDF, номер строки),
чтобы каждое замечание в отчёте ссылалось на конкретное место документа.
"""
from __future__ import annotations

import hashlib
from collections import Counter
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
    """Текст PDF по страницам. Таблицы (pdfplumber.find_tables) выдаются строками «| a | b |», как в Markdown и DOCX,
    чтобы проверки таблиц (параметры API, критерии приёмки, чек-листы) работали и на PDF. Заголовки распознаются по
    размеру шрифта (крупнее основного текста) и размечаются «#», «##»… — от них зависят разделы требований.
    Порядок сверху вниз сохраняется."""
    import pdfplumber

    raw: list[tuple[str, int, float | None]] = []  # (текст, страница, размер шрифта строки или None)
    with pdfplumber.open(str(path)) as pdf:
        n = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            try:
                tables = sorted(page.find_tables(), key=lambda t: t.bbox[1])
            except Exception:  # повреждённая разметка страницы — читаем как простой текст
                tables = []
            y = 0.0
            for t in tables:
                x0, top, x1, bottom = t.bbox
                if top > y:
                    raw.extend((ln, i, sz) for ln, sz in _pdf_text(page, y, top))
                for row in t.extract() or []:
                    cells = [" ".join((c or "").split()) for c in row]
                    if any(cells):
                        raw.append(("| " + " | ".join(cells) + " |", i, None))
                raw.append(("", i, None))
                y = max(y, bottom)
            raw.extend((ln, i, sz) for ln, sz in _pdf_text(page, y, page.height))
            raw.append(("", i, None))  # граница страницы
    sizes = [round(sz, 1) for t, _, sz in raw if sz and t.strip()]
    body = Counter(sizes).most_common(1)[0][0] if sizes else 0
    big = sorted({sz for sz in sizes if sz >= body * 1.15}, reverse=True)[:6]
    # перенос строки внутри абзаца: продолжение со строчной буквы склеивается с предыдущей строкой той же страницы
    joined: list[tuple[str, int, float | None]] = []
    for t, i, sz in raw:
        prev = joined[-1] if joined else None
        if (prev and t[:1].islower() and prev[0].strip() and prev[1] == i and not prev[0].lstrip().startswith("|")
                and not prev[0].rstrip().endswith((".", ":", ";", "!", "?")) and (sz is None or round(sz, 1) not in big)):
            joined[-1] = (prev[0].rstrip() + " " + t.strip(), i, prev[2])
        else:
            joined.append((t, i, sz))
    out: list[tuple[str, int | None]] = []
    for t, i, sz in joined:
        if sz and round(sz, 1) in big and t.strip() and len(t) <= 120 and not t.strip().startswith("|"):
            if out and out[-1][0].strip():
                out.append(("", i))
            out.append(("#" * (big.index(round(sz, 1)) + 1) + " " + t.strip(), i))
            out.append(("", i))
        else:
            out.append((t, i))
    return out, n


def _pdf_text(page, top: float, bottom: float) -> list[tuple[str, float | None]]:
    """Строки текста в полосе страницы и размер шрифта каждой строки (для распознавания заголовков)."""
    if bottom - top < 1:
        return []
    try:
        region = page.crop((0, max(0, top), page.width, min(page.height, bottom)))
    except ValueError:
        return []
    try:
        lines = region.extract_text_lines(layout=False, strip=True, return_chars=True)
    except Exception:
        return [(t, None) for t in (region.extract_text(x_tolerance=1.5, y_tolerance=3) or "").splitlines()]
    out = []
    for ln in lines:
        chars = [c for c in ln.get("chars", []) if c.get("text", "").strip()]
        size = Counter(round(c["size"], 1) for c in chars).most_common(1)[0][0] if chars else None
        out.append((ln["text"], size))
    return out


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
