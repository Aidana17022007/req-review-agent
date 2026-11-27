"""v13: оценка стоимости прогона по config/prices.yaml (цены не выдумываются: нет цены — так и пишем)."""
from __future__ import annotations

from pathlib import Path

PRICES = Path(__file__).resolve().parent.parent / "config" / "prices.yaml"


def load(path: Path = PRICES) -> dict:
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, ImportError, ValueError):
        return {}


def estimate(model_label: str, tokens_in: int, tokens_out: int, calls: int, prices: dict | None = None) -> dict:
    """{"model","tokens_in","tokens_out","calls","free_tier","usd","kzt","per_call_usd","price","note"}."""
    p = prices if prices is not None else load()
    models = p.get("models") or {}
    keys = [k for k in models if k.lower() in (model_label or "").lower()]
    key = max(keys, key=len) if keys else None
    m = models.get(key) or {}
    out = {"model": model_label, "tokens_in": tokens_in, "tokens_out": tokens_out, "calls": calls,
           "free_tier": bool(m.get("free_tier")), "usd": None, "kzt": None, "per_call_usd": None,
           "price": key, "checked": m.get("checked"), "note": m.get("note", "")}
    if m.get("free_tier"):
        out.update(usd=0.0, kzt=0.0, per_call_usd=0.0)
        return out
    pin, pout = m.get("input_per_1m"), m.get("output_per_1m")
    if pin is None or pout is None:
        out["note"] = ("цена модели не указана в config/prices.yaml — стоимость не оценивается" if key
                       else "модели нет в config/prices.yaml — стоимость не оценивается")
        return out
    usd = tokens_in / 1e6 * float(pin) + tokens_out / 1e6 * float(pout)
    out.update(usd=round(usd, 4), per_call_usd=round(usd / calls, 5) if calls else None)
    if p.get("usd_kzt"):
        out["kzt"] = round(usd * float(p["usd_kzt"]), 1)
    return out


def line(c: dict) -> str:
    """Строка паспорта отчёта."""
    if not c:
        return ""
    if c["free_tier"]:
        return f"0 ₸ — {c['note']}" if c.get("note") else "0 ₸ (бесплатный тариф)"
    if c["usd"] is None:
        return c["note"]
    s = f"≈ ${c['usd']:.4f} за прогон ({c['tokens_in']} / {c['tokens_out']} токенов"
    if c.get("kzt") is not None:
        s += f", ≈ {c['kzt']} ₸"
    return s + f"; цены — config/prices.yaml, сверены {c.get('checked') or 'дата не указана'})"
