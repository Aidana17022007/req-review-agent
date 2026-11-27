"""Сборка сайта ReqLens для Cloudflare Pages: python scripts/build_site.py [--out public] [--studio URL]

Исходник сайта — папка site/ (index.html, site.css, site.js, шрифт, WebP-картинки): дизайн-система v3 «Ecliptic Dawn»,
общие токены с приложением — tokens.css из design/tokens.json. При сборке в элементы data-k подставляются свежие цифры
из отчёта для сдачи и bench/results.json, поэтому сайт всегда совпадает с проектом.

Папка public/ (в git не хранится, собирается при каждом деплое):
- index.html — главная;
- report/ — интерактивный HTML-отчёт по документу организаторов (reports/requirements-report.html.gz — тот же
  отчёт, что пишет агент; без него — Markdown-отчёт в оформлении проекта) и report.md;
- slides/ — слайды защиты (docs/slides.html);
- assets/ — скриншоты и GIF из docs/assets, на которые ссылаются слайды.
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

REPORT_MD = """
<section class="section" style="margin-top:24px">
  <div class="caption">Отчёт</div><h2>{{ title }}</h2>
  <p class="small muted"><a href="report.md" download>Скачать отчёт (.md)</a></p>
  <div class="md">{{ html|safe }}</div>
</section>
"""


def fill_numbers(html: str) -> str:
    """Свежие цифры в элементы data-k (отчёт для сдачи, bench/results.json); без данных остаются значения из разметки."""
    vals = {}
    rep = ROOT / "reports" / "requirements-report.json"
    if rep.exists():
        d = json.loads(rep.read_text(encoding="utf-8"))
        fs = [f for r in d["requirements"] for f in r["findings"]] + d["set_findings"]
        n_req = sum(1 for r in d["requirements"] if r.get("kind", "requirement") == "requirement")
        vals["findings"] = f"{n_req} / {len(fs)}"
        sys.path.insert(0, str(ROOT / "bench"))
        try:
            from real_eval import evaluate

            ev = evaluate(d)
            vals["found"] = f"{ev['found']} из {ev['total']}"
        except Exception:
            pass
    rj = ROOT / "bench" / "results.json"
    if rj.exists():
        d = json.loads(rj.read_text(encoding="utf-8"))
        pct = lambda x: f"{round(100 * x)} %"  # noqa: E731
        vals.update(recall=pct(d["recall"]), precision=pct(d["precision"]), **{
            "bench-recall": pct(d["recall"]), "bench-precision": pct(d["precision"]), "bench-total": f"{d['tp']} из {d['total']}",
            "bench-sub": f"{len(d['cases'])} документов, {d['total']} заранее известных дефектов."})
        names = {"payments": "Оплата услуг", "credit": "Онлайн-кредит", "onboarding": "Открытие счёта",
                 "deposit_kk": "Онлайн-депозит (қазақ тілі)", "cards": "Перевыпуск карты (DOCX, таблицы)", "cashback": "Кэшбэк по категориям"}
        vals["bench-rows"] = "".join(f"<tr><td>{names.get(k, k)}</td><td>{c['tp']} из {c['total']}</td><td>{pct(c['recall'])}</td>"
                                     f"<td>{pct(c['precision'])}</td></tr>" for k, c in d["cases"].items())
    team = ROOT / "docs" / "team.yaml"
    if team.exists():
        people = re.findall(r'name:\s*"([^"]+)"', team.read_text(encoding="utf-8"))
        people = [p for p in people if p.strip() and p != "Имя Фамилия"]  # шаблон без имён не показываем
        if people:
            vals["team"] = "Команда: " + ", ".join(people)
    for k, v in vals.items():
        html = re.sub(rf'(<(\w+)[^>]*\bdata-k="{re.escape(k)}"[^>]*>)(.*?)(</\2>)', lambda m: m.group(1) + v + m.group(4), html,
                      count=1, flags=re.S)
    return html


def build(out: Path, studio: str) -> None:
    from req_review.ui import tokens_css

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out)  # сайт: index.html, site.css, site.js, шрифты, картинки WebP, знак
    (out / "tokens.css").write_text(tokens_css(), encoding="utf-8")  # общие токены с приложением (design/tokens.json)
    gif = ROOT / "docs" / "assets" / "live-run.gif"
    if gif.exists():
        shutil.copy2(gif, out / "live-run.gif")
    html = fill_numbers((out / "index.html").read_text(encoding="utf-8"))
    html = html.replace('href="https://reqlens-studio.onrender.com"', f'href="{studio}"')
    (out / "index.html").write_text(html, encoding="utf-8")
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
        from req_review.ui import env

        e = env()
        body = e.from_string(REPORT_MD).render(title=title, html=body_html)
        (out / "report" / "index.html").write_text(e.from_string(PAGE).render(title=f"ReqLens · {title}", root="../",
                                                                              studio=studio, body=body), encoding="utf-8")

    (out / "slides").mkdir()
    slides = ROOT / "docs" / "slides.html"
    if slides.exists():
        text = slides.read_text(encoding="utf-8")
        (out / "slides" / "index.html").write_text(text.replace('src="assets/', 'src="../assets/')
                                                   .replace("url(assets/", "url(../assets/"), encoding="utf-8")
        (out / "assets").mkdir()
        for name in sorted(set(re.findall(r"assets/([\w.-]+)", text))):  # только то, на что ссылаются слайды
            if (ROOT / "docs" / "assets" / name).exists():
                shutil.copy2(ROOT / "docs" / "assets" / name, out / "assets" / name)
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
