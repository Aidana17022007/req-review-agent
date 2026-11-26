"""Нарезка текста на фрагменты для RAG: по заголовкам и пунктам, 200–600 символов, с перекрытием."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HEADING = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
MAX_LEN, MIN_LEN, OVERLAP = 600, 200, 80


@dataclass
class Chunk:
    id: str
    source: str  # файл базы знаний или документа
    title: str  # заголовок документа
    section: str  # заголовок раздела / номер пункта
    text: str  # дословный текст фрагмента
    meta: dict = field(default_factory=dict)  # url, license, kind, criterion…
    line: int = 0


def front_matter(text: str) -> tuple[dict, str]:
    """Метаданные в начале файла kb между строками «---»: «key: value»."""
    meta = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            for line in text[3:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            text = text[end + 4:].lstrip("\n")
    return meta, text


def chunk_text(text: str, source: str, prefix: str = "") -> list[Chunk]:
    meta, body = front_matter(text)
    title = meta.get("title", "")
    chunks: list[Chunk] = []
    section, buf, buf_line = "", [], 0

    def flush():
        nonlocal buf
        para = " ".join(buf).strip()
        buf = []
        if not para:
            return
        parts, cur = [], ""
        for sent in re.split(r"(?<=[.!?;])\s+", para):
            if cur and len(cur) + len(sent) > MAX_LEN:
                parts.append(cur)
                tail = cur[-OVERLAP:]
                cur = (tail.split(" ", 1)[-1] + " " + sent).strip()
            else:
                cur = (cur + " " + sent).strip()
        if cur:
            if parts and len(cur) < MIN_LEN // 2:
                parts[-1] = parts[-1] + " " + cur
            else:
                parts.append(cur)
        for p in parts:
            n = len(chunks) + 1
            chunks.append(Chunk(f"{prefix}{source}#{n}", source, title, section, p.strip(), dict(meta), buf_line))

    for i, line in enumerate(body.splitlines(), start=1):
        m = HEADING.match(line)
        if m:
            flush()
            section = m.group(2).strip()
            buf_line = i
            continue
        if not buf:
            buf_line = i
        if line.strip():
            buf.append(line.strip())
        elif buf and len(" ".join(buf)) >= MIN_LEN:
            flush()
    flush()
    return chunks
