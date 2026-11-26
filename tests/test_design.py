"""Дизайн-система v2: токены — один источник правды, контраст AA, единые иконки, логотип и иконки PWA, витрина."""
import re
from pathlib import Path

import pytest

from req_review.ui import UI_DIR, load_tokens, tokens_css
from req_review.ui.a11y import AA_TEXT, contrast, contrast_table, rgb

ROOT = Path(__file__).resolve().parent.parent
T = load_tokens()


def test_tokens_css_is_generated_from_tokens_json():
    """tokens.css не правят руками: он совпадает с генерацией из design/tokens.json (иначе — python -m req_review.ui.styleguide)."""
    on_disk = (UI_DIR / "tokens.css").read_text(encoding="utf-8")
    assert on_disk.split("\n", 1)[1] == tokens_css(), "tokens.css устарел — пересоберите: python -m req_review.ui.styleguide"


def test_all_text_pairs_pass_wcag_aa_in_both_themes():
    rows = contrast_table(T)
    assert {r["theme"] for r in rows} == {"light", "dark"} and len(rows) > 30
    bad = [f'{r["theme"]}: --{r["fg"]} на --{r["bg"]} = {r["ratio"]}' for r in rows if not r["ok"]]
    assert not bad, "ниже AA (4.5): " + "; ".join(bad)


def test_semantic_tokens_are_complete_in_both_themes():
    light, dark = T["color"]["light"], T["color"]["dark"]
    assert light.keys() == dark.keys()
    for sev in ("critical", "major", "minor", "ok", "info"):
        assert {sev, f"{sev}-accent", f"{sev}-soft"} <= light.keys()
    # белый текст на кнопке «Удалить» и тосте ошибки — AA в обеих темах
    for c in (light, dark):
        assert contrast(rgb(c["on-danger"]), rgb(c["danger"])) >= AA_TEXT


def test_scales_motion_and_layers():
    for name in ("green", "gray"):
        assert list(T["palette"][name]) == ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"]
        lum = [sum(rgb(v)) for v in T["palette"][name].values()]
        assert lum == sorted(lum, reverse=True), f"шкала {name} должна темнеть от 50 к 950"
    assert [int(v.split("px")[0]) for v in T["scale"].values()] == [12, 14, 16, 20, 24, 32, 48]
    assert [v for v in T["space"].values()] == ["4px", "8px", "12px", "16px", "24px", "32px", "48px", "64px"]
    assert len(T["shadow"]) >= 2
    assert int(T["motion"]["base"].rstrip("ms")) <= 200, "микроанимации — не дольше 200 мс"
    z = T["z"]
    assert z["overlay"] < z["drawer"] < z["popover"] < z["modal"] < z["tooltip"] < z["toast"]
    css = tokens_css()
    for var in ("--green-700:", "--gray-500:", "--fs-md: 16px", "--lh-3xl: 56px", "--z-modal:", "--info:", "--danger:", "--r-full:"):
        assert var in css, var


def test_base_css_uses_layer_tokens_not_magic_numbers():
    css = (UI_DIR / "assets" / "base.css").read_text(encoding="utf-8")
    big = [m for m in re.findall(r"z-index:\s*(\d+)", css) if int(m) > 9]
    assert not big, f"z-index выше 9 — только через var(--z-*): {big}"
    for cls in (".btn-danger", ".btn-lg", ".field", ".dropzone", ".sev-info", ".modal", ".modal-box", ".toast-err",
                ".stages", ".skel-card", ".seg-sm"):
        assert cls + "{" in css or cls + " " in css or cls + "," in css, cls


def test_icons_are_one_set_with_one_stroke_width():
    from req_review.ui.icons import ICONS, STROKE, icon

    assert len(ICONS) >= 50
    for name in ICONS:
        svg = str(icon(name))
        assert 'viewBox="0 0 24 24"' in svg and f'stroke-width="{STROKE}"' in svg and 'fill="none"' in svg, name
        assert "stroke-width" not in ICONS[name], f"{name}: своя толщина линии"
    # JS-копии иконок в отчёте и Studio рисуют с той же толщиной
    for f in (UI_DIR / "assets" / "report.js", UI_DIR / "templates" / "studio.html.j2"):
        assert f'stroke-width="{STROKE}"' in f.read_text(encoding="utf-8"), f.name


def test_logo_and_favicon_are_inline_and_offline():
    from req_review.ui.brand import favicon_href, logo_mark, logo_svg, mark_svg

    assert favicon_href().startswith("data:image/svg+xml,") and "#" not in favicon_href()
    a, b = str(logo_mark(36)), str(logo_mark(36))
    assert re.search(r'id="(rl\d+)"', a)[1] != re.search(r'id="(rl\d+)"', b)[1], "id градиента уникален на странице"
    for theme in ("light", "dark"):
        assert "ReqLens" in logo_svg(theme) and "http" not in logo_svg(theme).replace("http://www.w3.org/2000/svg", "")
    assert mark_svg(48).count("<svg") == 1


def test_brand_files_for_pwa():
    import json

    d = ROOT / "design" / "brand"
    meta = json.loads((d / "brand.json").read_text(encoding="utf-8"))
    assert meta["theme_color"] == T["brand"]["theme_color"] and {i["purpose"] for i in meta["icons"]} == {"any", "maskable"}
    for f in ("reqlens-mark.svg", "reqlens-logo-light.svg", "reqlens-logo-dark.svg", "favicon.svg"):
        assert (d / f).read_text(encoding="utf-8").startswith("<svg")
    PIL = pytest.importorskip("PIL.Image")
    for name, size in (("icon-192.png", 192), ("icon-512.png", 512), ("icon-maskable-512.png", 512), ("favicon-32.png", 32)):
        p = d / name
        assert p.stat().st_size < 200_000
        assert PIL.open(p).size == (size, size), name
    # maskable: фон до самых краёв (система сама вырезает форму)
    im = PIL.open(d / "icon-maskable-512.png").convert("RGBA")
    assert all(im.getpixel(xy)[3] == 255 for xy in ((0, 0), (511, 0), (0, 511), (511, 511)))


def test_styleguide_shows_every_token_group_and_component(tmp_path):
    from req_review.ui.icons import ICONS
    from req_review.ui.styleguide import build

    html = build(tmp_path / "sg.html").read_text(encoding="utf-8")
    for anchor in ('id="brand"', 'id="color"', 'id="contrast"', 'id="type"', 'id="layout"', 'id="components"', 'id="icons"'):
        assert anchor in html, anchor
    assert html.count('data-theme="dark"') >= 3 and "пар «текст / фон» проходят AA" in html
    for cls in ("btn-danger", "btn-lg", "loading", "field invalid", "dropzone", "sev-info", "tbl", "tabs", "drawer is-static",
                "modal-box", "toast-err", "empty", "skel-card", "stages", "data-tip", "seg seg-sm"):
        assert cls in html, cls
    assert all(f"<span>{n}</span>" in html for n in ICONS)
