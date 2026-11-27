"""Видео-демо ReqLens на ~60 секунд (MP4) — по настоящему прогону, без сети и без обращений к модели.

    pip install playwright imageio-ffmpeg && playwright install chromium
    python review.py bench/real/notifications.md reports/video/report.md --answers examples/answers/organizers_answers.md         --rules fintech                                                          # настоящий прогон (нужен ключ)
    python scripts/demo_video.py reports/video/report.json docs/assets/demo-60s.mp4

Сцены (v15): титул → Studio «Открыть готовый пример» → «Кратко» после ответов аналитика → «Исправленное ТЗ»
(было → стало) → трассировка «требование ↔ API» → «Чек-лист банка» → документ с подсветкой → финальная карточка.
Сцена показывается, только если поле есть в отчёте (прогон с --answers и --rules fintech).
Подписи накладываются поверх экрана; все цифры берутся из report.json и *_before_after.md — ничего не рисуется вручную.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W, H = 1280, 720
CAP = ("(t) => { let c = document.getElementById('__cap'); if (!c) { c = document.createElement('div'); c.id = '__cap';"
       " c.style.cssText = 'position:fixed;left:50%;bottom:26px;transform:translateX(-50%);max-width:88%;background:rgba(2,3,12,.86);"
       "color:#F4F5FF;padding:12px 24px;border-radius:999px;border:1px solid rgba(142,155,255,.35);font:500 20px/1.35 Inter,system-ui,Segoe UI,sans-serif;"
       "z-index:2147483647;backdrop-filter:blur(14px);box-shadow:0 20px 60px rgba(2,3,12,.5);text-align:center'; document.body.appendChild(c); }"
       " c.textContent = t; }")
# оформление v3 «Ecliptic Dawn»: ночь сверху, рассвет внизу; тёмный текст — на рассвете
DAWN = ("linear-gradient(180deg,#02020E 0%,#02020E 30%,#080F36 42%,#192B84 52%,#4459C8 62%,#9191D3 74%,#D9C6DA 88%,#E3CDDB 100%)")


def card(title: str, sub: str, foot: str = "") -> str:
    return f"""<!doctype html><html lang="ru"><meta charset="utf-8"><body style="margin:0;height:100vh;display:grid;place-items:end center;
      background:#02020E {DAWN} bottom/100% 1100px no-repeat;color:#050719;font-family:Inter,system-ui,Segoe UI,sans-serif">
      <div style="position:fixed;top:40px;left:0;right:0;text-align:center;font-size:20px;letter-spacing:.2em;color:#8E9BFF;font-weight:500">REQLENS</div>
      <div style="text-align:center;max-width:1040px;padding:0 40px 70px">
        <div style="font-size:58px;font-weight:500;letter-spacing:-.04em;line-height:1.05;margin:0 0 18px">{title}</div>
        <div style="font-size:24px;line-height:1.4;color:#1B2052">{sub}</div>
        <div style="font-size:17px;margin-top:24px;color:#2A2F55">{foot}</div></div></body></html>"""


def md_table_html(md: str) -> str:
    rows = [ln for ln in md.splitlines() if ln.startswith("|") and not re.match(r"^\|\s*-", ln)]
    head, body = rows[0], rows[1:]
    cell = lambda s: re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s.strip())  # noqa: E731
    tr = lambda r, tag: "<tr>" + "".join(f"<{tag}>{cell(c)}</{tag}>" for c in r.strip().strip("|").split("|")) + "</tr>"  # noqa: E731
    title = re.search(r"^# (.+)$", md, re.M)
    return f"""<!doctype html><html lang="ru"><meta charset="utf-8"><body style="margin:0;padding:48px 64px;background:#02030C;
      font-family:Inter,system-ui,Segoe UI,sans-serif;color:#F4F5FF"><div style="font-size:14px;letter-spacing:.16em;color:#8E9BFF;font-weight:500">ИСПРАВИЛ → ПРОВЕРИЛ ЗАНОВО</div>
      <h1 style="font-size:40px;font-weight:500;letter-spacing:-.03em;margin:10px 0 24px">{title.group(1) if title else 'До / После'}</h1>
      <table style="border-collapse:collapse;font-size:21px;background:#0B0E24;border:1px solid rgba(140,155,255,.2);border-radius:20px;overflow:hidden">
      {tr(head, 'th')}{''.join(tr(r, 'td') for r in body)}</table>
      <style>th,td{{padding:12px 26px;border-bottom:1px solid rgba(140,155,255,.14);text-align:left}}th{{color:#A3A8C9;font-weight:500}}td b{{color:#5EE6B0}}</style></body></html>"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def to_mp4(webm: Path, out: Path, width: int = 1280, crf: int = 34) -> Path:
    ff = shutil.which("ffmpeg")
    if not ff:
        import imageio_ffmpeg

        ff = imageio_ffmpeg.get_ffmpeg_exe()
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(webm), "-vf", f"fps=15,scale={width}:-2",
                    "-c:v", "libx264", "-preset", "veryslow", "-crf", str(crf), "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", "-an", str(out)], check=True)
    return out


