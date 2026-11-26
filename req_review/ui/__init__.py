"""Дизайн-система ReqLens: токены, иконки, CSS/JS-ассеты и шаблоны (HTML-отчёт, веб-студия, styleguide)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent
ASSETS = UI_DIR / "assets"
TEMPLATES = UI_DIR / "templates"
TOKENS_JSON = UI_DIR.parent.parent / "design" / "tokens.json"
TOKENS_FALLBACK = ASSETS / "tokens.json"


def load_tokens() -> dict:
    p = TOKENS_JSON if TOKENS_JSON.exists() else TOKENS_FALLBACK
    return json.loads(p.read_text(encoding="utf-8"))


def tokens_css(tokens: dict | None = None) -> str:
    """tokens.json → CSS custom properties (светлая, тёмная тема, prefers-color-scheme)."""
    t = tokens or load_tokens()

    def block(colors: dict) -> str:
        return "\n".join(f"  --{k}: {v};" for k, v in colors.items())

    common = [f"  --font-sans: {t['font']['sans']};", f"  --font-mono: {t['font']['mono']};"]
    # палитры 50–950 — опорные шкалы; компоненты используют семантические токены (--brand, --text-2…), а не шкалы напрямую
    common += [f"  --{name}-{k}: {v};" for name, scale in t.get("palette", {}).items() for k, v in scale.items()]
    # шкала размеров шрифта 12/14/16/20/24/32/48 с межстрочными: --fs-md / --lh-md
    for k, v in t.get("scale", {}).items():
        size, lh = v.split("/")
        common += [f"  --fs-{k}: {size};", f"  --lh-{k}: {lh};"]
    # шорткат font требует семейство — добавляем его в токен типографики
    common += [f"  --t-{k}: {v} {t['font']['sans']};" for k, v in t["type"].items()]
    common += [f"  --s-{k}: {v};" for k, v in t["space"].items()]
    common += [f"  --r-{k}: {v};" for k, v in t["radius"].items()]
    common += [f"  --shadow-{k}: {v};" for k, v in t["shadow"].items()]
    common += [f"  --motion-{k}: {v};" for k, v in t["motion"].items()]
    common += [f"  --z-{k}: {v};" for k, v in t.get("z", {}).items()]
    common += [f"  --max-width: {t['layout']['max-width']};", f"  --sidebar: {t['layout'].get('sidebar', '248px')};"]
    light, dark = block(t["color"]["light"]), block(t["color"]["dark"])
    # [data-theme] без :root — темы можно применять и к отдельным блокам (витрина styleguide)
    return (f":root {{\n{chr(10).join(common)}\n{light}\n  color-scheme: light;\n}}\n"
            f"[data-theme=\"light\"] {{\n{light}\n  color-scheme: light;\n}}\n"
            f"[data-theme=\"dark\"] {{\n{dark}\n  color-scheme: dark;\n}}\n")
    # Основная тема — светлая зелёная; тёмная включается только переключателем (не по настройке ОС)


@lru_cache(maxsize=None)
def asset(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def asset_b64(name: str) -> str:
    """Бинарный ассет (например, gzip-бандл библиотеки) в base64 — для инлайна в офлайн-HTML без CDN."""
    import base64

    p = ASSETS / name
    return base64.b64encode(p.read_bytes()).decode("ascii") if p.exists() else ""


def env():
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    from .brand import favicon_href, logo_mark
    from .icons import ICONS, icon

    e = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html", "j2"]))
    e.globals.update(icon=icon, ICONS=ICONS, tokens_css=tokens_css, asset=asset, asset_b64=asset_b64,
                     logo_mark=logo_mark, favicon_href=favicon_href)
    return e


def build_tokens_css_file() -> Path:
    out = UI_DIR / "tokens.css"
    out.write_text("/* Сгенерировано из design/tokens.json — не редактировать вручную */\n" + tokens_css(), encoding="utf-8")
    return out
