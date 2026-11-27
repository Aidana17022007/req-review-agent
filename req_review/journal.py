"""v13+: журнал прогона runs/<id>/ и повтор прогона из журнала (без сети).

runs/<id>/
  run.json          — вход (путь, SHA-256), модель, профиль, время, этапы и критический путь, итоговые счётчики
  calls.jsonl       — по строке на обращение к модели: №, задача, этап, время, длина промпта/ответа, ключ записи
  calls/NNN_<задача>.json — вход (system + prompt) и выход (ответ модели) каждого обращения; ключей API здесь нет
  events.log        — журнал событий прогона
Повтор: `python review.py <вход> <отчёт> --replay runs/<id>` — те же ответы модели берутся из журнала (по system+prompt),
поэтому каждый этап воспроизводится без сети и квоты; запрос, которого нет в журнале, — ошибка «нет в журнале».
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime
from pathlib import Path

from .llm import LLMError


def key(system: str, prompt: str) -> str:
    return hashlib.sha256(f"{system}\x00{prompt}".encode()).hexdigest()[:24]


def new_dir(base: Path, sha: str) -> Path:
    d = base / f"{datetime.now():%Y%m%d-%H%M%S}-{sha[:8]}"
    (d / "calls").mkdir(parents=True, exist_ok=True)
    return d


class JournalLLM:
    """Прокси над моделью: пишет вход и выход каждого обращения; остальные атрибуты — как у модели."""

    def __init__(self, inner, root: Path):
        self._inner, self._root, self._n, self._lock = inner, root, 0, threading.Lock()
        self.stage = ""

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __setattr__(self, name, value):
        if name in ("temperature", "model", "max_retries", "timeout", "fallback_models"):
            setattr(self._inner, name, value)
        else:
            object.__setattr__(self, name, value)

    def generate_json(self, system, prompt, *, task: str = "", context: dict | None = None):
        t = time.monotonic()
        err = None
        try:
            data = self._inner.generate_json(system, prompt, task=task, context=context)
            return data
        except Exception as e:
            err, data = str(e)[:500], None
            raise
        finally:
            with self._lock:
                self._n += 1
                n = self._n
            k = key(system, prompt)
            rec = {"n": n, "task": task, "key": k, "model": getattr(self._inner, "label", ""),
                   "seconds": round(time.monotonic() - t, 2), "error": err, "system": system, "prompt": prompt, "response": data}
            (self._root / "calls" / f"{n:03d}_{task or 'call'}.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            line = {k2: rec[k2] for k2 in ("n", "task", "key", "model", "seconds", "error")}
            line.update(prompt_chars=len(prompt), response_chars=len(json.dumps(data, ensure_ascii=False)) if data else 0)
            with self._lock, open(self._root / "calls.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")


class ReplayLLM:
    """Модель-повтор: отвечает записанными в журнале ответами (по system + prompt)."""

    provider = "replay"

    def __init__(self, root: Path):
        from .llm import LLMStats

        self.root = Path(root)
        meta = json.loads((self.root / "run.json").read_text(encoding="utf-8")) if (self.root / "run.json").exists() else {}
        self.model = f"повтор журнала {self.root.name} ({meta.get('model', '')})"
        self.label = self.model
        self.stats = LLMStats()
        self.temperature = 0.0
        self.fallback_models: list[str] = []
        self.min_interval = 0
        self._answers = {}
        for p in sorted((self.root / "calls").glob("*.json")):
            rec = json.loads(p.read_text(encoding="utf-8"))
            if rec.get("response") is not None:
                self._answers[rec["key"]] = rec["response"]

    def generate_json(self, system, prompt, *, task: str = "", context: dict | None = None):
        k = key(system, prompt)
        if k not in self._answers:
            self.stats.errors.append(f"нет в журнале: {task}")
            raise LLMError(f"ответа нет в журнале {self.root.name} (задача {task})")
        self.stats.cached += 1
        return json.loads(json.dumps(self._answers[k]))


def finish(root: Path, ctx, input_path: str, log_lines: list[str] | None = None) -> None:
    p = ctx.passport
    meta = {"input": str(input_path), "sha256": p.get("sha256"), "model": p.get("model"), "profile": p.get("profile"),
            "started": p.get("started"), "duration_s": p.get("duration_s"), "calls": p.get("calls"),
            "stages": p.get("stages"), "critical_path": p.get("critical_path"), "verify": p.get("verify"),
            "findings": sum(len(rr.findings) for rr in ctx.rv.req_results) + len(ctx.rv.set_findings),
            "artifacts": {k: str(v) for k, v in ctx.artifacts.items()}}
    (root / "run.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    if log_lines:
        (root / "events.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
