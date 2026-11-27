"""Противоречивый ответ без чисел: одному случаю — два разных HTTP-кода или метода из спорных вариантов вопроса.
Примеры выдуманные (не документ организаторов)."""
from types import SimpleNamespace as NS

import pytest

from req_review.answers import classify_rules

RV = NS(req_results=[], set_findings=[])
Q_CODES = NS(qid="Q-01", rid="S-01", criterion="set_consistent", refs=[],
             text="Раздел 409 описывает конфликт, но в примере для повторного перевода возвращается 422. Какой код верный?")
Q_METHOD = NS(qid="Q-02", rid="S-02", criterion="set_consistent", refs=[],
              text="Метод объявлен как GET, но создаёт перевод. Каким методом создаётся перевод?")


@pytest.mark.parametrize("q,answer,kind", [
    # один случай — два кода: противоречие
    (Q_CODES, "Повторный перевод с тем же ключом получает 409. Повторный перевод с тем же ключом получает 422.", "contradictory"),
    # один случай — два метода: противоречие
    (Q_METHOD, "Перевод создаётся методом POST. Перевод создаётся методом GET, как в текущем описании.", "contradictory"),
    # разные случаи — по коду на каждый: конкретный ответ
    (Q_CODES, "Повторный перевод с тем же ключом получает 409; 422 — только при неверной сумме.", "concrete"),
    (Q_METHOD, "Перевод создаётся методом POST /transfers; GET оставляем для чтения статуса перевода.", "concrete"),
    # код, которого нет в вопросе, и число с единицей не считаются кодом
    (Q_CODES, "Повторный перевод с тем же ключом получает 409. Повторный перевод ждёт ответа 500 мс.", "concrete"),
])
def test_token_conflict(q, answer, kind):
    t, quote, note = classify_rules(q, answer, RV)
    assert t == kind
    assert quote in answer  # цитата — дословная подстрока ответа
    if kind == "contradictory":
        assert "два разных" in note


def test_only_for_what_is_correct_questions():
    q = NS(qid="Q-03", rid="S-03", criterion="set_complete", refs=[], text="Не описаны коды 409 и 422.")
    a = "Повторный перевод с тем же ключом получает 409. Повторный перевод с тем же ключом получает 422."
    assert classify_rules(q, a, RV)[0] == "concrete"  # вопрос о пропуске: два значения — дополнение, не спор
