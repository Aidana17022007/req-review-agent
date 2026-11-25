"""Генератор бенчмарка: внедряет известные дефекты в bench/clean.md.

Запуск: python bench/inject.py  →  bench/seeded.md + bench/ground_truth.json
Каждый дефект — точная подмена в тексте конкретного требования, поэтому «правильный ответ» известен заранее.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (тип дефекта, ID требования, что заменить, на что заменить, критерии, которыми дефект считается найденным)
DEFECTS = [
    ("vague", "PAY-01", "с поиском по названию", "с быстрым и удобным поиском", ["verifiable", "unambiguous"]),
    ("vague", "NFR-01", "не должно превышать 2 секунд для 95 % запросов при нагрузке до 300 запросов в секунду",
     "должно быть минимальным", ["verifiable", "unambiguous"]),
    ("missing_units", "PAY-07", "в течение 5 лет", "в течение длительного срока", ["verifiable", "unambiguous", "complete"]),
    ("open_list", "PAY-08", "по периоду и поставщику", "по периоду, поставщику и т.д.", ["complete"]),
    ("tbd", "NFR-05", "каждые 24 часа и храниться 30 дней", "с периодичностью TBD", ["complete"]),
    ("and_or", "PAY-09", "push-уведомление", "push-уведомление и/или SMS", ["unambiguous"]),
    ("conditional", "PAY-03", "за платёж в адрес поставщиков из справочника «Партнёры»", "при необходимости", ["unambiguous", "complete"]),
    ("design", "PAY-13", "с названием длиной до 40 символов", "в таблице PostgreSQL через выпадающий список", ["appropriate"]),
    ("compound", "PAY-12", "из справочника кодов отказа.",
     "из справочника кодов отказа, а также формировать ежемесячный отчёт для поставщика и отправлять его по e-mail.",
     ["singular"]),
    ("subjective", "NFR-06", "доступен на казахском и русском языках", "интуитивно понятным и современным", ["verifiable", "unambiguous"]),
    ("absolute", "NFR-02", "не менее 99,9 % в календарный месяц без учёта плановых работ", "100 % всегда", ["feasible", "verifiable"]),
]
# Противоречие: PAY-05 и новое требование SEC-01 задают разное число попыток
SET_DEFECTS = [
    ("contradiction", ["PAY-05", "SEC-01"],
     "- **SEC-01.** Система должна блокировать подтверждение платежа на 15 минут после 5 неверных вводов кода подряд.",
     ["set_consistent"]),
    ("duplicate", ["PAY-02", "PAY-15"],
     "- **PAY-15.** Система должна принимать платёж на сумму от 100 до 500 000 тенге включительно.",
     ["set_consistent", "necessary"]),
]


def build() -> tuple[str, dict]:
    text = (HERE / "clean.md").read_text(encoding="utf-8")
    text = text.replace("БЕНЧМАРК (вымышленный документ)", "БЕНЧМАРК С ВНЕДРЁННЫМИ ДЕФЕКТАМИ (вымышленный документ)")
    truth = {"defects": []}
    for kind, rid, old, new, crit in DEFECTS:
        line = next(l for l in text.splitlines() if f"**{rid}.**" in l)
        assert old in line, (rid, old)
        text = text.replace(line, line.replace(old, new, 1), 1)
        truth["defects"].append({"type": kind, "ids": [rid], "criteria": crit, "level": "requirement"})
    add = "\n".join(line for _, _, line, _ in SET_DEFECTS)
    text = text.replace("\n## 3. Нефункциональные требования", "\n" + add + "\n\n## 3. Нефункциональные требования", 1)
    for kind, ids, _, crit in SET_DEFECTS:
        truth["defects"].append({"type": kind, "ids": ids, "criteria": crit, "level": "set"})
    clean_ids = [l.split("**")[1].rstrip(".") for l in text.splitlines() if l.startswith("- **")]
    seeded = {i for d in truth["defects"] for i in d["ids"]}
    truth["clean_ids"] = [i for i in clean_ids if i not in seeded]
    return text, truth


def main():
    text, truth = build()
    (HERE / "seeded.md").write_text(text, encoding="utf-8")
    (HERE / "ground_truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"bench/seeded.md: внедрено дефектов {len(truth['defects'])}, чистых требований {len(truth['clean_ids'])}")


if __name__ == "__main__":
    main()