def main(argv: list[str]) -> int:
    from playwright.sync_api import sync_playwright

    rj = Path(argv[0] if argv else ROOT / "reports" / "video" / "report.json").resolve()
    out = Path(argv[1] if len(argv) > 1 else ROOT / "docs" / "assets" / "demo-60s.mp4").resolve()
    html = rj.with_suffix(".html")
    data = json.loads(rj.read_text(encoding="utf-8"))
    pp, ca = data["passport"], data.get("citation_audit") or {}
    fs = sum(len(r["findings"]) for r in data["requirements"]) + len(data["set_findings"])
    crit = sum(1 for r in data["requirements"] for f in r["findings"] if f["severity"] == "critical") + \
        sum(1 for f in data["set_findings"] if f["severity"] == "critical")
    n_req = sum(1 for r in data["requirements"] if r.get("kind", "requirement") == "requirement")  # без строк API и приёмки
    ans = data.get("answers") or {}
    rs, rev = ans.get("summary") or {}, ans.get("revised") or (data.get("revised") or {})
    port = free_port()
    env = {**os.environ, "LLM_PROVIDER": "mock", "PYTHONIOENCODING": "utf-8", "STUDIO_PORT": str(port),
           "REQLENS_DATA": tempfile.mkdtemp(prefix="reqlens-video-")}
    provider, _, model = pp.get("model", "").partition(" / ")
    # Studio показывает модель настоящего прогона (без плашки mock); готовый пример модель не вызывает, ключ не нужен
    if provider == "gemini":
        env.update(LLM_PROVIDER="gemini", GEMINI_MODEL=model, GEMINI_API_KEY="demo-replay-no-calls")
    elif provider.startswith("openai"):
        env.update(LLM_PROVIDER="openai", OPENAI_MODEL=model, OPENAI_API_KEY="demo-replay-no-calls",
                   OPENAI_BASE_URL=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"))
    srv = subprocess.Popen([sys.executable, "-m", "req_review.web", "--demo", str(rj)], cwd=ROOT, env=env)
    vids = Path(tempfile.mkdtemp(prefix="reqlens-video-raw-"))
    # отчёт — по http, как из Studio и с сайта: тогда он дочитывает соседний report.json (правила банка целиком,
    # граф трассировки, закрытые блокеры); из file:// показывается только компактный data.engine
    import functools
    import http.server
    import threading

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):  # noqa: D102
            pass

    files = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(rj.parent)))
    threading.Thread(target=files.serve_forever, daemon=True).start()
    report_url = f"http://127.0.0.1:{files.server_port}/{html.name}"
    try:
        for _ in range(150):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(viewport={"width": W, "height": H}, record_video_dir=str(vids), record_video_size={"width": W, "height": H})
            pg = ctx.new_page()
            cap = lambda t: pg.evaluate(CAP, t)  # noqa: E731
            # 1. титул
            pg.set_content(card("Дефекты требований — до первой строчки кода",
                                "ИИ-агент проверяет ТЗ банка по ISO/IEC/IEEE 29148 и IEEE 830",
                                f"Документ организаторов · {esc(pp.get('document', ''))}"))
            pg.wait_for_timeout(3500)
            # 2. Studio: «Открыть готовый пример» — отчёт по документу организаторов без загрузки и квоты
            pg.goto(f"http://127.0.0.1:{port}/")
            pg.wait_for_selector("#example", timeout=15000)
            cap("Studio: жюри открывает готовый пример — без загрузки файла и без квоты")
            pg.wait_for_timeout(2600)
            pg.click("#example")
            pg.wait_for_selector("#s-result.active", timeout=15000)
            cap("Отчёт по документу организаторов открыт сразу: вердикт, балл, файлы для скачивания")
            pg.wait_for_timeout(5000)

            def view(h: str):  # раздел отчёта с начала страницы (смена #hash не перезагружает документ)
                pg.goto(report_url + h)
                pg.wait_for_timeout(700)
                pg.evaluate("window.scrollTo(0, 0)")
                pg.wait_for_timeout(300)
            if ans:  # 3. «Кратко»: ответы аналитика → перепроверка
                view("")
                pg.evaluate("(() => { const b = document.getElementById('brief'); if (b) b.scrollIntoView({block:'start'}); })()")
                cap(f"Аналитик ответил на вопросы → перепроверка: закрыто блокеров {rs.get('blockers_closed', '—')} из "
                    f"{rs.get('blockers_total', '—')}, открытых замечаний {rs.get('open_before', '—')} → {rs.get('open_after', '—')}")
                pg.wait_for_timeout(6500)
            if rev:  # 4. «Было → Стало»
                view("#revised")
                cap(f"Исправленное ТЗ: было → стало ({len(rev.get('changed') or [])}), новые требования ({len(rev.get('added') or [])}), "
                    f"осталось уточнить ({len(rev.get('open') or [])})")
                pg.wait_for_timeout(3000)
                pg.mouse.wheel(0, 520)
                pg.wait_for_timeout(3500)
            if data.get("traceability"):  # 5. трассировка «требование ↔ API»
                view("#trace")
                gaps = (data["traceability"].get("stats") or {}).get("gaps", "—")
                cap(f"Трассировка: требование ↔ поле экрана ↔ параметр API ↔ HTTP-код · разрывов {gaps} — красным")
                pg.wait_for_timeout(7500)
            if data.get("bank_rules"):  # 6. чек-лист банка
                view("#bank")
                br = data["bank_rules"]
                cap(f"Чек-лист банка проверяет код, без модели: сработало {br.get('fired', 0)} · выполнено {br.get('passed', 0)}"
                    f" · не применимо {br.get('not_applicable', 0)}")
                pg.wait_for_timeout(4500)
                pg.mouse.wheel(0, 420)
                pg.wait_for_timeout(3500)
            # 7. документ с подсветкой и карточкой замечания
            view("#doc")
            cap(f"Каждое замечание — дословная цитата: {ca.get('verified', '—')} из {ca.get('total', '—')} подтверждены кодом")
            pg.evaluate("(() => { const m = document.querySelector('mark.hl.sev-critical, mark.hl'); if (m) { m.scrollIntoView({block:'center'}); m.click(); } })()")
            pg.wait_for_timeout(5000)
            pg.keyboard.press("Escape")
            # 8. финал
            pg.set_content(card(f"{fs} замечаний · {crit} критичных",
                                f"Каждая цитата проверена кодом · {n_req} требований"
                                + (f" · закрыто блокеров {rs.get('blockers_closed')} из {rs.get('blockers_total')}" if rs else ""),
                                f"{esc(pp.get('model', ''))} · {esc(pp.get('agent_version', ''))}"))
            pg.wait_for_timeout(4000)
            video = pg.video.path()
            ctx.close()
            b.close()
        webm = out.with_suffix(".webm")
        webm.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(video, webm)
        print(f"видео (WebM): {webm} · {webm.stat().st_size // 1024} КБ")
        try:
            mp4 = to_mp4(webm, out)
            for crf in (36, 38, 40):  # правило репозитория: файлы меньше 1 МБ
                if mp4.stat().st_size < 1000 * 1024:
                    break
                mp4 = to_mp4(webm, out, crf=crf)
            webm.unlink(missing_ok=True)
            print(f"видео (MP4): {mp4} · {mp4.stat().st_size // 1024} КБ")
        except ImportError:
            print("MP4 не собран: pip install imageio-ffmpeg (WebM готов)")
        return 0
    finally:
        files.shutdown()
        srv.terminate()
        srv.wait(timeout=10)
        shutil.rmtree(vids, ignore_errors=True)


def esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
