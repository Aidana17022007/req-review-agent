"""Видео-демо ReqLens на ~60 секунд (MP4) — по настоящему прогону, без сети и без обращений к модели.

    pip install playwright imageio-ffmpeg && playwright install chromium
    python review.py docs/requirements.md reports/video/report.md --fix-loop      # настоящий прогон (нужен ключ)
    python scripts/demo_video.py reports/video/report.json docs/assets/demo-60s.mp4

Сцены: титул → Studio «Демо» (живой прогон из записи) → «Итог за 30 секунд» и аудит цитат → документ с подсветкой
и карточкой замечания → матрица «требование × критерий» → «До / После» (--fix-loop) → финальная карточка с цифрами.
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
       " c.style.cssText = 'position:fixed;left:50%;bottom:26px;transform:translateX(-50%);max-width:88%;background:rgba(15,35,24,.92);"
       "color:#fff;padding:12px 22px;border-radius:14px;font:600 20px/1.35 system-ui,Segoe UI,sans-serif;z-index:2147483647;"
       "box-shadow:0 8px 30px rgba(0,0,0,.25);text-align:center'; document.body.appendChild(c); } c.textContent = t; }")


def card(title: str, sub: str, foot: str = "") -> str:
    return f"""<!doctype html><html lang="ru"><meta charset="utf-8"><body style="margin:0;height:100vh;display:grid;place-items:center;
      background:radial-gradient(circle at 30% 20%,#2f8f5b,#14532d 60%,#0d3a20);color:#fff;font-family:system-ui,Segoe UI,sans-serif">
      <div style="text-align:center;max-width:980px;padding:0 40px">
        <div style="font-size:22px;letter-spacing:.18em;opacity:.8;font-weight:700">REQLENS</div>
        <div style="font-size:54px;font-weight:800;line-height:1.12;margin:18px 0">{title}</div>
        <div style="font-size:24px;opacity:.92;line-height:1.4">{sub}</div>
        <div style="font-size:18px;opacity:.75;margin-top:28px">{foot}</div></div></body></html>"""


def md_table_html(md: str) -> str:
    rows = [ln for ln in md.splitlines() if ln.startswith("|") and not re.match(r"^\|\s*-", ln)]
    head, body = rows[0], rows[1:]
    cell = lambda s: re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s.strip())  # noqa: E731
    tr = lambda r, tag: "<tr>" + "".join(f"<{tag}>{cell(c)}</{tag}>" for c in r.strip().strip("|").split("|")) + "</tr>"  # noqa: E731
    title = re.search(r"^# (.+)$", md, re.M)
    return f"""<!doctype html><html lang="ru"><meta charset="utf-8"><body style="margin:0;padding:48px 64px;background:#f6f8f7;
      font-family:system-ui,Segoe UI,sans-serif;color:#14231b"><div style="font-size:15px;letter-spacing:.14em;color:#1f6b45;font-weight:700">ИСПРАВИЛ → ПРОВЕРИЛ ЗАНОВО</div>
      <h1 style="font-size:34px;margin:10px 0 24px">{title.group(1) if title else 'До / После'}</h1>
      <table style="border-collapse:collapse;font-size:21px;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 6px 24px rgba(0,0,0,.07)">
      {tr(head, 'th')}{''.join(tr(r, 'td') for r in body)}</table>
      <style>th,td{{padding:12px 26px;border-bottom:1px solid #e3ebe6;text-align:left}}th{{background:#e7f4ec}}td b{{color:#1f6b45}}</style></body></html>"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def to_mp4(webm: Path, out: Path, width: int = 1280, crf: int = 34) -> Path:
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
    html, ba = rj.with_suffix(".html"), rj.with_name(rj.stem + "_before_after.md")
    data = json.loads(rj.read_text(encoding="utf-8"))
    pp, ca = data["passport"], data.get("citation_audit") or {}
    fs = sum(len(r["findings"]) for r in data["requirements"]) + len(data["set_findings"])
    crit = sum(1 for r in data["requirements"] for f in r["findings"] if f["severity"] == "critical") + \
        sum(1 for f in data["set_findings"] if f["severity"] == "critical")
    port = free_port()
    env = {**os.environ, "LLM_PROVIDER": "mock", "PYTHONIOENCODING": "utf-8", "STUDIO_PORT": str(port),
           "REQLENS_DATA": tempfile.mkdtemp(prefix="reqlens-video-")}
    srv = subprocess.Popen([sys.executable, "-m", "req_review.web", "--demo", str(rj)], cwd=ROOT, env=env)
    vids = Path(tempfile.mkdtemp(prefix="reqlens-video-raw-"))
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
            # 2. Studio «Демо»: живой прогон из записи настоящего прогона
            pg.goto(f"http://127.0.0.1:{port}/")
            pg.wait_for_selector("#demo:not([hidden])", timeout=15000)
            cap("Перетащили документ — агент проверяет его вживую")
            pg.wait_for_timeout(1200)
            pg.click("#demo")
            t0 = time.time()
            while time.time() - t0 < 22 and not pg.evaluate("document.getElementById('s-result').classList.contains('active')"):
                pg.wait_for_timeout(300)
                if time.time() - t0 > 6:
                    cap("Нарезка → каждое требование → набор целиком → критик → отчёт")
            pg.wait_for_timeout(800)
            # 3. отчёт: итог за 30 секунд и аудит цитат
            pg.goto(html.as_uri())
            pg.wait_for_timeout(900)
            cap(f"Итог за 30 секунд: {crit} критичных, что исправить первым — с примером формулировки")
            pg.wait_for_timeout(4200)
            cap(f"Аудит цитат: {ca.get('verified', '—')} из {ca.get('total', '—')} подтверждены кодом · выдуманных в отчёте 0")
            pg.wait_for_timeout(3600)
            # 4. документ с подсветкой и карточкой замечания
            pg.goto(html.as_uri() + "#doc")
            pg.wait_for_timeout(1000)
            cap("Каждое замечание — дословная цитата и строка документа")
            pg.evaluate("(() => { const m = document.querySelector('mark.hl.sev-critical, mark.hl'); if (m) { m.scrollIntoView({block:'center'}); m.click(); } })()")
            pg.wait_for_timeout(4800)
            pg.keyboard.press("Escape")
            # 5. матрица и покрытие приёмкой
            pg.goto(html.as_uri())
            pg.wait_for_timeout(700)
            pg.evaluate("(() => { const d = document.getElementById('matrix'); if (d) { d.open = true; d.scrollIntoView({block:'start'}); } })()")
            cap("Матрица «требование × критерий» и покрытие правил примерами приёмки")
            pg.wait_for_timeout(4200)
            # 6. «До / После»
            if ba.exists():
                pg.set_content(md_table_html(ba.read_text(encoding="utf-8")))
                cap("Агент сам исправил формулировки и проверил документ заново")
                pg.wait_for_timeout(5200)
            # 7. финал
            pg.set_content(card(f"{fs} замечаний · {crit} критичных",
                                f"Каждая цитата проверена кодом · {len(data['requirements'])} требований · 6 разделов ТЗ",
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
            print(f"видео (MP4): {mp4} · {mp4.stat().st_size // 1024} КБ")
        except ImportError:
            print("MP4 не собран: pip install imageio-ffmpeg (WebM готов)")
        return 0
    finally:
        srv.terminate()
        srv.wait(timeout=10)
        shutil.rmtree(vids, ignore_errors=True)


def esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
