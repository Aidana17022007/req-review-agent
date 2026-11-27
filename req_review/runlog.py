"""v9: журнал прогона <отчёт>.log — этапы, длительности, модель, обращения / кэш / повторы, переключения моделей,
отброшенные цитаты. Без ключей (вычищаются из каждой строки) и без полного текста документа (только короткие цитаты
отброшенных замечаний — до 60 символов)."""
from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path

KEY_PATTERNS = [re.compile(p) for p in (r"AIza[0-9A-Za-z_\-]{20,}", r"sk-[A-Za-z0-9_\-]{16,}", r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}",
                                         r"(?i)(api[_-]?key|token|secret)\s*[=:]\s*\S{8,}")]


def redact(text: str) -> str:
    s = str(text)
    for name, val in os.environ.items():
        if re.search(r"(KEY|TOKEN|SECRET|PASSWORD)$", name) and val and len(val) >= 8 and val in s:
            s = s.replace(val, "***")
    for p in KEY_PATTERNS:
        s = p.sub("***", s)
    return s


class RunLog:
    def __init__(self):
        self.t0 = time.monotonic()
        self.started = datetime.now().astimezone()
        self.entries: list[tuple[float, str]] = []
        self._stage: tuple[float, str] | None = None
        self.stages: list[tuple[str, float]] = []

    def _t(self) -> float:
        return time.monotonic() - self.t0

    def add(self, msg: str) -> None:
        self.entries.append((self._t(), redact(msg)[:400]))

    def stage(self, name: str) -> None:
        now = self._t()
        if self._stage:
            self.stages.append((self._stage[1], now - self._stage[0]))
        self._stage = (now, name)
        self.entries.append((now, f"== этап: {name}"))

    def _close(self) -> None:
        if self._stage:
            self.stages.append((self._stage[1], self._t() - self._stage[0]))
            self._stage = None

    def text(self, ctx=None, error: str = "") -> str:
        self._close()
        pp = getattr(ctx, "passport", None) or {}
        out = ["ReqLens — журнал прогона", f"начало: {self.started:%Y-%m-%d %H:%M:%S %Z}".strip()]
        if pp:
            out += [f"документ: {pp.get('document', '')} · файл {Path(str(pp.get('file', ''))).name} · {pp.get('format', '')} · "
                    f"SHA-256 {str(pp.get('sha256', ''))[:16]}…",
                    f"модель: {pp.get('model', '')} · профиль: {pp.get('profile', '')} · режим: {pp.get('mode', '')}",
                    f"версия агента: {pp.get('agent_version', '')}"]
        out += ["", "--- события ---"]
        out += [f"[{t:7.1f} с] {m}" for t, m in self.entries]
        if self.stages:
            out += ["", "--- длительность этапов ---"] + [f"{name}: {sec:.1f} с" for name, sec in self.stages]
        if pp:
            out += ["", "--- итог ---",
                    f"обращений к модели: {pp.get('calls', 0)} · из кэша: {pp.get('cached', 0)} · повторов: {pp.get('retries', 0)}",
                    f"токены: вход {pp.get('tokens_in', 0)} / выход {pp.get('tokens_out', 0)}",
                    "переключения моделей: " + ("; ".join(map(str, pp.get("model_switches") or [])) or "нет"),
                    f"длительность: {pp.get('duration_s', round(self._t()))} с"]
            rv = getattr(ctx, "rv", None)
            dropped = list(getattr(rv, "dropped", []) or [])
            out.append(f"отброшено замечаний с неподтверждённой цитатой: {len(dropped)}")
            out += [f"  - {d.get('where', '')}: «{redact(str(d.get('quote', '')))[:60]}»" for d in dropped[:50]]
            out.append(f"отклонено критиком и ответами: {len(getattr(rv, 'rejected', []) or [])}")
        if error:
            out += ["", f"ОШИБКА: {redact(error)[:500]}"]
        return "\n".join(out) + "\n"

    def write(self, path: Path, ctx=None, error: str = "") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.text(ctx, error), encoding="utf-8")
        return path
