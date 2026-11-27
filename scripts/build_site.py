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
body{background:var(--bg);color:var(--text);margin:0}
.site{max-width:var(--max-width);margin:0 auto;padding:0 16px 24px}
.pagebar{position:sticky;top:8px;z-index:5}
.pagebar nav{display:flex;gap:4px;margin-left:auto;align-items:center;flex-wrap:wrap}
.hero{padding:56px 24px 28px;margin-top:8px;border-radius:var(--r-hero);background:radial-gradient(900px 400px at 0% 0%,color-mix(in srgb,var(--brand) 14%,transparent),transparent 60%)}
.k{font:800 clamp(32px,5.2vw,64px)/1.05 var(--font-sans);letter-spacing:-.035em;margin:12px 0 0}
.lead{font:400 clamp(16px,1.6vw,20px)/1.55 var(--font-sans);color:var(--text-2);max-width:860px;margin:18px 0 0}
.cta{display:flex;flex-wrap:wrap;gap:10px;margin-top:24px}
.section{margin-top:48px}.section h2{font:500 clamp(28px,3.4vw,44px)/1.1 var(--font-sans);letter-spacing:-.035em;margin:6px 0 18px;color:var(--text)}
.section>.caption{color:var(--text-3)}.section>p a{color:var(--brand)}
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
    <a class="btn btn-ghost btn-sm" href="{{ root }}proof/">Доказательства</a>
    <a class="btn btn-ghost btn-sm" href="{{ root }}slides/">Слайды</a>
    <button class="btn btn-round" id="theme" type="button" aria-label="Сменить тему">{{ icon("moon", 18) }}</button>
    {% if studio %}<a class="btn btn-primary btn-sm" href="{{ studio }}">Studio {{ icon("arrow-up-right", 16) }}</a>{% else %}<a class="btn btn-primary btn-sm" href="{{ root }}">На главную</a>{% endif %}
  </nav>
</header>
{{ body|safe }}
<footer class="footer" style="color:var(--text-3)">ReqLens · хакатон BCC-HUB × MNU · ISO/IEC/IEEE 29148:2018, IEEE Std 830-1998 · сайт собирается из репозитория при каждом деплое</footer>
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
        html = re.sub(r'<p\b[^>]*\bdata-nostudio\b[^>]*>.*?</p>\s*', "", html, flags=re.S)
        html = html.replace("data-studio-note hidden", "data-studio-note")
        html = re.sub(r'(<a\b[^>]*\bdata-studio\b)\s+hidden([^>]*\bhref=")[^"]*(")', rf"\1\g<2>{studio}\3", html)
    else:
        html = re.sub(a.format("data-studio"), "", html, flags=re.S)
        html = re.sub(r'<p\b[^>]*\bdata-studio-note\b[^>]*>.*?</p>\s*', "", html, flags=re.S)
    if not repo_public:
        html = re.sub(a.format("data-gh"), "", html, flags=re.S)
    return html


