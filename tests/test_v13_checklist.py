"""v13+ A12: чек-лист «Ревью требований» из шаблона документа заполняется агентом и молчит, если чек-листа нет."""
from req_review.checker import ReqResult, ReviewResult, SetFinding, SetRef
from req_review.reader import read_document
from req_review.splitter import split_requirements

TZ = """# Мини-ТЗ (выдуманное)

## Функциональные требования
- **Ф-1.** Клиент задаёт лимит от 1 000 до 100 000 тенге.
- **Ф-2.** Лимит действует со следующего дня.

## Требования к данным
Хранить лимит и дату изменения.

## Ревью требований

| Проверка | Создано или доступно | Проверено |
| :--- | :--- | :--- |
| Требование может быть протестировано | Да / Нет | Да / Нет |
| Требование не имеет противоречий | Да / Нет | Да / Нет |
| Реализация предусматривает схему отката решений | Да / Нет | Да / Нет |
| Все изменения согласованы с ответственными | Да / Нет | Да / Нет |
| Пункт про цвет кнопок | Да / Нет | Да / Нет |

## Блок согласующих

| Подразделение | ФИО ответственного | Подпись |
| :--- | :--- | :--- |
| | | |
"""


def _rv(tmp_path, text, set_findings=()):
    p = tmp_path / "tz.md"
    p.write_text(text, encoding="utf-8")
    doc = read_document(p)
    sp = split_requirements(doc)
    return ReviewResult(doc=doc, split=sp, req_results=[ReqResult(req=r) for r in sp.requirements],
                        set_findings=list(set_findings), dropped=[])


def test_checklist_filled_with_answers_and_refs(tmp_path):
    from req_review.bank_checklist import fill, report_md

    rv = _rv(tmp_path, TZ)
    rv.set_findings.append(SetFinding("contradiction", "set_consistent", [SetRef(rv.req_results[0].req.rid, "от 1 000")],
                                      "Лимит задан двумя значениями.", "critical", "", "LLM"))
    bc = fill(rv)
    assert bc["section"] == "Ревью требований" and len(bc["items"]) == 5
    ans = {i["item"]: i for i in bc["items"]}
    assert ans["Требование может быть протестировано"]["answer"] == "да"
    c = ans["Требование не имеет противоречий"]
    assert c["answer"] == "нет" and c["refs"] == ["S-01"]
    assert ans["Реализация предусматривает схему отката решений"]["answer"] == "нет"  # слово «отката» — только в чек-листе
    assert ans["Все изменения согласованы с ответственными"]["answer"] == "нет"  # блок согласующих пуст
    assert ans["Пункт про цвет кнопок"]["answer"] == "не оценено"
    md = "\n".join(report_md(bc))
    assert "Чек-лист «Ревью требований» — заполнен агентом" in md and "[S-01]" in md


def test_checklist_absent_gives_nothing(tmp_path):
    from req_review.bank_checklist import fill

    rv = _rv(tmp_path, TZ.split("## Ревью требований")[0])
    assert fill(rv) == {}


def test_approvals_filled_means_yes(tmp_path):
    from req_review.bank_checklist import fill

    rv = _rv(tmp_path, TZ.replace("| | | |", "| Казначейство | Иванова А. | подписано |"))
    ans = {i["item"]: i["answer"] for i in fill(rv)["items"]}
    assert ans["Все изменения согласованы с ответственными"] == "да"


def test_checklist_in_report_json_and_section_6(tmp_path, monkeypatch):
    import json

    from req_review.pipeline import Options, run

    monkeypatch.setenv("LLM_PROVIDER", "rules")
    src = tmp_path / "tz.md"
    src.write_text(TZ, encoding="utf-8")
    out = tmp_path / "r.md"
    run(str(src), str(out), Options(html=False, xlsx=False, jira=False, pdf=False), log=lambda m: None)
    data = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["bank_checklist"]["summary"]["не оценено"] == 1
    md = out.read_text(encoding="utf-8")
    assert md.index("## 6. Итог") < md.index("### Чек-лист «Ревью требований»")
