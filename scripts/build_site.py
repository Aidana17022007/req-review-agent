"""Сборка статического сайта ReqLens для Cloudflare Pages: python scripts/build_site.py [--out public] [--studio URL]

Что попадает на сайт (папка public/, в git не хранится — собирается заново при каждом деплое):
- index.html — главная: что умеет агент, цифры из bench/results.json и bench/RESULTS.md, скриншоты, ссылки;
- report/ — отчёт по документу организаторов (reports/requirements-report.md, отрисовка Markdown в браузере);
- slides/ — слайды защиты (docs/slides.html) с картинками;
- assets/ — скриншоты и GIF из docs/assets.
Адрес Studio на Render берётся из --studio или переменной STUDIO_URL (по умолчанию — подсказка о деплое).
Сайт не содержит кода агента и ключей: только документацию и готовый отчёт.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKED = "https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"

CSS = """
:root{--bg:#f7f8fb;--card:#fff;--ink:#0f172a;--muted:#5b6475;--line:#e3e7ee;--brand:#0b5fff;--ok:#12b76a;--crit:#e5484d;--maj:#f59e0b}
@media (prefers-color-scheme:dark){:root{--bg:#0b1020;--card:#121a2e;--ink:#e8ecf5;--muted:#9aa4b8;--line:#232d45;--brand:#4d8bff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--brand)}.wrap{max-width:1100px;margin:0 auto;padding:0 16px}
header{border-bottom:1px solid var(--line);background:var(--card)}header .wrap{display:flex;gap:16px;align-items:center;justify-content:space-between;padding:14px 16px}
.logo{font-weight:800;font-size:20px;letter-spacing:-.02em}.logo span{color:var(--brand)}nav a{margin-left:16px;text-decoration:none;font-weight:600}
.hero{padding:56px 0 24px}.hero h1{font-size:clamp(28px,5vw,46px);line-height:1.1;margin:0 0 14px;letter-spacing:-.03em}
.hero p{font-size:18px;color:var(--muted);max-width:760px}.btns{display:flex;flex-wrap:wrap;gap:12px;margin-top:22px}
.btn{display:inline-block;padding:12px 18px;border-radius:10px;font-weight:700;text-decoration:none;border:1px solid var(--line);background:var(--card)}
.btn.main{background:var(--brand);color:#fff;border-color:var(--brand)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin:28px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}.kpi b{display:block;font-size:30px;letter-spacing:-.02em}
.kpi span{color:var(--muted);font-size:14px}h2{font-size:26px;margin:44px 0 14px;letter-spacing:-.02em}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}.card h3{margin:0 0 6px;font-size:17px}.card p{margin:0;color:var(--muted)}
.shots img{width:100%;border-radius:12px;border:1px solid var(--line);display:block}.shots figcaption{color:var(--muted);font-size:14px;margin:6px 0 0}
table{border-collapse:collapse;width:100%;font-size:15px}th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
.tw{overflow-x:auto}footer{margin:56px 0 0;padding:24px 0;border-top:1px solid var(--line);color:var(--muted);font-size:14px}
code{background:rgba(127,127,127,.12);padding:1px 5px;border-radius:5px}pre{background:var(--card);border:1px solid var(--line);padding:12px;border-radius:10px;overflow-x:auto}
.md code,.md pre{white-space:pre-wrap;overflow-wrap:anywhere}.md{overflow-wrap:anywhere}
.md{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:8px 22px 22px;margin:24px 0}.md blockquote{margin:0;padding:4px 14px;border-left:4px solid var(--line);color:var(--muted)}
"""

FEATURES = [
    ("Дословные цитаты", "Каждое замечание — с цитатой и местом; код проверяет цитату по тексту документа и отбрасывает выдуманное."),
    ("Тест-проба", "К каждому требованию агент пробует написать приёмочный тест. Не вышло — доказательство непроверяемости."),
    ("Набор целиком", "Противоречия между правилами и примерами, нет метода чтения в API, контракт события, термины без определения."),
    ("Самопроверка", "Повторный проход с другой температурой, критик объединяет дубли и калибрует серьёзность."),
    ("Учёт строк", "Каждая строка документа учтена: вошла в требование или исключена с причиной."),
    ("PDF, DOCX, Markdown", "Таблицы Word и PDF, заголовки по размеру шрифта, документы на казахском языке."),
]


def page(title: str, body: str, extra_head: str = "") -> str:
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
            f'initial-scale=1"><title>{html.escape(title)}</title><meta name="description" content="ReqLens — ИИ-агент '
            f'статической проверки требований по ISO/IEC/IEEE 29148 и IEEE 830"><style>{CSS}</style>{extra_head}</head>'
            f"<body>{body}</body></html>")


def header(prefix: str, studio: str) -> str:
    return (f'<header><div class="wrap"><a class="logo" href="{prefix}" style="text-decoration:none;color:inherit">Req'
            f'<span>Lens</span></a><nav><a href="{prefix}report/">Отчёт</a><a href="{prefix}slides/">Слайды</a>'
            f'<a href="{html.escape(studio)}">Studio</a></nav></div></header>')


def numbers() -> dict:
    out = {"recall": None, "precision": None, "found": None, "crit": None, "findings": None, "reqs": None, "model": ""}
    rj = ROOT / "bench" / "results.json"
    if rj.exists():
        d = json.loads(rj.read_text(encoding="utf-8"))
        out.update(recall=round(100 * d["recall"]), precision=round(100 * d["precision"]), bench_total=d["total"],
                   bench_docs=len(d.get("cases", {})))
    rep = ROOT / "reports" / "requirements-report.json"
    if rep.exists():
        d = json.loads(rep.read_text(encoding="utf-8"))
        fs = [f for r in d["requirements"] for f in r["findings"]] + d["set_findings"]
        out["findings"] = len(fs)
        out["crit"] = sum(1 for f in fs if f["severity"] == "critical")
        out["reqs"] = sum(1 for r in d["requirements"] if r.get("kind", "requirement") == "requirement")
        out["model"] = d["passport"].get("model", "")
        import sys

        sys.path.insert(0, str(ROOT / "bench"))
        try:
            from real_eval import evaluate

            ev = evaluate(d)
            out["found"], out["found_total"] = ev["found"], ev["total"]
            out["crit_found"], out["crit_total"] = ev["critical_found"], ev["critical_total"]
        except Exception:
            pass
    return out


def build(out: Path, studio: str) -> None:
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    for p in (ROOT / "docs" / "assets").iterdir():
        if p.suffix.lower() in (".png", ".gif", ".svg", ".jpg", ".webp", ".mp4") and p.stat().st_size < 25_000_000:
            shutil.copy2(p, out / "assets" / p.name)
    n = numbers()
    kpi = []
    if n.get("found") is not None:
        kpi.append((f"{n['found']} из {n['found_total']}", "ожидаемых дефектов документа организаторов найдено"))
        kpi.append((f"{n['crit_found']} из {n['crit_total']}", "критичных дефектов найдено"))
    if n.get("recall") is not None:
        kpi.append((f"{n['recall']} % / {n['precision']} %", f"recall / precision на бенчмарке ({n['bench_total']} дефектов, "
                                                                f"{n['bench_docs']} документов)"))
    if n.get("findings") is not None:
        kpi.append((str(n["findings"]), f"подтверждённых замечаний к {n['reqs']} требованиям, критичных — {n['crit']}"))
    kpis = "".join(f'<div class="kpi"><b>{html.escape(a)}</b><span>{html.escape(b)}</span></div>' for a, b in kpi)
    feats = "".join(f'<div class="card"><h3>{html.escape(a)}</h3><p>{html.escape(b)}</p></div>' for a, b in FEATURES)
    shots = [("live-run.gif", "Живой прогон в Studio"), ("screenshot-doc-light.png", "Дефекты подчёркнуты в тексте документа"),
             ("screenshot-graph-light.png", "Граф требований: противоречия и зависимости"),
             ("screenshot-fixes-light.png", "Исправления «было → стало»")]
    shots_html = "".join(f'<figure class="shots" style="margin:0"><img loading="lazy" src="assets/{f}" alt="{html.escape(c)}">'
                         f"<figcaption>{html.escape(c)}</figcaption></figure>" for f, c in shots if (out / "assets" / f).exists())
    body = (header("./", studio) + '<main class="wrap"><section class="hero"><h1>ReqLens — ИИ-ревью требований до разработки</h1>'
            "<p>Агент читает документ требований (PDF, DOCX, Markdown), выделяет требования и проверяет каждое и весь набор "
            "по ISO/IEC/IEEE 29148:2018 и IEEE 830. Каждое замечание — с дословной цитатой, местом, серьёзностью и готовой "
            "формулировкой исправления.</p>"
            f'<div class="btns"><a class="btn main" href="report/">Отчёт по документу организаторов</a>'
            f'<a class="btn" href="{html.escape(studio)}">Проверить свой документ (Studio)</a><a class="btn" href="slides/">Слайды</a></div>'
            f'</section><div class="kpis">{kpis}</div>'
            f'<p style="color:var(--muted);font-size:14px">Модель отчёта: {html.escape(n.get("model") or "—")}. Цифры собраны кодом из '
            "bench/results.json и отчёта, а не вписаны руками.</p>"
            f'<h2>Что умеет</h2><div class="grid">{feats}</div>'
            f'<h2>Как это выглядит</h2><div class="grid">{shots_html}</div>'
            '<h2>Запуск</h2><pre>pip install -r requirements.txt\npython review.py docs/requirements.md reports/report.md'
            "  # ключ Gemini в .env\nLLM_PROVIDER=rules python review.py docs/requirements.md reports/report.md  # без ключа</pre>"
            "<footer>ReqLens · хакатон BCC-HUB × MNU · отчёт и цифры обновляются при каждом деплое</footer></main>")
    (out / "index.html").write_text(page("ReqLens — ИИ-ревью требований", body), encoding="utf-8")

    md_path = ROOT / "reports" / "requirements-report.md"
    md = md_path.read_text(encoding="utf-8") if md_path.exists() else "# Отчёт ещё не сформирован"
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    # отчёт цитирует документ: активный HTML не пропускаем (marked не фильтрует разметку)
    md = re.sub(r"(?is)<\s*(script|iframe|object|embed|style)\b.*?(</\s*\1\s*>|$)", "", md)
    md = re.sub(r"(?i)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", md)
    md = re.sub(r"(?i)javascript:", "", md)
    (out / "report").mkdir()
    try:  # отрисовка при сборке (workflow ставит markdown); без библиотеки — в браузере через marked
        import markdown as _md

        rendered = _md.markdown(md, extensions=["tables", "fenced_code"], output_format="html")
        rendered = re.sub(r"<table>", '<div class="tw"><table>', rendered).replace("</table>", "</table></div>")
        rbody = (header("../", studio) + f'<main class="wrap"><div class="md">{rendered}</div>'
                 '<p><a href="report.md" download>Скачать отчёт (.md)</a></p></main>')
        (out / "report" / "index.html").write_text(page("Отчёт ReqLens — документ организаторов", rbody), encoding="utf-8")
        md_done = True
    except ImportError:
        md_done = False
    rbody = (header("../", studio) + '<main class="wrap"><div class="md" id="md">Загрузка отчёта…</div>'
             f'<p><a href="report.md" download>Скачать отчёт (.md)</a></p></main>'
             f'<script id="src" type="text/markdown">{html.escape(md)}</script>'
             f'<script src="{MARKED}"></script><script>'
             "const t=new DOMParser().parseFromString(document.getElementById('src').innerHTML,'text/html').documentElement.textContent;"
             "const el=document.getElementById('md');el.innerHTML=window.marked?marked.parse(t):'<pre>'+t.replace(/&/g,'&amp;')"
             ".replace(/</g,'&lt;')+'</pre>';el.querySelectorAll('table').forEach(x=>{const w=document.createElement('div');"
             "w.className='tw';x.parentNode.insertBefore(w,x);w.appendChild(x)});if(location.hash){const a=document.getElementById("
             "location.hash.slice(1));if(a)a.scrollIntoView()}</script>")
    if not md_done:
        (out / "report" / "index.html").write_text(page("Отчёт ReqLens — документ организаторов", rbody), encoding="utf-8")
    shutil.copy2(md_path, out / "report" / "report.md") if md_path.exists() else None

    (out / "slides").mkdir()
    slides = ROOT / "docs" / "slides.html"
    if slides.exists():
        (out / "slides" / "index.html").write_text(slides.read_text(encoding="utf-8").replace('src="assets/', 'src="../assets/')
                                                   .replace("url(assets/", "url(../assets/"), encoding="utf-8")
    (out / "_headers").write_text("/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: strict-origin-when-cross-origin\n",
                                  encoding="utf-8")
    print(f"Сайт собран: {out} (страниц: {len(list(out.rglob('*.html')))})")


def main() -> None:
    ap = argparse.ArgumentParser(prog="python scripts/build_site.py")
    ap.add_argument("--out", default=str(ROOT / "public"))
    ap.add_argument("--studio", default=os.getenv("STUDIO_URL", "https://reqlens-studio.onrender.com"))
    a = ap.parse_args()
    build(Path(a.out), a.studio)


if __name__ == "__main__":
    main()
