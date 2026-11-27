"""v12: общие правила пропусков — на выдуманных мини-ТЗ (не на документе организаторов).

Каждое правило: срабатывает на дефектном примере, молчит на исправленном, цитаты дословные (verify.quote_in)."""
import pytest

from req_review.depth_v12 import data_model_gaps, error_without_code, repeat_action, same_object_names, stub_sections
from req_review.reader import read_document
from req_review.rules import check_requirement
from req_review.splitter import split_requirements
from req_review.verify import quote_in


def _doc(tmp_path, text, name="tz.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    doc = read_document(p)
    return doc, split_requirements(doc).requirements


def _quotes_ok(fs, doc):
    for f in fs:
        for r in f.refs:
            assert quote_in(r.quote, doc.text), r.quote


CASHBACK = """# Кэшбэк по подписке (выдуманный пример)

## Функциональные требования
- **К-1.** Клиент включает кэшбэк переключателем на экране «Подписки». По умолчанию кэшбэк выключен.
- **К-2.** Возврат уменьшает кэшбэк месяца исходной покупки. Снятие наличных и переводы исключаются.
- **К-3.** При изменении категории накопленный кэшбэк сохраняется и начисление идёт заново.

## Требования к данным
Хранить идентификатор карты, месяц, сумму кэшбэка в тиынах.
"""


def test_data_model_gaps(tmp_path):
    doc, reqs = _doc(tmp_path, CASHBACK)
    fs = data_model_gaps(reqs, doc)
    assert len(fs) == 1 and fs[0].criterion == "set_complete" and fs[0].severity == "major"
    p = fs[0].problem
    assert "признак включения" in p and "тип операции" in p and "связь возврата" in p
    _quotes_ok(fs, doc)
    fixed = CASHBACK.replace("сумму кэшбэка в тиынах.", "сумму кэшбэка в тиынах, признак включения кэшбэка, тип операции "
                                                         "и идентификатор исходной покупки для возврата.")
    doc2, reqs2 = _doc(tmp_path, fixed, "ok.md")
    assert data_model_gaps(reqs2, doc2) == []


def test_repeat_action(tmp_path):
    doc, reqs = _doc(tmp_path, CASHBACK)
    fs = repeat_action(reqs, doc)
    assert len(fs) == 1 and "При изменении категории" in fs[0].refs[0].quote and "того же значения" in fs[0].problem
    _quotes_ok(fs, doc)
    doc2, reqs2 = _doc(tmp_path, CASHBACK + "\nСохранение той же категории изменением не считается.\n", "ok.md")
    assert repeat_action(reqs2, doc2) == []


def test_stub_sections(tmp_path):
    text = CASHBACK + "\n## Тестирование\nзаполняется позже\n\n## Ревью требований\nTBD\n\n## Нагрузка\nTBD\n"
    doc, reqs = _doc(tmp_path, text)
    fs = stub_sections(reqs, doc)
    assert len(fs) == 1 and "«Тестирование»" in fs[0].problem and "«Нагрузка»" in fs[0].problem
    assert "Ревью" not in fs[0].problem  # служебные разделы шаблона — отдельное правило template_unfilled
    _quotes_ok(fs, doc)
    doc2, reqs2 = _doc(tmp_path, CASHBACK + "\n## Тестирование\nПроверяются К-1…К-3 по критериям приёмки.\n", "ok.md")
    assert stub_sections(reqs2, doc2) == []


def test_same_object_names(tmp_path):
    text = CASHBACK + "\n## Доступ\nКэшбэк видит только владелец карты. Держатель карты получает push.\n"
    doc, reqs = _doc(tmp_path, text)
    fs = same_object_names(reqs, doc)
    assert any("«владелец карты»" in f.problem and "«Держатель карты»" in f.problem for f in fs)
    _quotes_ok(fs, doc)
    doc2, reqs2 = _doc(tmp_path, CASHBACK + "\n## Доступ\nКэшбэк видит только держатель карты.\n", "ok.md")
    assert same_object_names(reqs2, doc2) == []


API = """# API кэшбэка (выдуманный пример)

## Статусы
### 400. Bad request
```
{"message":"Неверная категория"}
```
### 404. Not found
```
{"message":"Карта не найдена"}
```
"""


def test_error_without_code(tmp_path):
    doc, reqs = _doc(tmp_path, API)
    fs = error_without_code(reqs, doc)
    assert len(fs) == 1 and fs[0].severity == "minor" and "машинного кода" in fs[0].problem
    _quotes_ok(fs, doc)
    doc2, reqs2 = _doc(tmp_path, API.replace('{"message":"Неверная категория"}',
                                             '{"code":"BAD_CATEGORY","message":"Неверная категория"}'), "ok.md")
    assert error_without_code(reqs2, doc2) == []


@pytest.mark.parametrize("text,expected", [
    ("- **К-9.** Месяц считается по дате покупки в Алматы. В расчёт входят проведённые покупки. Возврат уменьшает сумму "
     "исходного месяца. Переводы исключаются.", True),
    ("- **К-9.** Месяц считается по дате покупки в Алматы. Переводы исключаются.", False),
    ("- **К-9.** Карты → Расходы → Кэшбэк. На экране видны переключатель и сумма. Ошибка показывается под полем.", False),
])
def test_non_atomic_requirement(tmp_path, text, expected):
    doc, reqs = _doc(tmp_path, "# ТЗ\n\n## Требования\n" + text + "\n")
    hits = [h for r in reqs for h in check_requirement(r) if h.criterion == "singular" and h.keep]
    assert bool(hits) is expected
    for h in hits:
        assert quote_in(h.quote, doc.text) and "самостоятельных правила" in h.problem
