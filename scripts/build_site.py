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
- tz/ — соответствие ТЗ (docs/TZ_COMPLIANCE.md), llms.txt, demo-60s.mp4 — видео «ReqLens за 60 секунд».

Ссылок на неработающие адреса на сайте нет:
- Studio (адрес --studio или STUDIO_URL) появляется, только если её /api/health отвечает 200 при сборке
  (или задан --studio-force / STUDIO_FORCE=1). Иначе главная кнопка ведёт на интерактивный отчёт, «Проверить свой
  документ» — к разделу «Одна команда».
- Ссылки на GitHub — только для открытого репозитория (--repo-public или REPO_PUBLIC=1): закрытый отдаёт посетителю 404.
Кода агента и ключей на сайте нет.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PAGE = """<!doctype html>
<html lang="ru" data-theme="dark">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<meta name="description" content="ReqLens — ИИ-агент статической проверки требований по ISO/IEC/IEEE 29148 и IEEE 830">
<link rel="icon" href="{{ favicon_href() }}">
<script>try{var t=localStorage.getItem("reqlens-theme")||(matchMedia("(prefers-color-scheme: light)").matches?"light":"dark");document.documentElement.dataset.theme=t}catch(e){}</script>
<style>
{{ tokens_css()|safe }}
{{ asset("base.css")|safe }}
body{background:var(--grad-page) fixed;color:var(--text);margin:0}
.site{max-width:var(--max-width);margin:0 auto;padding:0 16px 24px}
.pagebar{position:sticky;top:8px;z-index:5}
.pagebar nav{display:flex;gap:4px;margin-left:auto;align-items:center;flex-wrap:wrap}
.hero{padding:56px 24px 28px;margin-top:8px;border-radius:var(--r-hero);background:radial-gradient(900px 400px at 0% 0%,color-mix(in srgb,var(--brand) 14%,transparent),transparent 60%)}
.k{font:800 clamp(32px,5.2vw,64px)/1.05 var(--font-sans);letter-spacing:-.035em;margin:12px 0 0}
.lead{font:400 clamp(16px,1.6vw,20px)/1.55 var(--font-sans);color:var(--text-2);max-width:860px;margin:18px 0 0}
.cta{display:flex;flex-wrap:wrap;gap:10px;margin-top:24px}
.section{margin-top:48px}.section h2{font:500 clamp(28px,3.4vw,44px)/1.1 var(--font-sans);letter-spacing:-.035em;margin:6px 0 18px;color:#fff}
.section>.caption,.section>p a{color:#E3E6FF}
.feat .ic{color:var(--brand)}.feat .h3{margin:10px 0 6px}.feat p{margin:0}
.shot{border-radius:16px;border:1px solid var(--border);box-shadow:var(--shadow-lg);width:100%;height:auto;display:block;background:var(--surface)}
.shots figure{margin:0}.shots figcaption{margin-top:8px}
.kpi .sub{margin-top:6px}
pre.cmd{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:16px;overflow-x:auto;font:13px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}
.md{background:var(--panel);border:1px solid var(--border);border-radius:var(--r-panel);padding:clamp(20px,3vw,40px) clamp(18px,4vw,48px) 32px;margin-top:16px;overflow-wrap:anywhere}
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
    {% if studio %}<a class="btn btn-primary btn-sm" href="{{ studio }}">Studio {{ icon("arrow-up-right", 16) }}</a>{% else %}<a class="btn btn-primary btn-sm" href="{{ root }}">На главную</a>{% endif %}
  </nav>
</header>
{{ body|safe }}
<footer class="footer" style="color:#0A0D2A">ReqLens · хакатон BCC-HUB × MNU · ISO/IEC/IEEE 29148:2018, IEEE Std 830-1998 · сайт собирается из репозитория при каждом деплое</footer>
</div>
<script>document.getElementById("theme").onclick=function(){var d=document.documentElement,t=d.dataset.theme==="dark"?"light":"dark";d.dataset.theme=t;try{localStorage.setItem("reqlens-theme",t)}catch(e){}}</script>
</body>
</html>"""

REPORT_MD = """
<section class="section" style="margin-top:24px">
  <div class="caption">{{ caption }}</div><h2>{{ title }}</h2>
  {% if download %}<p class="small"><a href="{{ download }}" download>Скачать ({{ download.rsplit(".", 1)[-1] }})</a></p>{% endif %}
  <div class="md">{{ html|safe }}</div>
</section>
"""


