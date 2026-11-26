"""Тесты агента. Запуск: pytest -q (ключ LLM не нужен — используется mock)."""
from pathlib import Path

import pytest

from req_review.cli import main
from req_review.reader import read_document
from req_review.rules import check_requirement
from req_review.splitter import split_requirements
from req_review.verify import quote_in

FIX = Path(__file__).parent / "fixtures" / "sample_requirements.md"


def test_split_by_ids_keeps_doc_ids_and_tables():
    s = split_requirements(read_document(FIX))
    ids = [r.doc_id for r in s.requirements]
    assert s.method == "ids"
    assert ids[:3] == ["FR-01", "FR-02", "FR-03"]
    assert "NFR-01" in ids and "SEC-03" in ids  # строки Markdown-таблицы тоже нарезаются
    nfr = next(r for r in s.requirements if r.doc_id == "NFR-01")
    assert nfr.extra.get("Приоритет") == "Высокий"
    assert nfr.section.startswith("4.")
    # утверждения с «должен/должна» без ID попадают в список для проверки трассируемости
    texts = [t for _, t in s.unnumbered]
    assert any("регулятора" in t for t in texts)
    assert any("нового устройства" in t for t in texts)


def test_split_without_ids_assigns_own_numbers(tmp_path):
    p = tmp_path / "noids.txt"
    p.write_text("Требования\n\nСистема должна хранить логи 90 дней.\n\nПользователь может выгрузить отчёт.\n"
                 "Это просто пояснение.\n", encoding="utf-8")
    s = split_requirements(read_document(p))
    assert s.method == "modal"
    assert [r.rid for r in s.requirements] == ["R-001", "R-002"]
    assert all(r.doc_id is None for r in s.requirements)


def test_rules_catch_vague_words_and_skip_numeric():
    s = split_requirements(read_document(FIX))
    by = {r.doc_id: r for r in s.requirements}
    crit = lambda did: {h.criterion for h in check_requirement(by[did])}
    assert "verifiable" in crit("FR-02")          # «быстро»
    assert "complete" in crit("FR-06")            # «и т.д.»
    assert "complete" in crit("NFR-03")           # TBD
    assert "unambiguous" not in crit("FR-03")     # «Максимальная сумма … 500 000» — количественно
    hits = [h for h in check_requirement(by["FR-09"]) if h.criterion == "verifiable"]
    assert len(hits) == 1 and len(hits[0].terms) >= 2  # маркеры одного правила объединены


def test_quote_verification():
    text = "Система должна  быстро проверять наличие получателя «по номеру»."
    assert quote_in("быстро проверять наличие", text)
    assert quote_in('проверять наличие получателя "по номеру"', text)
    assert quote_in("Система должна … по номеру", text)
    assert not quote_in("медленно проверять", text)
    assert not quote_in("", text)


def _make_pdf(path: Path):
    pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not font.exists():
        pytest.skip("нет шрифта с кириллицей")
    pdfmetrics.registerFont(TTFont("DejaVu", str(font)))
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("DejaVu", 11)
    y = 800
    for line in FIX.read_text(encoding="utf-8").splitlines():
        if line.startswith("|"):
            continue
        c.drawString(40, y, line.replace("**", "")[:110])
        y -= 16
        if y < 60:
            c.showPage(); c.setFont("DejaVu", 11); y = 800
    c.save()


def test_pdf_reading_and_split(tmp_path):
    pdf = tmp_path / "req.pdf"
    _make_pdf(pdf)
    doc = read_document(pdf)
    assert doc.pages >= 1
    s = split_requirements(doc)
    ids = [r.doc_id for r in s.requirements]
    assert "FR-01" in ids and "SEC-02" in ids
    assert all(r.page for r in s.requirements)