def blind_html() -> str:
    """Раздел «Слепые документы» — только если он есть в bench/RESULTS.md и посчитан на модели (не mock)."""
    from html import escape

    from req_review.ui.styleguide import blind_results

    b = blind_results()
    if not b:
        return ""
    head = "".join(f'<th scope="col">{escape(h)}</th>' for h in b["head"])
    rows = "".join("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in r) + "</tr>" for r in b["rows"])
    return f"""<section class="panel" id="blind">
  <p class="eyebrow" data-i18n="blind.eyebrow">Слепая оценка</p>
  <h2 class="h1" data-i18n="blind.t">Документы, которые агент видит впервые.</h2>
  <div class="table"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>
  <p class="note" data-i18n="blind.note">Документы написаны не командой, ключ дефектов хранился отдельно, агент на них не настраивался. Цифры — из bench/RESULTS.md.</p>
  <p class="note">{escape(b["meta"])}</p>
</section>
"""


_W = r"[\p{L}\p{N}_]"


def js_regex(p: str) -> str:
    r"""Регулярное выражение Python → JS (флаг u): \w и \b в JS не знают кириллицу, заменяем на классы Unicode."""
    out, cls, i = [], False, 0
    while i < len(p):
        t = p[i:i + 2]
        if t == r"\w":
            out.append(_W[1:-1] if cls else _W)  # внутри [...] — без собственных скобок
        elif t == r"\b" and not cls:
            out.append(f"(?:(?<={_W})(?!{_W})|(?<!{_W})(?={_W}))")
        elif p[i] == "\\":
            out.append(t)  # прочие экранирования — как есть
        else:
            cls = (cls or p[i] == "[") and not (cls and p[i] == "]")
            out.append(p[i])
            i += 1
            continue
        i += 2
    return "".join(out)


def rules_payload() -> dict:
    """Словарные правила агента (req_review/rules.py — только чтение) для виджета «Проверьте одну фразу» на сайте."""
    from req_review import rules as R
    from req_review.criteria import criterion_name

    return {"rules": [{"p": js_regex(r.pattern), "crit": r.criterion, "name": criterion_name(r.criterion), "sev": r.severity,
                       "problem": r.problem, "fix": r.fix, "num": bool(r.skip_if_number_near)} for r in R.RULES],
            "and": js_regex(R._AND_SPLIT.pattern), "kk": js_regex(R._KK_SPLIT.pattern),
            "sent": js_regex(R._SENT.pattern), "id": js_regex(r"\s*\**\s*[\w-]{1,10}\s*[-.]?\s*\d+[.)]?\**\s*"),
            "atomic": {"crit": "singular", "name": criterion_name("singular"), "sev": "minor",
                       "problem": "Неатомарное требование: в одном пункте несколько самостоятельных правил — их нельзя по отдельности "
                                  "трассировать к критериям приёмки и изменять, не задев соседние.",
                       "fix": "Разбить пункт на отдельные требования — по одному правилу в каждом, с собственным критерием приёмки."},
            "singular": {"crit": "singular", "name": criterion_name("singular"), "sev": "minor",
                         "problem": "Похоже, в одной формулировке объединено несколько требований.",
                         "fix": "Разделить на отдельные требования с собственными идентификаторами."}}


def try_html() -> str:
    """Секция «Проверьте одну фразу»: правила агента работают в браузере — без модели, сервера и ключа.
    Без JS секция скрыта (атрибут hidden снимает site.js), правила вшиты в страницу — отдельного запроса нет."""
    try:
        data = json.dumps(rules_payload(), ensure_ascii=False).replace("</", "<\\/")
    except Exception as e:  # noqa: BLE001 — без правил сайт собирается, просто без виджета
        print(f"Виджет «Проверьте одну фразу» пропущен: {e}")
        return ""
    ex = ["Система должна быстро проверять получателя и показывать удобный экран подтверждения.",
          "Комиссия взимается при необходимости, её размер — TBD.",
          "Поддерживаются карты Visa, Mastercard и т.д., оплата картой и/или по QR-коду."]
    chips = "".join(f'<button class="try-chip" type="button" data-try="{i}">{i + 1}</button>' for i in range(len(ex)))
    return f"""<section class="panel try" id="try" hidden>
  <p class="eyebrow" data-i18n="try.eyebrow">Попробуйте сами</p>
  <h2 class="h1" data-i18n="try.t">Проверьте одну фразу — прямо здесь.</h2>
  <p class="lead" data-i18n="try.lead">Впишите требование: словарные правила агента подсветят размытые слова и объяснят, как исправить. Без модели, сервера и ключа — всё считается в браузере.</p>
  <form class="try-form" id="try-form">
    <label class="sr-only" for="try-q" data-i18n="try.label">Текст требования</label>
    <textarea id="try-q" rows="3" maxlength="1000" spellcheck="false">{ex[0]}</textarea>
    <div class="try-bar"><span class="note" style="margin:0" data-i18n="try.ex">Примеры:</span>{chips}<span class="grow"></span>
      <button class="btn btn-white btn-sm" type="submit"><span data-i18n="try.go">Проверить</span><i aria-hidden="true">›</i></button></div>
  </form>
  <div class="try-out" id="try-out" aria-live="polite"></div>
  <p class="note" data-i18n="try.note">Это только первый, словарный слой агента. Полная проверка — модель, тест-проба, противоречия между требованиями — в Studio или одной командой ниже.</p>
  <script type="application/json" id="rl-rules">{data}</script>
  <script type="application/json" id="rl-examples">{json.dumps(ex, ensure_ascii=False)}</script>
</section>
"""


def _load(rel: str) -> dict | None:
    p = ROOT / rel
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None


def _pct(x) -> str:
    return f"{round(100 * x)} %" if isinstance(x, (int, float)) else "—"


def _generic_block(title: str, rel: str, cmd: str, d) -> str:
    """Блок для файла бенчмарка, формат которого задаёт движок (v13): числовые поля верхнего уровня таблицей."""
    from html import escape

    rows = "".join(f"<tr><td>{escape(str(k))}</td><td>{escape(str(v if not isinstance(v, float) else round(v, 4)))}</td></tr>"
                   for k, v in (d.items() if isinstance(d, dict) else []) if isinstance(v, (int, float, str)) and len(str(v)) < 80)
    return (f'<section class="section"><div class="caption">{escape(rel)}</div><h2>{escape(title)}</h2>'
            f'<div class="md"><div class="tw"><table><tbody>{rows}</tbody></table></div>'
            f'<p class="small">Пересчитать: <code>{escape(cmd)}</code></p></div></section>')


def proof_html() -> str:
    """v13: страница «Доказательства» — только цифры из файлов, которые пересчитываются командой (рядом — команда).
    Файла нет — блока нет (а не пустая таблица)."""
    from html import escape

    out = []
    res = _load("bench/results.json")
    if res:
        names = {"payments": "Оплата услуг", "credit": "Онлайн-кредит", "onboarding": "Открытие счёта",
                 "deposit_kk": "Онлайн-депозит (қазақ тілі)", "cards": "Перевыпуск карты (DOCX, таблицы)", "cashback": "Кэшбэк по категориям"}
        rows = "".join(f"<tr><td>{escape(names.get(k, k))}</td><td>{c['tp']} из {c['total']}</td><td>{_pct(c['recall'])}</td>"
                       f"<td>{_pct(c['precision'])}</td></tr>" for k, c in res.get("cases", {}).items())
        out.append(f"""<section class="section"><div class="caption">bench/results.json</div><h2>Бенчмарк: документы с известными дефектами</h2>
<div class="grid g-4">
  <article class="kpi"><span class="lbl">Полнота (recall)</span><div class="kpi-num">{_pct(res.get("recall"))}</div><div class="sub">{res.get("tp")} из {res.get("total")} дефектов</div></article>
  <article class="kpi"><span class="lbl">Точность (precision)</span><div class="kpi-num">{_pct(res.get("precision"))}</div><div class="sub">F1 {_pct(res.get("f1"))}</div></article>
  <article class="kpi"><span class="lbl">Ложные тревоги на чистых</span><div class="kpi-num">{res.get("fp_on_clean", "—")}</div><div class="sub">на {res.get("clean", "—")} заведомо чистых требованиях</div></article>
  <article class="kpi"><span class="lbl">Модель</span><div class="small" style="margin-top:10px">{escape(str(res.get("label", "")))}</div><div class="sub">{escape(str(res.get("date", "")))}</div></article>
</div>
<div class="md"><div class="tw"><table><thead><tr><th>Документ</th><th>Найдено</th><th>Recall</th><th>Precision</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="small">Пересчитать: <code>python bench/run.py</code></p></div></section>""")
    base = _load("bench/baseline/results.json")
    if base and all(k in base for k in ("A_rules", "B_bare", "C_reqlens")):
        lab = {"A_rules": "Только правила (без модели)", "B_bare": "Один промпт в ту же модель", "C_reqlens": "ReqLens (агент)"}
        rows = ""
        for k in ("A_rules", "B_bare", "C_reqlens"):
            b, o = base[k].get("bench", {}), base[k].get("organizers", {})
            rows += (f"<tr><td>{'<b>' if k == 'C_reqlens' else ''}{lab[k]}{'</b>' if k == 'C_reqlens' else ''}</td><td>{_pct(b.get('recall'))}</td>"
                     f"<td>{_pct(b.get('precision'))}</td><td>{o.get('found', '—')} из {o.get('total', '—')}</td>"
                     f"<td>{o.get('critical_found', '—')} из {o.get('critical_total', '—')}</td></tr>")
        out.append(f"""<section class="section"><div class="caption">bench/baseline/results.json</div><h2>ReqLens против одного промпта в ту же модель</h2>
<div class="md"><div class="tw"><table><thead><tr><th>Как проверяли</th><th>Recall (бенчмарк)</th><th>Precision</th><th>Документ организаторов</th><th>Критичные</th></tr></thead>
<tbody>{rows}</tbody></table></div><p class="small">Пересчитать: <code>python bench/baseline_eval.py</code></p></div></section>""")
    rep = _load("reports/requirements-report.json")
    if rep:
        pp, ca = rep.get("passport", {}), rep.get("citation_audit") or {}
        found = ""
        try:
            sys.path.insert(0, str(ROOT / "bench"))
            from real_eval import evaluate

            ev = evaluate(rep)
            found = f"{ev['found']} из {ev['total']}"
        except Exception:  # noqa: BLE001
            pass
        out.append(f"""<section class="section"><div class="caption">reports/requirements-report.json</div><h2>Документ организаторов: отчёт для сдачи</h2>
<div class="grid g-4">
  <article class="kpi"><span class="lbl">Ожидаемые дефекты</span><div class="kpi-num">{escape(found or "—")}</div><div class="sub">сверка кодом: <code>python bench/real_eval.py</code></div></article>
  <article class="kpi"><span class="lbl">Цитаты найдены в тексте</span><div class="kpi-num">{ca.get("verified", "—")} / {ca.get("total", "—")}</div><div class="sub">аудит цитат кодом</div></article>
  <article class="kpi"><span class="lbl">Время прогона</span><div class="kpi-num">{pp.get("duration_s", "—")} с</div><div class="sub">профиль {escape(str(pp.get("profile", "")))} · обращений {pp.get("calls", "—")}</div></article>
  <article class="kpi"><span class="lbl">Модель</span><div class="small" style="margin-top:10px">{escape(str(pp.get("model", "")))}</div><div class="sub">{escape(str(pp.get("started", "")))}</div></article>
</div></section>""")
    # v13 (движок, PR v13-engine): блоки появятся, когда файлы будут пересчитаны командой
    for rel, title, cmd in (("bench/score.json", "Полнота и точность с доверительными интервалами", "python bench/score.py"),
                            ("bench/ablation.json", "Вклад каждого слоя агента", "python bench/ablation.py"),
                            ("bench/transitions.json", "Реакция на исправления", "python bench/transitions.py"),
                            ("bench/stability.json", "Устойчивость: одно и то же замечание в N прогонах", "python bench/stability.py"),
                            ("bench/real/verify.json", "verify: цитаты и SHA-256 отчёта для сдачи", "python review.py verify …")):
        d = _load(rel)
        if d:
            out.append(_generic_block(title, rel, cmd, d))
    if not out:
        return ""
    body = ('<section class="hero"><div class="caption">Доказательства</div><h1 class="k">Цифры, которые можно пересчитать.</h1>'
            '<p class="lead">Каждая цифра на этой странице взята из файла репозитория и пересчитывается командой, указанной рядом. '
            'Нет файла — нет блока.</p></section>' + "\n".join(out))
    from req_review.ui import env

    return env().from_string(PAGE).render(title="ReqLens · Доказательства", root="../", studio="", body=body)


def report_pdf(out_dir: Path) -> bool:
    """PDF отчёта для сдачи рядом с /report/: готовый reports/requirements-report.pdf или сборка из Markdown."""
    pdf = ROOT / "reports" / "requirements-report.pdf"
    if pdf.exists():
        shutil.copy2(pdf, out_dir / "report.pdf")
        return True
    md = ROOT / "reports" / "requirements-report.md"
    if not md.exists():
        return False
    try:
        from req_review.pdf_report import markdown_to_pdf

        markdown_to_pdf(md.read_text(encoding="utf-8"), out_dir / "report.pdf", "Отчёт ReqLens — документ организаторов")
        return (out_dir / "report.pdf").exists()
    except Exception as e:  # noqa: BLE001 — без шрифта/reportlab сайт собирается без PDF
        print(f"PDF отчёта не собран: {e}")
        return False


def report_siblings(rep: str, out_dir: Path) -> str:
    """Журнал, шаблон ответов и повестка решений лежат рядом с отчётом. Копируем те, что есть в reports/;
    если журнала нет (reports/ в git не хранит .log), убираем passport.log из данных — ссылок на 404 в отчёте не будет."""
    m = re.search(r'"log": "([\w.-]+)\.log"', rep)
    if not m:
        return rep
    stem = m[1]
    found = False
    for name in (f"{stem}.log", f"{stem}_answers_template.md", f"{stem}_decisions.md"):
        if (ROOT / "reports" / name).exists():
            shutil.copy2(ROOT / "reports" / name, out_dir / name)
            found = found or name.endswith(".log")
    return rep if found else rep.replace(m[0], '"log": ""')


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
    sj = ROOT / "bench" / "score.json"
    if sj.exists():  # v15: эталон из 150 и честная точность — диапазон, пока проверены не все замечания
        g = json.loads(sj.read_text(encoding="utf-8"))
        prec = (f"{round(100 * g['precision_strict'])}–{round(100 * g['precision'])} %" if g.get("unjudged")
                else f"{round(100 * g['precision'])} %")
        vals["recall-precision"] = f"{round(100 * g['recall'])} % / {prec}"
    try:  # самопроверка соответствия ТЗ — тем же кодом, что в CI
        import subprocess

        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "tz_check.py")], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", cwd=ROOT, timeout=120).stdout
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
    html = html.replace("<!-- blind -->\n", blind_html()).replace("<!-- try -->\n", try_html())
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
        (out / "report" / "index.html").write_text(report_siblings(rep, out / "report"), encoding="utf-8")
    else:
        md = md_path.read_text(encoding="utf-8") if md_path.exists() else "# Отчёт ещё не сформирован"
        title = (re.search(r"^#\s+(.+)$", md, re.M) or [None, "Отчёт"])[1]
        (out / "report" / "index.html").write_text(md_page(md, title=title, caption="Отчёт", download="report.md" if md_path.exists() else None,
                                                           root="../", studio=studio), encoding="utf-8")
    has_pdf = report_pdf(out / "report")
    if not has_pdf:  # ссылки на PDF без файла — убираем (без 404)
        html = re.sub(r'<a\b[^>]*\bdata-pdf\b[^>]*>.*?</a>\s*', "", (out / "index.html").read_text(encoding="utf-8"), flags=re.S)
        (out / "index.html").write_text(html, encoding="utf-8")
    proof = proof_html()
    if proof:
        (out / "proof").mkdir()
        (out / "proof" / "index.html").write_text(proof, encoding="utf-8")
    else:
        html = re.sub(r'<a\b[^>]*\bdata-proof\b[^>]*>.*?</a>\s*', "", (out / "index.html").read_text(encoding="utf-8"), flags=re.S)
        (out / "index.html").write_text(html, encoding="utf-8")
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
