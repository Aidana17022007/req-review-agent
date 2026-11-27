"""v13, сайт и Studio (без сети): «Проверьте одну фразу» (правила агента в браузере), страница «Доказательства» из
bench/*.json (нет файла — нет блока), PDF отчёта без 404, ожидание пробуждения Studio, подробности прогона в Studio."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def test_js_regex_handles_cyrillic_word_boundaries():
    import build_site

    w = r"[\p{L}\p{N}_]"
    assert build_site.js_regex(r"\w+") == w + "+"
    assert build_site.js_regex(r"[\w-]") == r"[\p{L}\p{N}_-]", "\\w внутри класса — без вложенных скобок"
    assert build_site.js_regex(r"(?<![\w])") == r"(?<![\p{L}\p{N}_])"
    assert r"\b" not in build_site.js_regex(r"\bбыстр\w*\b") and "(?<=" in build_site.js_regex(r"\bx")
    assert build_site.js_regex(r"\d\s\.") == r"\d\s\."


def test_site_widget_embeds_all_agent_rules():
    import build_site

    from req_review import rules

    p = build_site.rules_payload()
    assert len(p["rules"]) == len(rules.RULES) and all(r["problem"] and r["fix"] and r["name"] for r in p["rules"])
    assert {r["sev"] for r in p["rules"]} <= {"critical", "major", "minor"} and p["and"] and p["sent"] and p["id"]
    sec = build_site.try_html()
    assert sec.startswith('<section class="panel try" id="try" hidden>'), "без JS секция скрыта"
    data = json.loads(re.search(r'<script type="application/json" id="rl-rules">(.*?)</script>', sec, re.S)[1].replace("<\\/", "</"))
    assert data["rules"][0]["p"] == p["rules"][0]["p"]
    assert "<!-- try -->" in (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "site" / "site.js").read_text(encoding="utf-8")
    assert "REQLENS_TRY" in js and '"try.t"' in js and 'new RegExp(r.p, "giu")' in js


def test_proof_page_only_from_files(monkeypatch, tmp_path):
    import build_site

    html = build_site.proof_html()
    assert "Бенчмарк: документы с известными дефектами" in html and "python bench/run.py" in html
    assert "ReqLens против одного промпта в ту же модель" in html and "python bench/baseline_eval.py" in html
    res = json.loads((ROOT / "bench" / "results.json").read_text(encoding="utf-8"))
    assert f"{res['tp']} из {res['total']} дефектов" in html, "цифры — из bench/results.json"
    assert "bench/score.json" not in html or (ROOT / "bench" / "score.json").exists(), "нет файла — нет блока"
    monkeypatch.setattr(build_site, "ROOT", tmp_path)  # пустой репозиторий: ни одного файла — страницы нет
    assert build_site.proof_html() == ""


def test_site_has_no_dead_pdf_or_proof_links(tmp_path):
    import build_site

    out = tmp_path / "public"
    build_site.build(out, "")
    html = (out / "index.html").read_text(encoding="utf-8")
    has_pdf = (out / "report" / "report.pdf").exists()
    assert ('href="report/report.pdf"' in html) == has_pdf, "ссылка на PDF — только если PDF собран"
    assert ('href="proof/"' in html) == (out / "proof" / "index.html").exists()
    for u in re.findall(r'href="((?:report|proof|tz|slides)/[^"#]*)"', html):
        t = out / u
        assert (t / "index.html" if u.endswith("/") else t).exists(), u
    js = (ROOT / "site" / "site.js").read_text(encoding="utf-8")
    assert "Studio просыпается, ~30 с" in js and "/api/health" in js and 'id="wake"' in (ROOT / "site" / "index.html").read_text(encoding="utf-8")


def test_studio_health_has_cors_for_site(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from req_review.web.app import app

    monkeypatch.setenv("REQLENS_DATA", str(tmp_path))
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200 and r.headers.get("access-control-allow-origin") == "*"


def test_studio_details_card_reads_v12_fields():
    html = (ROOT / "req_review" / "ui" / "templates" / "studio.html.j2").read_text(encoding="utf-8")
    for marker in ('id="det-card"', "p.stages", "critical_path", "traceability", "rule_without_acceptance", "sm.blockers_closed",
                   "rv.changed", "p.strong", "renderDetails(d)"):
        assert marker in html, marker
    wf = (ROOT / ".github" / "workflows" / "studio-health.yml").read_text(encoding="utf-8")
    assert 'cron: "17 * * * *"' in wf and "/api/health" in wf and "vars.STUDIO_URL" in wf
    rd = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    assert rd[0].startswith("**▶ Оценить без установки:**") and rd[1].startswith("**⏱ Проверить за 2 минуты:**")