def studio_live(url: str, force: bool = False) -> bool:
    """Studio показываем, только если она отвечает: /api/health = 200 (бесплатный Render просыпается до минуты)."""
    if not url:
        return False
    if force:
        return True
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/health", timeout=75) as r:  # noqa: S310 — адрес задаёт владелец
            return r.status == 200
    except Exception as e:  # noqa: BLE001
        print(f"Studio {url} не отвечает ({e}) — кнопки ведут на отчёт и «Одну команду»")
        return False


def apply_links(html: str, studio: str, repo_public: bool) -> str:
    """Оставить только рабочие ссылки: Studio (если жива) или запасные кнопки; GitHub — только открытого репозитория."""
    a = r'<a\b[^>]*\b{}\b[^>]*>.*?</a>\s*'
    if studio:
        html = re.sub(a.format("data-nostudio"), "", html, flags=re.S)
        html = re.sub(r'(<a\b[^>]*\bdata-studio\b)\s+hidden([^>]*\bhref=")[^"]*(")', rf"\1\g<2>{studio}\3", html)
    else:
        html = re.sub(a.format("data-studio"), "", html, flags=re.S)
    if not repo_public:
        html = re.sub(a.format("data-gh"), "", html, flags=re.S)
    return html


def md_page(md: str, *, title: str, caption: str, download: str | None, root: str, studio: str) -> str:
    """Markdown → страница сайта в оформлении проекта. Ссылки на файлы репозитория (которых нет на сайте) — текстом."""
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    md = re.sub(r"\A\s*#\s+.+\n", "", md)  # заголовок документа уже в шапке страницы
    md = re.sub(r"(?is)<\s*(script|iframe|object|embed|style)\b.*?(</\s*\1\s*>|$)", "", md)  # документ цитируется
    md = re.sub(r"(?i)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", md).replace("javascript:", "")
    try:
        import markdown as _md

        body_html = _md.markdown(md, extensions=["tables", "fenced_code"])
        body_html = body_html.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")
    except ImportError:
        from html import escape

        body_html = f"<pre>{escape(md)}</pre>"
    body_html = re.sub(r'<a href="(?!https?://|#|mailto:)[^"]*">(.*?)</a>', r"<code>\1</code>", body_html, flags=re.S)
    from req_review.ui import env

    e = env()
    body = e.from_string(REPORT_MD).render(title=title, caption=caption, download=download, html=body_html)
    return e.from_string(PAGE).render(title=f"ReqLens · {title}", root=root, studio=studio, body=body)


def fill_numbers(html: str) -> str:
    """Свежие цифры в элементы data-k (отчёт для сдачи, bench/results.json); без данных остаются значения из разметки."""
    vals = {}
    rep = ROOT / "reports" / "requirements-report.json"
    if rep.exists():
        d = json.loads(rep.read_text(encoding="utf-8"))
        fs = [f for r in d["requirements"] for f in r["findings"]] + d["set_findings"]
        n_req = sum(1 for r in d["requirements"] if r.get("kind", "requirement") == "requirement")
        vals.update({"n-req": str(n_req), "n-findings": str(len(fs)),
                     "n-critical": str(sum(1 for f in fs if f["severity"] == "critical"))})
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
        vals.update(**{"recall-precision": f"{pct(d['recall'])} / {pct(d['precision'])}",
            "bench-recall": pct(d["recall"]), "bench-precision": pct(d["precision"]), "bench-total": f"{d['tp']} из {d['total']}",
            "bench-sub": f"{len(d['cases'])} документов, {d['total']} заранее известных дефектов."})
        names = {"payments": "Оплата услуг", "credit": "Онлайн-кредит", "onboarding": "Открытие счёта",
                 "deposit_kk": "Онлайн-депозит (қазақ тілі)", "cards": "Перевыпуск карты (DOCX, таблицы)", "cashback": "Кэшбэк по категориям"}
        vals["bench-rows"] = "".join(f"<tr><td>{names.get(k, k)}</td><td>{c['tp']} из {c['total']}</td><td>{pct(c['recall'])}</td>"
                                     f"<td>{pct(c['precision'])}</td></tr>" for k, c in d["cases"].items())
    try:  # самопроверка соответствия ТЗ — тем же кодом, что в CI
        import subprocess

        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "tz_check.py")], capture_output=True, text=True,
                             cwd=ROOT, timeout=120).stdout
        m = re.search(r"(\d+)\s*/\s*(\d+)\s+обязательных", out)
        if m:
            vals["tz"] = f"{m[1]} из {m[2]}"
    except Exception:  # noqa: BLE001
        pass
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


