"""История проверок ReqLens App: проекты, версии документа и прогоны в SQLite (стандартный sqlite3, без ORM).

Папка данных — REQLENS_DATA (по умолчанию <корень проекта>/data, в .gitignore). Файлы прогона
(загруженный документ и отчёты) лежат в <data>/runs/<run_id>/; в базе — только метаданные и сводка.
Ключ модели и текст документа в базу не пишутся.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from ..pipeline import ROOT

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, created REAL NOT NULL,
    UNIQUE(project_id, sha256)
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    document_id INTEGER REFERENCES documents(id), doc_name TEXT NOT NULL, doc_hash TEXT NOT NULL,
    version INTEGER NOT NULL, agent_version TEXT DEFAULT '', model TEXT DEFAULT '', mode TEXT DEFAULT 'llm',
    created REAL NOT NULL, finished REAL, status TEXT NOT NULL,
    score INTEGER, readiness INTEGER, critical INTEGER, major INTEGER, findings INTEGER, verdict TEXT DEFAULT '',
    artifacts TEXT DEFAULT '{}', compare TEXT, error TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS runs_project ON runs(project_id, created);
"""

ACTIVE = ("queued", "running")


def data_dir() -> Path:
    return Path(os.getenv("REQLENS_DATA") or ROOT / "data")


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        (root / "runs").mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(root / "reqlens.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        # прогон, оборванный перезапуском сервера, не должен навсегда остаться «в работе»
        self.db.execute("UPDATE runs SET status='interrupted', error='Сервер был перезапущен во время прогона' "
                        "WHERE status IN ('queued','running')")
        self.db.commit()

    def _q(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self.db.execute(sql, args)
            rows = cur.fetchall()
            self.db.commit()
            return rows

    # ------------------------------------------------------------------ проекты
    def create_project(self, name: str) -> dict:
        pid = uuid.uuid4().hex[:10]
        self._q("INSERT INTO projects(id, name, created) VALUES (?,?,?)", (pid, name, time.time()))
        return self.project(pid)

    def project(self, pid: str) -> dict | None:
        rows = self._q("SELECT * FROM projects WHERE id=?", (pid,))
        if not rows:
            return None
        p = dict(rows[0])
        last = self._q("SELECT * FROM runs WHERE project_id=? ORDER BY created DESC LIMIT 1", (pid,))
        p["runs"] = self._q("SELECT COUNT(*) FROM runs WHERE project_id=?", (pid,))[0][0]
        p["last_run"] = _run(last[0]) if last else None
        return p

    def projects(self) -> list[dict]:
        return [self.project(r["id"]) for r in self._q("SELECT id FROM projects ORDER BY created DESC")]

    def delete_project(self, pid: str) -> None:
        for r in self._q("SELECT id FROM runs WHERE project_id=?", (pid,)):
            shutil.rmtree(self.run_dir(r["id"]), ignore_errors=True)
        self._q("DELETE FROM runs WHERE project_id=?", (pid,))
        self._q("DELETE FROM documents WHERE project_id=?", (pid,))
        self._q("DELETE FROM projects WHERE id=?", (pid,))

    # ------------------------------------------------------------------ документы и прогоны
    def run_dir(self, rid: str) -> Path:
        return self.root / "runs" / rid

    def document(self, pid: str, name: str, sha: str, size: int) -> int:
        self._q("INSERT OR IGNORE INTO documents(project_id, name, sha256, size, created) VALUES (?,?,?,?,?)",
                (pid, name, sha, size, time.time()))
        return self._q("SELECT id FROM documents WHERE project_id=? AND sha256=?", (pid, sha))[0]["id"]

    def find_same(self, pid: str, sha: str) -> dict | None:
        """Готовый прогон того же файла (тот же SHA-256) в проекте — открыть его вместо нового запроса к модели."""
        rows = self._q("SELECT * FROM runs WHERE project_id=? AND doc_hash=? AND status='done' "
                       "ORDER BY created DESC LIMIT 1", (pid, sha))
        return _run(rows[0]) if rows else None

    def previous_done(self, pid: str) -> dict | None:
        rows = self._q("SELECT * FROM runs WHERE project_id=? AND status='done' ORDER BY created DESC LIMIT 1", (pid,))
        return _run(rows[0]) if rows else None

    def create_run(self, rid: str, pid: str, doc_id: int, name: str, sha: str, mode: str) -> dict:
        version = self._q("SELECT COALESCE(MAX(version), 0) + 1 FROM runs WHERE project_id=?", (pid,))[0][0]
        self._q("INSERT INTO runs(id, project_id, document_id, doc_name, doc_hash, version, mode, created, status) "
                "VALUES (?,?,?,?,?,?,?,?, 'queued')", (rid, pid, doc_id, name, sha, version, mode, time.time()))
        return self.run(rid)

    def update_run(self, rid: str, **fields) -> None:
        if not fields:
            return
        for k in ("artifacts", "compare"):
            if k in fields and not isinstance(fields[k], str) and fields[k] is not None:
                fields[k] = json.dumps(fields[k], ensure_ascii=False)
        cols = ", ".join(f"{k}=?" for k in fields)
        self._q(f"UPDATE runs SET {cols} WHERE id=?", (*fields.values(), rid))

    def run(self, rid: str) -> dict | None:
        rows = self._q("SELECT * FROM runs WHERE id=?", (rid,))
        return _run(rows[0]) if rows else None

    def runs(self, pid: str) -> list[dict]:
        return [_run(r) for r in self._q("SELECT * FROM runs WHERE project_id=? ORDER BY version", (pid,))]

    def delete_run(self, rid: str) -> None:
        shutil.rmtree(self.run_dir(rid), ignore_errors=True)
        self._q("DELETE FROM runs WHERE id=?", (rid,))


def _run(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["artifacts"] = json.loads(d.get("artifacts") or "{}")
    d["compare"] = json.loads(d["compare"]) if d.get("compare") else None
    return d


_STORE: Store | None = None
_STORE_LOCK = threading.Lock()


def get_store() -> Store:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None or _STORE.root != data_dir():
            _STORE = Store(data_dir())
        return _STORE
