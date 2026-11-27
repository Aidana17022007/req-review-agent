"""v9: лимиты загрузок публичного демо-сервера — квота модели не должна уходить на случайный трафик.

DEMO_UPLOADS_PER_IP — проверок с одного адреса в сутки (UTC), DEMO_UPLOADS_TOTAL — всего в сутки; 0 — без лимита.
По умолчанию лимиты включены только на публичном сервере (задана переменная PORT, как на Render): 5 и 20.
Локальный запуск (python -m req_review.web) по умолчанию без лимитов. Режимы «Только правила» и «Демо» модель не
тратят и не считаются. Счётчики — в памяти процесса (перезапуск сервиса их сбрасывает).

v13: DEMO_UPLOADS_PER_IP_HOUR — проверок с одного адреса за последний час (на публичном сервере по умолчанию 3).
DEMO_LIMIT_FALLBACK=rules — при исчерпании лимита не отказывать (429), а проверить тот же файл только правилами
(без модели и квоты) с пометкой в ответе; без переменной — как раньше, 429.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

_lock = threading.Lock()
_day = ""
_by_ip: dict[str, int] = {}
_total = 0
_hour: dict[str, list[float]] = {}  # v13: время загрузок адреса за последний час


def _limit(name: str, public_default: int) -> int:
    raw = os.getenv(name, "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            return public_default
    return public_default if os.getenv("PORT") else 0


def limits() -> tuple[int, int]:
    return _limit("DEMO_UPLOADS_PER_IP", 5), _limit("DEMO_UPLOADS_TOTAL", 20)


def hour_limit() -> int:
    """v13: проверок с одного адреса за скользящий час; 0 — без лимита (локально по умолчанию)."""
    return _limit("DEMO_UPLOADS_PER_IP_HOUR", 3)


def fallback() -> str:
    """v13: «rules» — при исчерпании лимита проверять только правилами вместо отказа 429."""
    return "rules" if os.getenv("DEMO_LIMIT_FALLBACK", "").strip().lower() == "rules" else ""


def client_ip(request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return getattr(request.client, "host", "") or "?"


def _seconds_to_midnight() -> int:
    now = time.time()
    return int(86400 - now % 86400) or 1


def check_and_count(ip: str) -> dict | None:
    """None — можно (загрузка засчитана); иначе {"scope", "limit", "retry_after"} — лимит исчерпан."""
    global _day, _total
    per_ip, total = limits()
    per_hour = hour_limit()
    if not per_ip and not total and not per_hour:
        return None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = time.time()
    with _lock:
        if today != _day:
            _day, _total = today, 0
            _by_ip.clear()
        recent = [t for t in _hour.get(ip, []) if now - t < 3600]
        _hour[ip] = recent
        if per_hour and len(recent) >= per_hour:
            return {"scope": "hour", "limit": per_hour, "retry_after": max(1, int(3600 - (now - recent[0])))}
        if per_ip and _by_ip.get(ip, 0) >= per_ip:
            return {"scope": "ip", "limit": per_ip, "retry_after": _seconds_to_midnight()}
        if total and _total >= total:
            return {"scope": "total", "limit": total, "retry_after": _seconds_to_midnight()}
        _by_ip[ip] = _by_ip.get(ip, 0) + 1
        _total += 1
        _hour[ip].append(now)
    return None


def message(hit: dict) -> str:
    if hit["scope"] == "hour":
        return (f"Лимит проверок с моделью исчерпан: не больше {hit['limit']} в час с одного адреса. Откройте готовый пример "
                "по документу организаторов, проверьте файл только правилами или запустите ReqLens локально — там лимитов нет.")
    who = f"{hit['limit']} с одного адреса" if hit["scope"] == "ip" else f"{hit['limit']} на всех пользователей"
    return (f"Дневной лимит проверок на демо-сервере исчерпан ({who}). Откройте готовый пример по документу "
            "организаторов или запустите ReqLens локально — там лимитов нет.")


def reset() -> None:
    """Для тестов: обнулить счётчики."""
    global _day, _total
    with _lock:
        _day, _total = "", 0
        _by_ip.clear()
        _hour.clear()
