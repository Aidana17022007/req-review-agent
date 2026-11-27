"""v9, интерфейс (mock, без сети): ответы аналитика и решения в HTML-отчёте, Studio (пример, лимит, ответы,
«сломанные» файлы, қазақша), сайт («Оценить без установки», «Слепые документы» — только реальные цифры)."""
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "tests" / "fixtures" / "sample_requirements.md"


def _data(html: str) -> dict:
    return json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S)[1].replace("<\\/", "</"))


@pytest.fixture(scope="module")
def reports(tmp_path_factory):
    """Mock-прогон без ответов и с ответами (конкретный, уклончивый, противоречивый) — настоящие поля 2.4 в HTML."""
    from req_review.pipeline import Options, run

    saved = {k: os.environ.get(k) for k in ("LLM_PROVIDER", "LLM_MIN_INTERVAL")}
    os.environ.update(LLM_PROVIDER="mock", LLM_MIN_INTERVAL="0")
    d = tmp_path_factory.mktemp("ui_v9")
    opts = dict(xlsx=False, jira=False, pdf=False)
    run(str(DOC), str(d / "r0" / "report.md"), Options(**opts), log=lambda m: None)
    (d / "answers.md").write_text("### Q-01\nПроверка получателя — не дольше 2 секунд для 95 % запросов.\n\n"
                                  "### Q-03\nУточним с командой безопасности после пилота.\n", encoding="utf-8")
    run(str(DOC), str(d / "r1" / "report.md"), Options(**opts, answers=str(d / "answers.md")), log=lambda m: None)
    yield {k: (d / k / "report.html").read_text(encoding="utf-8") for k in ("r0", "r1")}
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_html_report_carries_answers_and_decisions(reports):
    html = reports["r1"]
    assert len(html.encode("utf-8")) < 1_000_000
    d = _data(html)
    a = d["answers"]
    assert a and a["source"] == "answers.md" and {x["type"] for x in a["items"]} <= {"concrete", "evasive", "contradictory"}
    concrete = [x for x in a["items"] if x["type"] == "concrete"]
    assert concrete and all(x["quote"] in x["answer"] for x in concrete), "цитата — подстрока ответа"
    assert a["before"]["critical"] >= a["after"]["critical"]
    assert any(r.get("closed_by") for r in d["rejected"]), "закрытые ответами замечания — в rejected с closed_by"
    assert d["decisions"] and all(x["title"] and x["options"] for x in d["decisions"])
    assert d["passport"]["log"] == "report.log"
    for marker in ("answersHTML", "decisionsHTML", "Ответы аналитика", "Решения для владельца продукта", "закрыто ответом",
                   "сформулировано кодом", "Каскад моделей", "Журнал прогона", "Что закрыли ответы?", "Какие вопросы аналитику?",
                   "Аналитик жауаптары", "Өнім иесіне арналған шешімдер"):
        assert marker in html, marker


def test_report_without_answers_hides_block(reports):
    d = _data(reports["r0"])
    assert d["answers"] is None, "без --answers блок «Ответы аналитика» скрыт"
    # старый отчёт (схема 2.3, без полей v9) — build_data не падает, блоки пустые
    from req_review.html_report import _answers, _decisions

    assert _answers(None) is None and _answers({"items": []}) is None and _decisions(None) == []
    assert _decisions([{"title": ""}, {"title": "T", "where": [{"rid": "R-001", "line": "x"}]}])[0]["where"][0]["line"] is None


def test_dawn_blockers_and_tour(reports):
    """v9+: «Рассвет готовности», «блокеры гаснут» и тур по отчёту — в HTML; движение только без reduced-motion."""
    from req_review.ui import asset

    html = reports["r1"]
    for marker in ("dawnHTML", "Рассвет готовности", "blockersHTML", "Закрыто блокеров:", "const TOUR", "REQLENS_TOUR",
                   "Тур за 60 секунд", "tour=1", "Дайындық таңы", "60 секундтық тур"):
        assert marker in html, marker
    css = asset("base.css")
    motion = re.findall(r"@media \(prefers-reduced-motion:no-preference\)\{(.*?)\n\}", css, re.S)
    assert any("dawn-rise" in m for m in motion) and any("bk-off" in m for m in motion), "анимация — только без reduced-motion"
    assert ".tour-ring{position:fixed;z-index:var(--z-modal)" in css and "@media print{.tour-ring,.tour-card{display:none" in css
    studio = Path("req_review/ui/templates/studio.html.j2").read_text(encoding="utf-8")
    assert 'id="r-tour"' in studio and "REQLENS_TOUR" in studio and "bkHTML(B,A)" in studio


