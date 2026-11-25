"""Нарезка документа на отдельные требования.

Стратегия:
1. Ищем требования с идентификаторами документа (FR-01, REQ-1.2, ТР-3, НФТ.4, 3.1.2 ...),
   в том числе в строках Markdown/DOCX-таблиц.
2. Если идентификаторов нет — берём пункты и абзацы с модальными формулировками
   («должен», «необходимо», «shall» ...) и присваиваем свои номера, сохраняя цитату.
3. Если и так ничего не нашлось — нарезку делает LLM (см. checker.llm_split).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .reader import Document, Line

# Идентификатор вида FR-01, REQ-001, NFR.3.2, ТР-1, SEC_02, UC-3a
ALNUM_ID = r"(?:[A-ZА-ЯЁ]{1,8}[-_.]?){1,3}\d+(?:[.\-_]\d+)*[a-zа-я]?"
NUM_ID = r"\d+(?:\.\d+)+"  # 3.1.2

ID_LINE_RE = re.compile(
    r"^\s*(?:[-*•]\s+)?(?:\*\*|__)?[\[(]?(?P<id>" + ALNUM_ID + r")[\])]?(?:\*\*|__)?"
    r"\s*(?:[:.)\-—–]\s*|\s+)(?:\*\*|__)?\s*(?P<text>\S.*)$"
)
NUM_LINE_RE = re.compile(r"^\s*(?:#+\s*)?(?P<id>" + NUM_ID + r")\.?\s+(?P<text>\S.*)$")
LIST_NUM_RE = re.compile(r"^\s*(?P<id>\d{1,3})[.)]\s+(?P<text>\S.*)$")
BULLET_RE = re.compile(r"^\s*[-*•]\s+(?:\[[ xX]\]\s+)?(?P<text>\S.*)$")
HEADING_MD_RE = re.compile(r"^\s*(#{1,6})\s+(?P<text>.+?)\s*#*\s*$")
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
ID_ONLY_RE = re.compile(r"^\s*(?:\*\*)?(?P<id>" + ALNUM_ID + "|" + NUM_ID + r")(?:\*\*)?\s*$")

MODAL_RE = re.compile(
    r"\b(долж(?:ен|на|но|ны)\w*|обязан\w*|необходимо|требуется|следует|нужно|может|могут|"
    r"обеспечива\w*|поддержива\w*|позволя\w*|предоставля\w*|"
    r"shall|must|should|will|may|is required to)\b",
    re.IGNORECASE,
)
# Слова, которые часто оказываются частью идентификатора, но им не являются
NOT_ID_PREFIXES = {"ISO", "IEC", "IEEE", "GOST", "ГОСТ", "RFC", "PCI", "TLS", "SSL", "HTTP", "UTF", "SHA", "AES", "PDF"}


@dataclass
class Requirement:
    rid: str  # идентификатор в отчёте (R-001)
    doc_id: str | None  # идентификатор в документе (если был)
    text: str  # полный текст требования (цитата)
    section: str  # раздел документа
    line_start: int
    line_end: int
    page: int | None = None
    extra: dict = field(default_factory=dict)

    @property
    def location(self) -> str:
        parts = []
        if self.section:
            parts.append(f"раздел «{self.section}»")
        if self.page:
            parts.append(f"стр. {self.page}")
        if self.line_start == self.line_end:
            parts.append(f"строка {self.line_start}")
        else:
            parts.append(f"строки {self.line_start}–{self.line_end}")
        return ", ".join(parts)

    @property
    def short(self) -> str:
        t = " ".join(self.text.split())
        return t if len(t) <= 140 else t[:137].rstrip() + "…"


@dataclass
class SplitResult:
    requirements: list[Requirement]
    method: str  # "ids" | "modal" | "llm"
    unnumbered: list[tuple[Line, str]] = field(default_factory=list)  # модальные фразы без ID
    duplicate_ids: dict[str, list[int]] = field(default_factory=dict)


def _clean(text: str) -> str:
    text = re.sub(r"(\*\*|__|`)", "", text)
    return " ".join(text.split()).strip()


def _valid_alnum_id(i: str) -> bool:
    prefix = re.match(r"[A-ZА-ЯЁ]+", i)
    if prefix and prefix.group(0) in NOT_ID_PREFIXES:
        return False
    return True


def _split_table_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_heading(line: str, nxt: str | None) -> str | None:
    m = HEADING_MD_RE.match(line)
    if m:
        return _clean(m.group("text"))
    m = NUM_LINE_RE.match(line)
    if m and not MODAL_RE.search(m.group("text")) and len(m.group("text")) < 90 and not m.group("text").endswith((".", ";")):
        return _clean(f"{m.group('id')} {m.group('text')}")
    # Однострочный нумерованный заголовок «1. Общие положения» / «Раздел 2. ...»
    m = re.match(r"^\s*(?:Раздел|Глава|Section)\s+\d+.*$", line, re.IGNORECASE)
    if m and len(line) < 90:
        return _clean(line)
    return None


def split_requirements(doc: Document) -> SplitResult:
    lines = doc.lines
    section = ""
    reqs: list[dict] = []
    cur: dict | None = None
    table_header: list[str] | None = None
    candidates_no_id: list[tuple[Line, str, str]] = []  # (line, text, section)

    def close():
        nonlocal cur
        if cur:
            reqs.append(cur)
        cur = None

    for idx, ln in enumerate(lines):
        raw = ln.text
        stripped = raw.strip()
        nxt = lines[idx + 1].text if idx + 1 < len(lines) else None

        if not stripped:
            # пустая строка завершает требование, если следом не идёт продолжение-список
            if cur and not (cur["text"].rstrip().endswith(":") and nxt and BULLET_RE.match(nxt)):
                close()
            table_header = None if not stripped else table_header
            continue

        # --- таблицы ---
        if TABLE_ROW_RE.match(raw):
            if TABLE_SEP_RE.match(raw.replace("|", "|")) or set(stripped) <= set("|-: "):
                continue
            cells = _split_table_row(raw)
            id_cell = None
            for ci, c in enumerate(cells[:2]):
                m = ID_ONLY_RE.match(c)
                if m and (not m.group("id")[0].isalpha() or _valid_alnum_id(m.group("id"))):
                    id_cell = ci
                    break
            if id_cell is None:
                if table_header is None:
                    table_header = cells
                elif cells and MODAL_RE.search(" ".join(cells)):
                    candidates_no_id.append((ln, _clean(max(cells, key=len)), section))
                continue
            close()
            others = [c for j, c in enumerate(cells) if j != id_cell and c]
            if not others:
                continue
            text = max(others, key=len)
            extra = {}
            if table_header and len(table_header) == len(cells):
                for h, c in zip(table_header, cells):
                    if c and c != text and c != cells[id_cell] and h:
                        extra[_clean(h)] = _clean(c)
            reqs.append(
                dict(doc_id=_clean(cells[id_cell]), text=_clean(text), section=section,
                     start=ln.lineno, end=ln.lineno, page=ln.page, extra=extra)
            )
            continue
        table_header = None

        # --- заголовки ---
        h = _is_heading(raw, nxt)
        if h is not None:
            close()
            section = h
            continue

        # --- строка с ID ---
        m = ID_LINE_RE.match(raw)
        if m and _valid_alnum_id(m.group("id")) and any(ch.isdigit() for ch in m.group("id")):
            close()
            cur = dict(doc_id=_clean(m.group("id")), text=m.group("text").strip(), section=section,
                       start=ln.lineno, end=ln.lineno, page=ln.page, extra={})
            continue
        m = NUM_LINE_RE.match(raw)
        if m and MODAL_RE.search(m.group("text")):
            close()
            cur = dict(doc_id=m.group("id"), text=m.group("text").strip(), section=section,
                       start=ln.lineno, end=ln.lineno, page=ln.page, extra={})
            continue
        # ID на отдельной строке, текст — на следующей (часто в PDF)
        m = ID_ONLY_RE.match(raw)
        if m and m.group("id")[0].isalpha() and _valid_alnum_id(m.group("id")):
            close()
            cur = dict(doc_id=_clean(m.group("id")), text="", section=section,
                       start=ln.lineno, end=ln.lineno, page=ln.page, extra={})
            continue

        # --- продолжение текущего требования ---
        if cur is not None:
            cur["text"] = (cur["text"] + " " + stripped).strip()
            cur["end"] = ln.lineno
            continue

        # --- кандидат без идентификатора ---
        b = BULLET_RE.match(raw) or LIST_NUM_RE.match(raw)
        text = b.group("text") if b else stripped
        if MODAL_RE.search(text) and len(text) > 15:
            candidates_no_id.append((ln, _clean(text), section))
    close()

    reqs = [r for r in reqs if _clean(r["text"])]
    if reqs:
        method = "ids"
        unnumbered = [(ln, t) for ln, t, _ in candidates_no_id]
    else:
        method = "modal"
        unnumbered = []
        reqs = [
            dict(doc_id=None, text=t, section=s, start=ln.lineno, end=ln.lineno, page=ln.page, extra={})
            for ln, t, s in candidates_no_id
        ]

    out: list[Requirement] = []
    seen: dict[str, list[int]] = {}
    for i, r in enumerate(reqs, start=1):
        rid = f"R-{i:03d}"
        out.append(Requirement(rid=rid, doc_id=r["doc_id"], text=_clean(r["text"]), section=r["section"],
                               line_start=r["start"], line_end=r["end"], page=r["page"], extra=r["extra"]))
        if r["doc_id"]:
            seen.setdefault(r["doc_id"], []).append(r["start"])
    dups = {k: v for k, v in seen.items() if len(v) > 1}
    return SplitResult(requirements=out, method=method, unnumbered=unnumbered, duplicate_ids=dups)