def build(out: Path, studio: str, *, force: bool = False, repo_public: bool = False) -> None:
    from req_review.ui import tokens_css

    studio = studio.strip() if studio_live(studio.strip(), force) else ""
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out)  # сайт: index.html, site.css, site.js, шрифты, картинки WebP, знак
    (out / "tokens.css").write_text(tokens_css(), encoding="utf-8")  # общие токены с приложением (design/tokens.json)
    for src, dst in (("docs/assets/live-run.gif", "live-run.gif"), ("docs/assets/demo-60s.mp4", "demo-60s.mp4"), ("llms.txt", "llms.txt")):
        if (ROOT / src).exists():
            shutil.copy2(ROOT / src, out / dst)
    html = apply_links(fill_numbers((out / "index.html").read_text(encoding="utf-8")), studio, repo_public)
    (out / "index.html").write_text(html, encoding="utf-8")

    (out / "report").mkdir()
    md_path = ROOT / "reports" / "requirements-report.md"
    if md_path.exists():
        shutil.copy2(md_path, out / "report" / "report.md")
    gz = ROOT / "reports" / "requirements-report.html.gz"
    if gz.exists():  # интерактивный отчёт агента — как есть, в его собственном оформлении
        rep = gzip.decompress(gz.read_bytes()).decode("utf-8")
        if studio:  # кнопка «Открыть Studio» в отчёте ведёт на развёрнутую Studio, а не на localhost
            rep = rep.replace('href="http://localhost:8000/"', f'href="{studio}"').replace("Открыть Studio (localhost:8000)", "Открыть ReqLens Studio")
        (out / "report" / "index.html").write_text(rep, encoding="utf-8")
    else:
        md = md_path.read_text(encoding="utf-8") if md_path.exists() else "# Отчёт ещё не сформирован"
        title = (re.search(r"^#\s+(.+)$", md, re.M) or [None, "Отчёт"])[1]
        (out / "report" / "index.html").write_text(md_page(md, title=title, caption="Отчёт", download="report.md" if md_path.exists() else None,
                                                           root="../", studio=studio), encoding="utf-8")
    tz = ROOT / "docs" / "TZ_COMPLIANCE.md"
    if tz.exists():
        (out / "tz").mkdir()
        shutil.copy2(tz, out / "tz" / "TZ_COMPLIANCE.md")
        md = tz.read_text(encoding="utf-8")
        title = (re.search(r"^#\s+(.+)$", md, re.M) or [None, "Соответствие ТЗ"])[1]
        (out / "tz" / "index.html").write_text(md_page(md, title=title, caption="Доверие", download="TZ_COMPLIANCE.md",
                                                       root="../", studio=studio), encoding="utf-8")

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
    print(f"Сайт собран: {out} (страниц: {len(list(out.rglob('*.html')))}, интерактивный отчёт: {'да' if gz.exists() else 'нет'}, "
          f"Studio: {studio or 'нет — кнопки ведут на отчёт'}, GitHub: {'да' if repo_public else 'скрыт'})")


def main() -> None:
    ap = argparse.ArgumentParser(prog="python scripts/build_site.py")
    ap.add_argument("--out", default=str(ROOT / "public"))
    ap.add_argument("--studio", default=os.getenv("STUDIO_URL", ""), help="адрес Studio; ссылка появится, если /api/health = 200")
    ap.add_argument("--studio-force", action="store_true", default=os.getenv("STUDIO_FORCE") == "1",
                    help="поставить ссылку на Studio без проверки /api/health")
    ap.add_argument("--repo-public", action="store_true", default=os.getenv("REPO_PUBLIC") == "1",
                    help="репозиторий открыт: показать ссылки на GitHub")
    a = ap.parse_args()
    build(Path(a.out), a.studio, force=a.studio_force, repo_public=a.repo_public)


if __name__ == "__main__":
    main()
