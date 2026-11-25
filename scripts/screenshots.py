"""Скриншоты HTML-отчёта для README и слайдов (опционально, нужен Playwright).

    pip install playwright && playwright install chromium
    python scripts/screenshots.py [путь к report.html]   →  docs/assets/screenshot-*.png

Без аргумента делает mock-прогон на тестовом примере.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "assets"


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("Нужен Playwright: pip install playwright && playwright install chromium")
    html = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "reports" / "mock.html"
    if len(sys.argv) == 1:
        env = {**os.environ, "LLM_PROVIDER": "mock", "LLM_MIN_INTERVAL": "0"}
        subprocess.run([sys.executable, str(ROOT / "review.py"), str(ROOT / "tests/fixtures/sample_requirements.md"),
                        str(ROOT / "reports/mock.md"), "--profile", "full", "--quiet"], check=True, env=env)
    OUT.mkdir(parents=True, exist_ok=True)
    shots = [("hero", "", None), ("document", "#doc", "#tabs"), ("requirements", "#reqs", "#tabs"),
             ("fixed", "#fixed", "#tabs"), ("graph", "#graph", "#tabs")]
    with sync_playwright() as p:
        b = p.chromium.launch()
        for theme in ("light", "dark"):
            page = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2, color_scheme=theme)
            for name, hash_, anchor in shots:
                page.goto(html.resolve().as_uri() + hash_)
                page.wait_for_timeout(1300)
                if anchor:
                    page.locator(anchor).scroll_into_view_if_needed()
                    page.evaluate("window.scrollBy(0, -70)")
                    page.wait_for_timeout(400)
                page.screenshot(path=str(OUT / f"screenshot-{name}-{theme}.png"))
            page.close()
        b.close()
    print(f"Готово: {OUT}")


if __name__ == "__main__":
    main()