def test_report_ui_hides_v9_blocks_and_sibling_links_safely():
    from req_review.ui import asset

    js = asset("report.js")
    assert "if (!ANS) return" in js and "if (!DEC.length) return" in js
    # в готовом примере Studio (/api/v1/example/files/…) соседних файлов нет — ссылок на них тоже
    assert "IN_EXAMPLE" in js and "/api\\/v1\\/example\\//" in js
    kk = asset("report-i18n.js")
    for w in ("Ответы аналитика", "Решения для владельца продукта", "Где расходится", "Варианты", "Журнал прогона", "Каскад моделей"):
        assert f'"{w}"' in kk, w


def test_studio_v9_screens(tmp_path, monkeypatch):
    monkeypatch.setenv("REQLENS_DATA", str(tmp_path))
    from fastapi.testclient import TestClient

    from req_review.web.app import app

    html = TestClient(app).get("/").text
    for marker in ('id="example"', "openExample", 'api("/example")', "example=1",  # готовый пример
                   'id="privacy"', "не загружайте конфиденциальное", "Ollama",  # предупреждение перед загрузкой
                   "limit:[", "retry_after", "Retry-After", "err-example",  # экран 429
                   "document:[", "Файл не читается", "Что сделать",  # «сломанные» файлы
                   'id="s-answers"', 'id="ans-card"', "/runs/${run.id}/answers", "unknown_qids", "localStorage.setItem(draftKey()",
                   "Скачать шаблон ответов", "Перепроверить", "Ответы аналитика: было → стало",  # ответы аналитика
                   'id="btn-lang"', '"Ответить на вопросы":"Сұрақтарға жауап беру"', '"Файл не читается":"Файл оқылмайды"'):  # қазақша
        assert marker in html, marker


def test_blind_results_only_real_numbers(tmp_path):
    from req_review.ui.styleguide import blind_results

    p = tmp_path / "RESULTS.md"
    assert blind_results(tmp_path / "нет.md") is None
    p.write_text("# Бенчмарк\n\n| Recall | **97 %** |\n", encoding="utf-8")
    assert blind_results(p) is None, "нет раздела — ничего не показываем"
    sec = ("## Слепые документы (bench/blind_eval.py)\n\n*Дата:* 2026-11-27 · *модель:* {m} · *агент:* v9.0.0.\n\n"
           "| Документ | Найдено | Критичных | Замечаний агента | Не найдено |\n|---|---|---|---|---|\n"
           "| Кэшбэк | 5 из 6 (83 %) | 2 из 2 | 14 | D-3 |\n")
    p.write_text(sec.format(m="mock / mock-heuristic"), encoding="utf-8")
    assert blind_results(p) is None, "mock-цифры не показываются"
    p.write_text(sec.format(m="gemini / gemini-3.8-flash") + "\n## Другое\n| x | y |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    b = blind_results(p)
    assert b["head"][0] == "Документ" and b["rows"] == [["Кэшбэк", "5 из 6 (83 %)", "2 из 2", "14", "D-3"]]


def test_site_try_button_and_no_dead_links(monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_site

    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert "<!-- blind -->" in html and 'data-i18n="cta.try"' in html
    no = build_site.apply_links(html, "", False)
    yes = build_site.apply_links(html, "https://studio.example", False)
    assert re.search(r'href="report/"><span data-i18n="cta.try"', no) and "data-studio-note" not in no
    assert re.search(r'href="https://studio.example"><span data-i18n="cta.try"', yes) and "data-nostudio" not in yes
    assert "data-studio-note hidden" not in yes
    monkeypatch.setattr("req_review.ui.styleguide.blind_results", lambda *a, **k: None)
    assert build_site.blind_html() == ""
    kk = (ROOT / "site" / "site.js").read_text(encoding="utf-8")
    assert '"cta.try"' in kk and '"blind.t"' in kk


def test_site_report_drops_log_link_when_log_missing(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_site

    rep = '<script id="data">{"passport": {"log": "nope-report.log"}}</script>'
    assert '"log": ""' in build_site.report_siblings(rep, tmp_path), "нет файла журнала — нет ссылки (не 404)"
