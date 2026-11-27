"""v15: проверка интерфейса в браузере (Playwright) — HTML-отчёт, Studio, сайт.

    pip install playwright && playwright install chromium
    python scripts/ui_check.py --report путь/report.html [--studio http://127.0.0.1:8000] [--site public] [--shots папка]

Для каждой страницы: ширины 1440 / 768 / 390, тёмная и светлая тема, ru и kk. Ошибка — если
  • в консоли есть ошибка или исключение страницы;
  • у страницы горизонтальный скролл (scrollWidth > ширины окна);
  • в режиме kk на экране осталась строка из словаря KK без перевода (обход DOM: видимые текстовые узлы, кроме текста
    документа, цитат и замечаний агента — они на русском по ТЗ);
  • на сайте есть ссылка на несуществующий файл (404).
Код выхода 1 при любой ошибке; --shots — скриншоты новых блоков v15 (до/после, ru и kk).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIDTHS = (1440, 768, 390)
NOISE = ("GL Driver Message", "glBlitFramebuffer", "GPU stall due to ReadPixels", "favicon.ico")

# видимые текстовые узлы, которые остались ключом словаря KK (т. е. русской подписью интерфейса без перевода)
UNTRANSLATED_JS = r"""(keys) => {
  const set = new Set(keys), skip = "script,style,pre,code,.doc,.quote,.q-in,.msg,.kv dd,textarea,[lang=ru],.no-kk";
  const out = [], w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    const t = n.nodeValue.trim(), el = n.parentElement;
    if (!t || !el || el.closest(skip)) continue;
    const r = el.getBoundingClientRect(), st = getComputedStyle(el);
    if (!r.width || !r.height || st.visibility === "hidden" || st.display === "none") continue;
    if (set.has(t)) out.push(t);
  }
  return [...new Set(out)];
}"""


# сайт: подписи с data-i18n, у которых нет ключа в словаре KK (site.js + #rl-kk от build_site.py), остаются по-русски
SITE_UNTRANSLATED_JS = r"""(keys) => {
  const set = new Set(keys);
  try { Object.keys(JSON.parse(document.getElementById("rl-kk").textContent)).forEach(k => set.add(k)); } catch (e) {}
  return [...document.querySelectorAll("[data-i18n]")].filter(n => n.getClientRects().length && !set.has(n.dataset.i18n)
    && /[А-Яа-яЁё]/.test(n.textContent)).map(n => n.dataset.i18n + ": " + n.textContent.trim().slice(0, 40));
}"""


def site_kk_keys() -> list[str]:
    js = (ROOT / "site" / "site.js").read_text(encoding="utf-8")
    m = re.search(r"var KK\s*=\s*\{(.*?)\n\s*\};", js, re.S)
    return re.findall(r'"([\w.-]+)"\s*:', m[1] if m else "")


def kk_keys(js_text: str) -> list[str]:
    """Ключи словаря KK из JS (report-i18n.js / Studio) с русским текстом; слова, одинаковые в обоих языках
    («Граф», «Модель», «Экспорт»), не считаются непереведёнными."""
    m = re.search(r"const KK\s*=\s*\{(.*?)\n\s*\};", js_text, re.S)
    body = m[1] if m else ""
    pairs = re.findall(r'"((?:[^"\\]|\\.)+)"\s*:\s*"((?:[^"\\]|\\.)*)"', body)
    return [k for k, v in pairs if re.search("[А-Яа-яЁё]", k) and k != v]


def check_page(b, url: str, keys: list[str], errors: list, label: str, *, hashes=("",), shots: Path | None = None,
               shot_hashes=(), wait=700):
    for theme in ("dark", "light"):
        for lang in ("ru", "kk"):
            for w in WIDTHS:
                page = b.new_page(viewport={"width": w, "height": 900}, reduced_motion="reduce")
                where = f"{label} {theme}/{lang}/{w}"
                page.on("console", lambda m, where=where: errors.append(f"{where}: console {m.text}")
                        if m.type == "error" and not any(n in m.text for n in NOISE) else None)
                page.on("pageerror", lambda e, where=where: errors.append(f"{where}: {e}"))
                page.add_init_script(f"try{{localStorage.setItem('reqlens-theme','{theme}');localStorage.setItem('reqlens-lang','{lang}')}}catch(e){{}}")
                for h in hashes:
                    page.goto(url + h)
                    page.wait_for_timeout(wait)
                    sw = page.evaluate("Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)")
                    if sw > w + 1:
                        errors.append(f"{where}{h}: горизонтальный скролл {sw} > {w}")
                    if lang == "kk":
                        left = page.evaluate(SITE_UNTRANSLATED_JS if label.startswith("site") else UNTRANSLATED_JS, keys)
                        if left:
                            errors.append(f"{where}{h}: без перевода: {left[:8]}")
                    if shots and w == 1440 and theme == "dark" and h in shot_hashes:
                        shots.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(shots / f"{label}-{(h.strip('#') or 'overview')}-{lang}.png"))
                page.close()


def dead_links(site: Path) -> list[str]:
    bad = []
    for html in site.rglob("*.html"):
        text = html.read_text(encoding="utf-8", errors="replace")
        for u in re.findall(r'href="([^"#?]+)', text):
            if re.match(r"(https?:|mailto:|data:|javascript:)", u) or "${" in u:  # шаблон JS, а не ссылка
                continue
            t = (html.parent / u).resolve()
            if not (t.exists() and (t.is_file() or (t / "index.html").exists())):
                bad.append(f"{html.relative_to(site)} → {u}")
    return bad


def serve(folder: Path):
    """Статический http-сервер на свободном порту в фоне (остановится вместе с процессом)."""
    import functools
    import http.server
    import threading

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):  # noqa: D102
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(folder)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main() -> int:
    ap = argparse.ArgumentParser(prog="python scripts/ui_check.py")
    ap.add_argument("--report", help="HTML-отчёт для проверки")
    ap.add_argument("--studio", help="адрес запущенной Studio")
    ap.add_argument("--site", help="папка собранного сайта (public/)")
    ap.add_argument("--shots", help="куда сохранить скриншоты новых блоков")
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    shots = Path(a.shots) if a.shots else None
    report_keys = kk_keys((ROOT / "req_review" / "ui" / "assets" / "report-i18n.js").read_text(encoding="utf-8"))
    studio_keys = kk_keys((ROOT / "req_review" / "ui" / "templates" / "studio.html.j2").read_text(encoding="utf-8"))
    with sync_playwright() as p:
        b = p.chromium.launch()
        if a.report:
            url = Path(a.report).resolve().as_uri()
            check_page(b, url, report_keys, errors, "report", hashes=("", "#revised", "#trace", "#bank"), shots=shots,
                       shot_hashes=("", "#revised", "#trace", "#bank"))
        if a.studio:
            check_page(b, a.studio.rstrip("/") + "/", studio_keys, errors, "studio", hashes=("",), shots=shots, shot_hashes=("",), wait=1500)
            check_page(b, a.studio.rstrip("/") + "/?example=1", studio_keys, errors, "studio-example", hashes=("",), wait=2500)
        if a.site:
            site = Path(a.site)
            errors += [f"site: ссылка на 404: {x}" for x in dead_links(site)]
            srv = serve(site)  # по http, как на хостинге: шрифты из file:// браузер не грузит (CORS)
            for page_rel in ("index.html", "proof/index.html"):
                if (site / page_rel).exists():
                    check_page(b, f"http://127.0.0.1:{srv.server_port}/{page_rel.replace('index.html', '')}", site_kk_keys(), errors, f"site/{page_rel.split('/')[0]}",
                               shots=shots, shot_hashes=("",))
        b.close()
    for e in errors:
        print("✗", e)
    print(f"Ошибок: {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
