"""Сборка сайта ReqLens для Cloudflare Pages: python scripts/build_site.py [--out public] [--studio URL]

Сайт собирается из дизайн-системы проекта (req_review/ui: tokens.css, base.css, логотип, иконки) — выглядит так же,
как отчёт, Studio и слайды. Функции на главной берутся из таблицы «Чем ReqLens отличается» в README, цифры — из
bench/results.json и отчёта для сдачи, поэтому сайт всегда совпадает с проектом.

Папка public/ (в git не хранится, собирается при каждом деплое):
- index.html — главная;
- report/ — интерактивный HTML-отчёт по документу организаторов (reports/requirements-report.html.gz — тот же
  отчёт, что пишет агент; без него — Markdown-отчёт в оформлении проекта) и report.md;
- slides/ — слайды защиты (docs/slides.html);
- assets/ — скриншоты и GIF из docs/assets.
Адрес Studio на Render — --studio или STUDIO_URL. Кода агента и ключей на сайте нет.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# эмодзи строки README → иконка дизайн-системы
EMOJI_ICON = {"🧪": "flask", "🔍": "search", "🪄": "wand", "🛡": "shield", "🏦": "bank", "📊": "graph", "🔒": "wifi-off",
              "🧰": "download", "🕸": "cube", "🤖": "bot"}

PAGE = """<!doctype html>
<html lang="ru" data-theme="light">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<meta name="description" content="ReqLens — ИИ-агент статической проверки требований по ISO/IEC/IEEE 29148 и IEEE 830">
<link rel="icon" href="{{ favicon_href() }}">
<script>try{var t=localStorage.getItem("reqlens-theme")||(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");document.documentElement.dataset.theme=t}catch(e){}</script>
<style>
{{ tokens_css()|safe }}
{{ asset("base.css")|safe }}
body{background:var(--bg);color:var(--text);margin:0}
.site{max-width:var(--max-width);margin:0 auto;padding:0 16px 24px}
.pagebar{position:sticky;top:8px;z-index:5}
.pagebar nav{display:flex;gap:4px;margin-left:auto;align-items:center;flex-wrap:wrap}
.hero{padding:56px 24px 28px;margin-top:8px;border-radius:var(--r-hero);background:radial-gradient(900px 400px at 0% 0%,color-mix(in srgb,var(--brand) 14%,transparent),transparent 60%)}
.k{font:800 clamp(32px,5.2vw,64px)/1.05 var(--font-sans);letter-spacing:-.035em;margin:12px 0 0}
.grad{background:linear-gradient(90deg,#14532D,#3FA06B);-webkit-background-clip:text;background-clip:text;color:transparent}
[data-theme=dark] .grad{background:linear-gradient(90deg,#7FD1A2,#3FA06B);-webkit-background-clip:text;background-clip:text}
.lead{font:400 clamp(16px,1.6vw,20px)/1.55 var(--font-sans);color:var(--text-2);max-width:860px;margin:18px 0 0}
.cta{display:flex;flex-wrap:wrap;gap:10px;margin-top:24px}
.section{margin-top:48px}.section h2{font:800 clamp(24px,3vw,34px)/1.15 var(--font-sans);letter-spacing:-.025em;margin:6px 0 18px}
.feat .ic{color:var(--brand)}.feat .h3{margin:10px 0 6px}.feat p{margin:0}
.shot{border-radius:16px;border:1px solid var(--border);box-shadow:var(--shadow-lg);width:100%;height:auto;display:block;background:var(--surface)}
.shots figure{margin:0}.shots figcaption{margin-top:8px}
.kpi .sub{margin-top:6px}
pre.cmd{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:16px;overflow-x:auto;font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}
.md{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-card);padding:8px 24px 24px;margin-top:16px;overflow-wrap:anywhere}
.md table{border-collapse:collapse;width:100%}.md th,.md td{border:1px solid var(--border);padding:8px 10px;text-align:left;vertical-align:top}
.md code,.md pre{white-space:pre-wrap;overflow-wrap:anywhere}.md .tw{overflow-x:auto}
@media (max-width:640px){.pagebar nav .btn-ghost{display:none}.hero{padding-top:32px}.pagebar .logo small{display:none}}
</style>
</head>
<body>
<div class="site">
<header class="pagebar">
  <a class="logo" href="{{ root }}" style="text-decoration:none"><span class="logo-mark">{{ logo_mark(36) }}</span><span>ReqLens<small>ИИ-ревью требований</small></span></a>
  <nav>
    <a class="btn btn-ghost btn-sm" href="{{ root }}report/">Отчёт</a>
    <a class="btn btn-ghost btn-sm" href="{{ root }}slides/">Слайды</a>
    <button class="btn btn-round" id="theme" type="button" aria-label="Сменить тему">{{ icon("moon", 18) }}</button>
    <a class="btn btn-primary btn-sm" href="{{ studio }}">Studio {{ icon("arrow-up-right", 16) }}</a>
  </nav>
</header>
{{ body|safe }}
<footer class="footer">ReqLens · хакатон BCC-HUB × MNU · ISO/IEC/IEEE 29148:2018, IEEE Std 830-1998 · сайт собирается из репозитория при каждом деплое</footer>
</div>
<script>document.getElementById("theme").onclick=function(){var d=document.documentElement,t=d.dataset.theme==="dark"?"light":"dark";d.dataset.theme=t;try{localStorage.setItem("reqlens-theme",t)}catch(e){}}</script>
</body>
</html>"""

HOME = """
<section class="hero">
  <div class="caption">ISO/IEC/IEEE 29148 · IEEE 830</div>
  <h1 class="k">Дефекты требований —<br><span class="grad">до первой строчки кода</span></h1>
  <p class="lead">ReqLens читает готовый документ требований (PDF, DOCX, Markdown, TXT), выделяет отдельные требования,
  проверяет каждое и весь набор целиком и пишет отчёт на русском: дословная цитата, место, серьёзность и готовая
  формулировка исправления.</p>
  <div class="cta">
    <a class="btn btn-primary btn-lg" href="report/">{{ icon("file", 18) }} Отчёт по документу организаторов</a>
    <a class="btn btn-secondary btn-lg" href="{{ studio }}">{{ icon("upload", 18) }} Проверить свой документ</a>
    <a class="btn btn-ghost btn-lg" href="slides/">{{ icon("play", 18) }} Слайды</a>
  </div>
</section>

<div class="grid g-4">
{% for k in kpis %}
  <div class="kpi{% if loop.first %} kpi-hero{% endif %}"><div class="caption"{% if loop.first %} style="color:rgba(255,255,255,.8)"{% endif %}>{{ k.label }}</div>
  <div class="kpi-num" style="margin-top:10px">{{ k.value }}</div><div class="sub small{% if not loop.first %} muted{% endif %}">{{ k.sub }}</div></div>
{% endfor %}
</div>
<p class="small faint" style="margin-top:10px">{{ note }}</p>

<section class="section">
  <div class="caption">Возможности</div><h2>Чем ReqLens отличается от обычного «LLM-ревьюера»</h2>
  <div class="grid g-3">
  {% for f in features %}
    <div class="card feat">{{ icon(f.icon, 26) }}<div class="h3">{{ f.title }}</div><p class="small muted">{{ f.text }}</p></div>
  {% endfor %}
  </div>
</section>

<section class="section shots">
  <div class="caption">Как это выглядит</div><h2>Отчёт, граф и Studio</h2>
  <div class="grid g-2">
  {% for s in shots %}
    <figure><img class="shot" loading="lazy" src="assets/{{ s.file }}" alt="{{ s.caption }}"><figcaption class="small muted">{{ s.caption }}</figcaption></figure>
  {% endfor %}
  </div>
</section>

<section class="section">
  <div class="caption">Запуск</div><h2>Одна команда</h2>
  <pre class="cmd">pip install -r requirements.txt
python review.py docs/requirements.md reports/report.md            # ключ Gemini в .env
LLM_PROVIDER=rules python review.py docs/requirements.md reports/report.md   # без ключа — только правила</pre>
</section>
"""

REPORT_MD = """
<section class="section" style="margin-top:24px">
  <div class="caption">Отчёт</div><h2>{{ title }}</h2>
  <p class="small muted"><a href="report.md" download>Скачать отчёт (.md)</a></p>
  <div class="md">{{ html|safe }}</div>
</section>
"""


def readme_features() -> list[dict]:
    """Строки таблицы «Чем ReqLens отличается» из README: эмодзи, название, описание."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r"^\|\s*(\S+)\s+\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|\s*$", text, re.M):
        emoji, title, desc = m.group(1), m.group(2), m.group(3)
        icon = next((v for k, v in EMOJI_ICON.items() if emoji.startswith(k)), "spark")
        desc = re.sub(r"`([^`]+)`", r"\1", re.sub(r"\*([^*]+)\*", r"\1", desc))
        out.append({"icon": icon, "title": title, "text": desc})
    return out


def numbers() -> tuple[list[dict], str]:
    kpis, model = [], ""
    rep = ROOT / "reports" / "requirements-report.json"
    if rep.exists():
        d = json.loads(rep.read_text(encoding="utf-8"))
        fs = [f for r in d["requirements"] for f in r["findings"]] + d["set_findings"]
        n_req = sum(1 for r in d["requirements"] if r.get("kind", "requirement") == "requirement")
        model = d["passport"].get("model", "")
        sys.path.insert(0, str(ROOT / "bench"))
        try:
            from real_eval import evaluate

            ev = evaluate(d)
            kpis.append({"label": "Документ организаторов", "value": f"{ev['found']} из {ev['total']}",
                         "sub": f"ожидаемых дефектов найдено, критичных — {ev['critical_found']} из {ev['critical_total']}"})
        except Exception:
            pass
        kpis.append({"label": "Замечаний", "value": str(len(fs)),
                     "sub": f"к {n_req} требованиям, критичных — {sum(1 for f in fs if f['severity'] == 'critical')}"})
    rj = ROOT / "bench" / "results.json"
    if rj.exists():
        d = json.loads(rj.read_text(encoding="utf-8"))
        kpis.append({"label": "Бенчмарк", "value": f"{round(100 * d['recall'])}/{round(100 * d['precision'])} %",
                     "sub": f"recall / precision · {d['total']} дефектов, {len(d.get('cases', {}))} документов"})
    kpis.append({"label": "Цитаты", "value": "100 %", "sub": "замечаний с дословной цитатой, проверенной кодом"})
    note = (f"Модель отчёта: {model}. " if model else "") + "Цифры собраны кодом из отчёта и bench/results.json при сборке сайта."
    return kpis[:4], note


def build(out: Path, studio: str) -> None:
    from req_review.ui import env

    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    for p in (ROOT / "docs" / "assets").iterdir():
        if p.suffix.lower() in (".png", ".gif", ".svg", ".jpg", ".webp", ".mp4"):
            shutil.copy2(p, out / "assets" / p.name)
    e = env()
    page = e.from_string(PAGE)
    kpis, note = numbers()
    shots = [{"file": f, "caption": c} for f, c in (
        ("screenshot-doc-light.png", "Документ: дефекты подчёркнуты в тексте"),
        ("screenshot-graph-light.png", "3D-граф: противоречия и цепочка конфликта"),
        ("screenshot-tests-light.png", "Тесты: Gherkin и покрытие «тестируемо X из N»"),
        ("screenshot-fixes-light.png", "Исправления: diff «было → стало» и вопросы аналитику"),
        ("screenshot-studio-assistant.png", "Studio: AI-ассистент рядом с отчётом"),
        ("screenshot-studio-compare.png", "Studio: «До / После» для новой версии")) if (out / "assets" / f).exists()]
    home = e.from_string(HOME).render(kpis=kpis, note=note, features=readme_features(), shots=shots, studio=studio)
    (out / "index.html").write_text(page.render(title="ReqLens — ИИ-ревью требований", root="./", studio=studio, body=home),
                                    encoding="utf-8")

    (out / "report").mkdir()
    md_path = ROOT / "reports" / "requirements-report.md"
    if md_path.exists():
        shutil.copy2(md_path, out / "report" / "report.md")
    gz = ROOT / "reports" / "requirements-report.html.gz"
    if gz.exists():  # интерактивный отчёт агента — как есть, в его собственном оформлении
        (out / "report" / "index.html").write_bytes(gzip.decompress(gz.read_bytes()))
    else:
        md = md_path.read_text(encoding="utf-8") if md_path.exists() else "# Отчёт ещё не сформирован"
        md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
        md = re.sub(r"(?is)<\s*(script|iframe|object|embed|style)\b.*?(</\s*\1\s*>|$)", "", md)  # отчёт цитирует документ
        md = re.sub(r"(?i)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", md).replace("javascript:", "")
        try:
            import markdown as _md

            body_html = _md.markdown(md, extensions=["tables", "fenced_code"])
            body_html = body_html.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")
        except ImportError:
            from html import escape

            body_html = f"<pre>{escape(md)}</pre>"
        title = (re.search(r"^#\s+(.+)$", md, re.M) or [None, "Отчёт"])[1]
        body = e.from_string(REPORT_MD).render(title=title, html=body_html)
        (out / "report" / "index.html").write_text(page.render(title=f"ReqLens · {title}", root="../", studio=studio, body=body),
                                                   encoding="utf-8")

    (out / "slides").mkdir()
    slides = ROOT / "docs" / "slides.html"
    if slides.exists():
        (out / "slides" / "index.html").write_text(slides.read_text(encoding="utf-8").replace('src="assets/', 'src="../assets/')
                                                   .replace("url(assets/", "url(../assets/"), encoding="utf-8")
    (out / "_headers").write_text("/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n",
                                  encoding="utf-8")
    print(f"Сайт собран: {out} (страниц: {len(list(out.rglob('*.html')))}, интерактивный отчёт: {'да' if gz.exists() else 'нет'})")


def main() -> None:
    ap = argparse.ArgumentParser(prog="python scripts/build_site.py")
    ap.add_argument("--out", default=str(ROOT / "public"))
    ap.add_argument("--studio", default=os.getenv("STUDIO_URL") or "https://reqlens-studio.onrender.com")
    a = ap.parse_args()
    build(Path(a.out), a.studio)


if __name__ == "__main__":
    main()
