"""v15, интерфейс (без сети): всё, что движок уже посчитал, видно в HTML-отчёте и Studio — «Кратко», «Исправленное ТЗ»,
трассировка «требование ↔ API», «Чек-лист банка», паспорт 2.5; блок скрыт, если поля нет. Цифры «Доказательств» — только
из файлов репозитория. Mock-прогон на tests/fixtures/sample_requirements.md (ключ модели не нужен)."""
import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "tests" / "fixtures" / "sample_requirements.md"


def _data(html: str) -> dict:
    return json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S)[1].replace("<\\/", "</"))


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """Без ответов и правил банка — и с ними (--answers, --rules fintech): настоящие поля 2.5 в data.engine."""
    from req_review.pipeline import Options, run

    saved = {k: os.environ.get(k) for k in ("LLM_PROVIDER", "LLM_MIN_INTERVAL")}
    os.environ.update(LLM_PROVIDER="mock", LLM_MIN_INTERVAL="0")
    d = tmp_path_factory.mktemp("ui_v15")
    opts = dict(xlsx=False, jira=False, pdf=False)
    run(str(DOC), str(d / "r0" / "report.md"), Options(**opts), log=lambda m: None)
    (d / "answers.md").write_text("### Q-01\nПроверка получателя — не дольше 2 секунд для 95 % запросов.\n\n"
                                  "### Q-03\nУточним с командой безопасности после пилота.\n", encoding="utf-8")
    run(str(DOC), str(d / "r1" / "report.md"), Options(**opts, answers=str(d / "answers.md"), rules="fintech"), log=lambda m: None)
    yield {k: ((d / k / "report.html").read_text(encoding="utf-8"), json.loads((d / k / "report.json").read_text(encoding="utf-8")))
           for k in ("r0", "r1")}
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_engine_fields_reach_html_and_blocks_render(runs):
    html, rep = runs["r1"]
    assert len(html.encode("utf-8")) < 1_000_000
    e = _data(html)["engine"]
    assert e.get("revised") and e["revised"].get("summary", {}).get("blockers_total") is not None
    assert "trace_gaps" in e and rep.get("traceability") and rep.get("bank_rules")
    for marker in ("function briefHTML", "function renderRevised", "function traceGapsHTML", "function renderBank",
                   "function passportV15", "function enrichFromJSON", "Исправленное ТЗ", "Чек-лист банка", "Требование ↔ API",
                   "Экономия времени (оценка)", "Устраняет:", "Осталось уточнить", "сработало", "выполнено", "не применимо"):
        assert marker in html, marker


def test_blocks_hidden_without_fields(runs):
    html, _ = runs["r0"]
    e = _data(html)["engine"]
    assert "revised" not in e, "без --answers нет «Исправленного ТЗ» и «Кратко»"
    from req_review.ui import asset

    js = asset("report.js")
    # условия показа: нет поля — нет пункта меню / блока
    assert "...(REV ? [{ id: \"revised\"" in js and "...(HAS_BANK ? [{ id: \"bank\"" in js
    assert 'if (!ANS) return ""' in js.split("function briefHTML")[1][:120]
    assert "...(TG ? [[\"api\"" in js
    # полный report.json дочитывается только по http(s) и только для того же прогона
    enr = js.split("function enrichFromJSON")[1][:900]
    assert "https?:" in enr and "fp.sha256 !== P.sha256" in enr and "fp.started !== P.started" in enr


def test_fixture_reports_render_without_v15_fields():
    """Старые фикстуры (2.2, 2.4) — без engine: build_data их не читает, а JS не должен падать на пустом engine."""
    from req_review.ui import asset

    js = asset("report.js")
    assert "const E = D.engine || {};" in js
    for f in ("report_v9.json", "report_v22.json"):
        d = json.loads((ROOT / "tests" / "fixtures" / f).read_text(encoding="utf-8"))
        assert "traceability" not in d and "bank_rules" not in d  # блоки v15 для них скрыты


def test_kk_dictionary_covers_new_labels():
    from req_review.ui import asset

    kk = asset("report-i18n.js")
    for w in ("Исправленное ТЗ", "Чек-лист банка", "Требование ↔ API", "Кратко", "Закрыто блокеров", "Открытых замечаний",
              "Было → Стало", "Устраняет:", "Новые требования", "Осталось уточнить", "Правила банка", "Комплаенс и безопасность",
              "Чек-лист документа", "Экономия времени (оценка)", "Стоимость прогона", "Поле экрана", "Параметр API", "HTTP-код",
              "сработало", "выполнено", "не применимо", "операция без метода API", "HTTP-статус без описания"):
        assert f'"{w}"' in kk, w
    assert r"[/^(\d+) из (\d+)$/" in kk and ".q-in" in kk.split("const SKIP")[1][:80]


def test_studio_start_screen_projects_warning_and_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("REQLENS_DATA", str(tmp_path))
    from fastapi.testclient import TestClient

    from req_review.web.app import app

    html = TestClient(app).get("/").text
    for marker in ('id="start-hero"', 'id="example"', 'id="hero-upload"', "Загрузить своё ТЗ", 'id="pj-ephemeral"',
                   "история проверок очищается при обновлении", "st===413", "st===429", "function briefBlock", "data-open-view",
                   '"Загрузить своё ТЗ":"Өз ТТ-ны жүктеу"', '"Кратко":"Қысқаша"'):
        assert marker in html, marker
    upload = html.split('id="s-upload"')[1].split('id="s-projects"')[0]
    assert upload.count("btn-primary") == 1, "одна белая кнопка на экран — «Открыть готовый пример»"


def test_headline_numbers_only_from_files(tmp_path):
    from req_review.ui.proof import PENDING, evidence, headline

    rows = evidence(tmp_path)  # пустой репозиторий: ни одного числа, только «появится после прогона»
    assert rows and all(r["value"] is None and r["detail"] == "" for r in rows) and PENDING
    assert headline(tmp_path) == []
    g = json.loads((ROOT / "bench" / "score.json").read_text(encoding="utf-8"))
    real = {r["id"]: r for r in evidence()}
    assert real["gold_recall"]["value"].startswith(f"{int(100 * g['recall'] + 0.5)} %")
    if g.get("unjudged"):  # пока проверены не все замечания — диапазон, а не лучшая цифра
        assert real["gold_precision"]["value"].startswith("от ")


def test_site_evidence_section_numbers_from_files(monkeypatch, tmp_path):
    """Сайт, раздел «Доказательства»: строки — из proof.evidence, у каждой подписи есть казахский перевод;
    нет числа — «появится после прогона», а не выдуманное значение."""
    import importlib.util
    from html import escape

    from req_review.ui import proof

    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    bs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bs)
    sec, kk = bs.evidence_html()
    rows = proof.evidence(ROOT)
    assert sec.count("<tr data-ev=") == len(rows)
    for r in rows:
        assert f'data-i18n="ev.{r["id"]}.t"' in sec and kk[f"ev.{r['id']}.t"]
        if r["value"]:
            assert escape(r["value"]) in sec
    keys = set(re.findall(r'data-i18n="([\w.-]+)"', sec))
    assert keys <= set(kk), keys - set(kk)
    assert not any(re.search(r"\bиз\b|проверено|критичных", v) for v in kk.values())  # казахский без русских связок

    real = proof.evidence
    monkeypatch.setattr(proof, "evidence", lambda root=None: real(tmp_path))  # пустой репозиторий
    sec, kk = bs.evidence_html()
    assert proof.PENDING in sec and "data-pending" in sec and "%" not in re.sub(r"<p class=\"note\".*", "", sec, flags=re.S)
