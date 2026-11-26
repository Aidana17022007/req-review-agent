"""Скриншоты и GIF для README и слайдов (опционально, нужен Playwright; GIF — Pillow).

    pip install playwright pillow && playwright install chromium
    python scripts/screenshots.py [путь к report.html] [--no-studio]   →  docs/assets/

Что снимается:
  • все разделы HTML-отчёта (светлая и тёмная темы, 1440×900), включая 3D-граф (WebGL через SwiftShader) и 2D-вид;
  • мобильный вид документа (375×800);
  • ReqLens Studio: загрузка, живой прогон, отчёт с AI-ассистентом, «До / После» и GIF живого прогона.
Без аргумента делает mock-прогон на тестовом примере (ключ модели не нужен).
"""
from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "assets"
FIX = ROOT / "tests" / "fixtures" / "sample_requirements.md"
# WebGL в headless Chromium — программный рендер SwiftShader
GL_ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
# сообщения драйвера SwiftShader (есть и на пустой WebGL-странице) — не ошибки отчёта
GL_NOISE = ("GL Driver Message", "glBlitFramebuffer", "GPU stall due to ReadPixels")

REPORT_SHOTS = [("overview", "", True), ("requirements", "#reqs", False), ("doc", "#doc", False), ("graph", "#graph", False),
                ("set", "#set", False), ("tests", "#tests", False), ("fixes", "#fixes", False), ("trace", "#trace", False),
                ("export", "#export", False)]


def mock_env() -> dict:
    return {**os.environ, "LLM_PROVIDER": "mock", "LLM_MIN_INTERVAL": "0", "PYTHONIOENCODING": "utf-8"}


def console_guard(page, errors: list, where: str):
    page.on("console", lambda m: errors.append(f"{where}: {m.text}")
            if m.type == "error" and not any(n in m.text for n in GL_NOISE) else None)
    page.on("pageerror", lambda e: errors.append(f"{where}: {e}"))


def shoot_report(b, html: Path, errors: list):
    for theme in ("light", "dark"):
        page = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1, reduced_motion="reduce")
        console_guard(page, errors, f"report/{theme}")
        page.add_init_script(f"try{{localStorage.setItem('reqlens-theme','{theme}')}}catch(e){{}}")
        for name, hash_, full in REPORT_SHOTS:
            page.goto(html.resolve().as_uri() + hash_)
            page.wait_for_timeout(4500 if name == "graph" else 900)
            if name == "graph":  # выбрать узел с противоречием — видна цепочка конфликта и боковая панель
                page.evaluate("(() => { const b = document.querySelector('#view-graph .tbl [data-gsel]') || document.querySelector('#g-side [data-gsel]'); if (b) b.click(); })()")
                page.wait_for_timeout(1800)
            if name == "doc":  # карточка у первого дефекта
                page.keyboard.press("j")
                page.wait_for_timeout(600)
            page.screenshot(path=str(OUT / f"screenshot-{name}-{theme}.png"), full_page=full)
        if theme == "light":
            page.goto(html.resolve().as_uri() + "#graph")
            page.wait_for_timeout(1500)
            page.click("[data-gmode='2d']")
            page.wait_for_timeout(800)
            page.screenshot(path=str(OUT / "screenshot-graph2d-light.png"))
        page.close()
    page = b.new_page(viewport={"width": 375, "height": 800}, device_scale_factor=2, reduced_motion="reduce")
    console_guard(page, errors, "report/375")
    for name, hash_ in (("doc", "#doc"), ("overview", "")):
        page.goto(html.resolve().as_uri() + hash_)
        page.wait_for_timeout(900)
        page.screenshot(path=str(OUT / f"screenshot-mobile-{name}.png"))
    page.close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def shoot_studio(b, errors: list):
    port = free_port()
    env = {**mock_env(), "STUDIO_DEMO_DELAY": "0.9", "STUDIO_PORT": str(port)}
    srv = subprocess.Popen([sys.executable, "-c", f"import uvicorn; from req_review.web.app import app; uvicorn.run(app, host='127.0.0.1', port={port}, log_level='warning')"],
                           cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}/"
    try:
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        page = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        console_guard(page, errors, "studio")
        page.goto(url)
        page.wait_for_timeout(600)
        page.screenshot(path=str(OUT / "screenshot-studio-upload.png"))
        # живой прогон: файл «перетаскивают» в зону загрузки; кадры для GIF снимаем по ходу
        frames = []
        page.set_input_files("#file", str(FIX))
        page.evaluate("""() => { const dt = new DataTransfer(); dt.items.add(document.getElementById('file').files[0]);
            document.getElementById('drop').dispatchEvent(new DragEvent('dragenter', {dataTransfer: dt, bubbles: true})); }""")
        frames += [page.screenshot()] * 3
        page.evaluate("""() => { const dt = new DataTransfer(); dt.items.add(document.getElementById('file').files[0]);
            document.getElementById('drop').dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true})); }""")
        t0 = time.time()
        shot_live = False
        while time.time() - t0 < 60:
            png = page.screenshot()
            frames.append(png)
            done = page.evaluate("document.getElementById('s-result').classList.contains('active')")
            rows = page.evaluate("document.querySelectorAll('#lv-body tr:not(.sk)').length")
            if not shot_live and rows >= 8:
                page.screenshot(path=str(OUT / "screenshot-studio-live.png"))
                shot_live = True
            if done:
                break
            page.wait_for_timeout(180)
        make_gif(frames, OUT / "live-run.gif")
        page.wait_for_timeout(2500)
        # ассистент: подсказка «Почему … критичное?»
        page.click("#chat-sugg button")
        page.wait_for_timeout(1200)
        page.click("#chat-sugg button:nth-child(2)")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / "screenshot-studio-assistant.png"))
        # До / После: проверить исправленную агентом версию
        page.click("#cmp-fixed")
        page.wait_for_selector("#s-compare.active", timeout=90000)
        page.wait_for_timeout(1600)
        page.screenshot(path=str(OUT / "screenshot-studio-compare.png"))
        page.close()
    finally:
        srv.terminate()
        srv.wait(timeout=10)


def make_gif(frames: list[bytes], path: Path, width: int = 960):
    try:
        from PIL import Image
    except ImportError:
        print("Pillow не установлен — GIF пропущен")
        return
    if not frames:
        return
    step = max(1, len(frames) // 40)  # не больше ~40 кадров
    imgs = []
    for png in frames[::step] + [frames[-1]] * 3:
        im = Image.open(io.BytesIO(png)).convert("RGB")
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        imgs.append(im.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=[260] * (len(imgs) - 1) + [2200], loop=0, optimize=True)
    print(f"GIF: {path} ({len(imgs)} кадров, {path.stat().st_size // 1024} КБ)")


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("Нужен Playwright: pip install playwright && playwright install chromium")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    html = Path(args[0]) if args else ROOT / "reports" / "mock.html"
    if not args:
        subprocess.run([sys.executable, str(ROOT / "review.py"), str(FIX), str(ROOT / "reports/mock.md"), "--profile", "full", "--quiet"],
                       check=True, env=mock_env())
    OUT.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=GL_ARGS)
        shoot_report(b, html, errors)
        b.close()
        if "--no-studio" not in sys.argv:
            b = p.chromium.launch()  # Studio без WebGL: отдельный браузер без SwiftShader
            shoot_studio(b, errors)
            b.close()
    if errors:
        print("Ошибки в консоли браузера:\n  " + "\n  ".join(errors))
        sys.exit(1)
    print(f"Готово: {OUT} (ошибок в консоли нет)")


if __name__ == "__main__":
    main()
