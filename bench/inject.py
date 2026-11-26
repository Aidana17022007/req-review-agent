"""Генератор бенчмарка: внедряет заранее известные дефекты в 3 вымышленных документа.

Запуск: python bench/inject.py  →  bench/out/<doc>_seeded.md + bench/ground_truth.json
Каждый дефект — точная подмена в тексте конкретного требования, поэтому «правильный ответ» известен заранее.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

# Тип дефекта → критерии, по которым замечание засчитывается как найденное
VAGUE = ["verifiable", "unambiguous"]

# doc: (тип, ID требования, что заменить, на что заменить, критерии)
DEFECTS = {
    "payments": [
        ("vague", "PAY-01", "с поиском по названию", "с быстрым и удобным поиском", VAGUE),
        ("vague", "NFR-01", "не должно превышать 2 секунд для 95 % запросов при нагрузке до 300 запросов в секунду",
         "должно быть минимальным", VAGUE),
        ("missing_units", "PAY-07", "в течение 5 лет", "в течение длительного срока", ["verifiable", "unambiguous", "complete"]),
        ("open_list", "PAY-08", "по периоду и поставщику", "по периоду, поставщику и т.д.", ["complete"]),
        ("tbd", "NFR-05", "каждые 24 часа и храниться 30 дней", "с периодичностью TBD", ["complete"]),
        ("and_or", "PAY-09", "push-уведомление", "push-уведомление и/или SMS", ["unambiguous"]),
        ("conditional", "PAY-03", "за платёж в адрес поставщиков из справочника «Партнёры»", "при необходимости", ["unambiguous", "complete"]),
        ("design", "PAY-13", "с названием длиной до 40 символов", "в таблице PostgreSQL через выпадающий список", ["appropriate"]),
        ("compound", "PAY-12", "из справочника кодов отказа.",
         "из справочника кодов отказа, а также формировать ежемесячный отчёт для поставщика и отправлять его по e-mail.", ["singular"]),
        ("subjective", "NFR-06", "доступен на казахском и русском языках", "интуитивно понятным и современным", VAGUE),
        ("absolute", "NFR-02", "не менее 99,9 % в календарный месяц без учёта плановых работ", "100 % всегда", ["feasible", "verifiable"]),
    ],
    "credit": [
        ("vague", "CR-03", "до отправки заявки", "быстро и точно до отправки заявки", VAGUE),
        ("missing_units", "CR-11", "5 лет с момента подачи", "длительный срок", ["verifiable", "unambiguous", "complete"]),
        ("open_list", "CR-04", "ИИН, место работы и ежемесячный доход в тенге", "ИИН, место работы, доход и т.д.", ["complete"]),
        ("tbd", "CR-10", "не позднее 15 минут после подписания договора", "в срок TBD после подписания договора", ["complete"]),
        ("and_or", "CR-13", "push-уведомление", "push-уведомление и/или e-mail", ["unambiguous"]),
        ("conditional", "CR-05", "до запуска скоринга", "при необходимости", ["unambiguous", "complete"]),
        ("design", "CR-07", "одобренную сумму, ставку и график платежей", "одобренную сумму во всплывающем окне на React", ["appropriate"]),
        ("compound", "CR-12", "в любой момент до подписания договора.",
         "в любой момент до подписания договора, а также формировать выписку по всем кредитам и отправлять её в налоговую службу.",
         ["singular"]),
        ("subjective", "CNF-01", "Время ответа на расчёт ежемесячного платежа не должно превышать 1 секунды для 95 % запросов",
         "Расчёт ежемесячного платежа должен быть удобным и интуитивно понятным", VAGUE),
        ("absolute", "CNF-02", "не менее 99,5 % в календарный месяц", "100 % всегда", ["feasible", "verifiable"]),
        ("vague_goal", "CNF-03", "должны передаваться только по протоколу TLS версии 1.2 и выше", "должны быть надёжно защищены",
         ["verifiable", "unambiguous"]),
        ("vague", "CR-06", "не позднее 5 минут после отправки заявки", "своевременно после отправки заявки", VAGUE),
    ],
    "onboarding": [
        ("vague", "ON-04", "распознавать ИИН, ФИО и дату рождения", "быстро распознавать ИИН, ФИО и дату рождения", VAGUE),
        ("open_list", "ON-03", "в формате JPEG или PNG размером до 10 МБ", "в форматах JPEG, PNG и т.п.", ["complete"]),
        ("tbd", "ON-10", "7 дней", "в течение срока, который будет определён позднее", ["complete"]),
        ("and_or", "ON-12", "SMS с подтверждением", "SMS и/или push-уведомление с подтверждением", ["unambiguous"]),
        ("conditional", "ON-13", "до открытия счёта", "по возможности", ["unambiguous", "complete"]),
        ("design", "ON-14", "выбрать язык интерфейса: казахский или русский", "выбрать язык интерфейса в выпадающем списке на Kotlin",
         ["appropriate"]),
        ("compound", "ON-08", "номер счёта и реквизиты после открытия счёта.",
         "номер счёта и реквизиты после открытия счёта, а также выпускать виртуальную карту и отправлять её данные по e-mail.",
         ["singular"]),
        ("subjective", "ONF-03", "обслуживать не менее 100 одновременных сессий онбординга", "быть удобной и современной", VAGUE),
        ("absolute", "ON-05", "и принимать решение о совпадении", "и гарантировать 100 % точность без ошибок", ["feasible", "verifiable"]),
        ("vague_goal", "ONF-02", "должны храниться в зашифрованном виде и удаляться через 90 дней после открытия счёта",
         "должны быть обеспечены защитой от утечек", ["verifiable", "unambiguous"]),
        ("missing_units", "ONF-01", "не должно превышать 5 секунд для 95 % запросов", "должно быть минимальным", VAGUE),
        ("passive", "ON-11", "Система должна запрашивать согласие клиента на сбор и обработку персональных данных",
         "Согласие клиента на сбор и обработку персональных данных должно быть получено", ["complete", "conforming"]),
    ],
}

# Дефекты уровня набора: новые требования, конфликтующие или дублирующие существующие
SET_DEFECTS = {
    "payments": [
        ("contradiction", ["PAY-05", "SEC-01"],
         "- **SEC-01.** Система должна блокировать подтверждение платежа на 15 минут после 5 неверных вводов кода подряд.",
         ["set_consistent"]),
        ("duplicate", ["PAY-02", "PAY-15"],
         "- **PAY-15.** Система должна принимать платёж на сумму от 100 до 500 000 тенге включительно.", ["set_consistent", "necessary"]),
    ],
    "credit": [
        ("contradiction", ["CR-01", "CR-15"],
         "- **CR-15.** Система должна принимать заявку на кредит на сумму от 100 000 до 3 000 000 тенге.", ["set_consistent"]),
        ("duplicate", ["CR-02", "CR-16"],
         "- **CR-16.** Система должна предлагать срок кредита от 6 до 60 месяцев с шагом 6 месяцев.", ["set_consistent", "necessary"]),
    ],
    "onboarding": [
        ("contradiction", ["ON-09", "ON-15"],
         "- **ON-15.** Система должна блокировать онбординг на 12 часов после 5 неудачных попыток верификации подряд.",
         ["set_consistent"]),
        ("duplicate", ["ON-07", "ON-16"],
         "- **ON-16.** Система должна открывать текущий счёт в тенге не позднее 10 минут после успешной верификации.",
         ["set_consistent", "necessary"]),
    ],
}


def build_doc(name: str) -> tuple[str, dict]:
    text = (HERE / "docs" / f"{name}.md").read_text(encoding="utf-8")
    text = text.replace("БЕНЧМАРК (вымышленный документ)", "БЕНЧМАРК С ВНЕДРЁННЫМИ ДЕФЕКТАМИ (вымышленный документ)")
    defects = []
    for kind, rid, old, new, crit in DEFECTS[name]:
        line = next(line for line in text.splitlines() if f"**{rid}.**" in line)
        assert old in line, (name, rid, old)
        text = text.replace(line, line.replace(old, new, 1), 1)
        defects.append({"doc": name, "type": kind, "ids": [rid], "criteria": crit, "level": "requirement"})
    add = "\n".join(line for _, _, line, _ in SET_DEFECTS[name])
    marker = next(m for m in ("\n## 3. Нефункциональные требования",) if m in text)
    text = text.replace(marker, "\n" + add + "\n" + marker, 1)
    for kind, ids, _, crit in SET_DEFECTS[name]:
        defects.append({"doc": name, "type": kind, "ids": ids, "criteria": crit, "level": "set"})
    all_ids = [line.split("**")[1].rstrip(".") for line in text.splitlines() if line.startswith("- **")]
    seeded = {i for d in defects for i in d["ids"]}
    return text, {"defects": defects, "clean_ids": [i for i in all_ids if i not in seeded]}


def build_all() -> dict:
    OUT.mkdir(exist_ok=True)
    truth = {"documents": {}}
    for name in DEFECTS:
        text, t = build_doc(name)
        (OUT / f"{name}_seeded.md").write_text(text, encoding="utf-8")
        truth["documents"][name] = t
    truth["total_defects"] = sum(len(d["defects"]) for d in truth["documents"].values())
    (HERE / "ground_truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    return truth


def main():
    truth = build_all()
    for name, d in truth["documents"].items():
        print(f"bench/out/{name}_seeded.md: дефектов {len(d['defects'])}, чистых требований {len(d['clean_ids'])}")
    print(f"Всего внедрено дефектов: {truth['total_defects']}")


if __name__ == "__main__":
    main()