def test_docx_reading(tmp_path):
    import docx

    d = docx.Document()
    d.add_heading("Требования", 1)
    d.add_paragraph("FR-1. Система должна выгружать отчёт быстро.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "ID", "Требование"
    t.cell(1, 0).text, t.cell(1, 1).text = "NFR-1", "Доступность не ниже 99,9 % в месяц."
    p = tmp_path / "req.docx"
    d.save(p)
    s = split_requirements(read_document(p))
    assert [r.doc_id for r in s.requirements] == ["FR-1", "NFR-1"]


def test_end_to_end_mock(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    out = tmp_path / "reports" / "report.md"
    assert main([str(FIX), str(out), "--env", str(tmp_path / "none.env")]) == 0
    rep = out.read_text(encoding="utf-8")
    for section in ("## 1. Паспорт прогона", "## 2. Нарезка требований", "## 3. Проверка каждого требования",
                    "## 4. Проверка набора требований", "## 5. Сводка", "## 6. Итог"):
        assert section in rep
    assert "| R-001 | FR-01 |" in rep
    assert "Версия агента" in rep and "Модель" in rep
    assert "этой фразы нет в документе" not in rep.split("Отброшенные замечания")[0]  # галлюцинация отброшена
    assert "Противоречие" in rep  # FR-03 vs FR-05 / SEC-01 vs SEC-02
    assert "нельзя" in rep.split("## 6. Итог")[1]


def test_mixed_document_units_without_ids(tmp_path):
    """Смешанный документ: Ф-1 с ID + НФТ, интеграция, критерии приёмки и параметры API без ID — всё нарезается."""
    p = tmp_path / "mixed.md"
    p.write_text(
        "# Задача\n\n## Ревью требований\n\n| Проверка | Да |\n| :--- | :--- |\n| Требование может быть протестировано | Да / Нет |\n\n"
        "### Функциональные требования\n* **Ф-1.** Клиент задаёт порог от 1 000 до 1 000 000 ₸.\n\n"
        "### Нефункциональные требования\nСервис передаёт push в течение минуты после события.\n\n"
        "### Критерии приемки\n\n| Условия | Действие | Результат |\n| :--- | :--- | :--- |\n| Порог 50 000 ₸ | Покупка 1 500 ₸ | Один push |\n\n"
        "### Общие параметры\n\n| Поле | Значение |\n| :--- | :--- |\n| **REST type** | GET |\n| **Author** | Школа |\n",
        encoding="utf-8")
    s = split_requirements(read_document(p))
    texts = [r.text for r in s.requirements]
    assert s.method == "ids" and [r.doc_id for r in s.requirements][0] == "Ф-1"
    assert any("в течение минуты" in t for t in texts)          # НФТ без ID
    assert any(t.startswith("Порог 50 000 ₸ |") for t in texts)  # строка критериев приёмки
    assert "REST type | GET" in texts                            # параметр API
    assert not any("Школа" in t or "протестировано" in t for t in texts)  # метаданные и чек-лист шаблона — не требования
    assert all(r.rid.startswith("R-") for r in s.requirements)


def test_rest_get_for_mutation_and_empty_prod(tmp_path):
    from req_review.checker import deterministic_set_checks

    p = tmp_path / "api.md"
    p.write_text("# API\n\n## Функциональные требования\n- **F-1.** Клиент задаёт порог.\n\n### Общие параметры\n\n"
                 "| Поле | Значение |\n| :--- | :--- |\n| **REST type** | GET |\n"
                 "| **Request URL** | Dev: `/alerts/saveLimit` . Prod: — |\n\n### Логика работы метода\n"
                 "1. Заменить настройку и вернуть результат сохранения.\n", encoding="utf-8")
    doc = read_document(p)
    s = split_requirements(doc)
    found = deterministic_set_checks(s, doc)
    kinds = {(f.kind, f.severity) for f in found}
    assert ("contradiction", "critical") in kinds and ("gap", "critical") in kinds
    from req_review.verify import quote_in

    by = {r.rid: r.text for r in s.requirements}
    for f in found:
        for ref in f.refs:
            if ref.req_id in by:
                assert quote_in(ref.quote, by[ref.req_id])
