"""Генератор бенчмарка: внедряет заранее известные дефекты в 5 вымышленных документов.

Запуск: python bench/inject.py  →  bench/out/<doc>_seeded.md (или .docx) + bench/ground_truth.json
Каждый дефект — точная подмена в тексте конкретного требования, поэтому «правильный ответ» известен заранее.
Документы: оплата услуг, онлайн-кредит, открытие счёта (Markdown, списки), онлайн-депозит на казахском языке
(deposit_kk) и перевыпуск карты (cards) — DOCX, где требования лежат в таблицах Word.
"""
from __future__ import annotations

import json
import re
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
    "deposit_kk": [  # казахский язык
        ("vague", "DEP-01", "мерзімі мен жылдық тиімді мөлшерлемесін көрсете отырып", "жылдам және ыңғайлы түрде", VAGUE),
        ("vague", "DNF-01", "секундына 200 сұраныс жүктемесінде сұраныстардың 95 %-ы үшін 2 секундтан аспауы тиіс",
         "барынша аз болуы тиіс", VAGUE),
        ("missing_units", "DEP-08", "5 жыл бойы", "ұзақ мерзім бойы", ["verifiable", "unambiguous", "complete"]),
        ("open_list", "DEP-11", "кезең және депозит түрі бойынша", "кезең, депозит түрі және т.б. бойынша", ["complete"]),
        ("tbd", "DNF-05", "әр 24 сағат сайын жасалып, 30 күн сақталуы тиіс", "TBD кезеңділікпен жасалуы тиіс", ["complete"]),
        ("and_or", "DEP-09", "push-хабарламаны", "push-хабарламаны және/немесе SMS", ["unambiguous"]),
        ("conditional", "DEP-04", "депозитті ашу алдында", "қажет болған жағдайда", ["unambiguous", "complete"]),
        ("design", "DEP-13", "40 таңбаға дейінгі атау", "PostgreSQL кестесіндегі ашылмалы тізім арқылы атау", ["appropriate"]),
        ("compound", "DEP-14", "экранда көрсетуі тиіс.",
         "экранда көрсетуі, сондай-ақ ай сайынғы үзінді көшірмені қалыптастырып, оны e-mail арқылы жіберуі тиіс.", ["singular"]),
        ("subjective", "DNF-06", "қазақ және орыс тілдерінде қолжетімді", "интуитивті түсінікті және заманауи", VAGUE),
        ("absolute", "DNF-02", "жоспарлы жұмыстарды есептемегенде күнтізбелік айда кемінде 99,9 %", "әрқашан 100 %",
         ["feasible", "verifiable"]),
    ],
    "cards": [  # DOCX: требования в таблицах Word
        ("vague", "CRD-01", "с указанием последних четырёх цифр номера и срока действия", "в быстром и удобном виде", VAGUE),
        ("vague", "KNF-01", "не должно превышать 2 секунд для 95 % запросов при нагрузке до 200 запросов в секунду",
         "должно быть минимальным", VAGUE),
        ("missing_units", "CRD-07", "в течение 5 лет", "в течение длительного срока", ["verifiable", "unambiguous", "complete"]),
        ("open_list", "CRD-08", "в отделении или курьером", "в отделении, курьером и т.д.", ["complete"]),
        ("tbd", "KNF-05", "каждые 24 часа и храниться 30 дней", "с периодичностью TBD", ["complete"]),
        ("and_or", "CRD-09", "push-уведомление", "push-уведомление и/или SMS", ["unambiguous"]),
        ("conditional", "CRD-03", "за плановый перевыпуск карты по окончании срока действия", "при необходимости",
         ["unambiguous", "complete"]),
        ("design", "CRD-13", "длиной до 200 символов", "в форме на React с автодополнением из таблицы PostgreSQL", ["appropriate"]),
        ("compound", "CRD-12", "из справочника кодов отказа.",
         "из справочника кодов отказа, а также формировать ежемесячный отчёт по перевыпускам и отправлять его в отделение по e-mail.",
         ["singular"]),
        ("subjective", "KNF-06", "доступен на казахском и русском языках", "интуитивно понятным и современным", VAGUE),
        ("absolute", "KNF-02", "не менее 99,9 % в календарный месяц без учёта плановых работ", "100 % всегда", ["feasible", "verifiable"]),
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
    "deposit_kk": [
        ("contradiction", ["DEP-06", "DEP-15"],
         "- **DEP-15.** Жүйе қате кодты қатарынан 5 рет енгізгеннен кейін қол қоюды 15 минутқа бұғаттауы тиіс.", ["set_consistent"]),
        ("duplicate", ["DEP-02", "DEP-16"],
         "- **DEP-16.** Жүйе депозитті 10 000-нан 50 000 000 теңгеге дейінгі сомаға (қоса алғанда) ашуға мүмкіндік беруі тиіс.",
         ["set_consistent", "necessary"]),
    ],
    "cards": [
        ("contradiction", ["CRD-05", "CRD-15"],
         "| CRD-15 | Система должна блокировать подтверждение заказа на 15 минут после 5 неверных вводов кода подряд. | Высокий |",
         ["set_consistent"]),
        ("duplicate", ["CRD-02", "CRD-16"],
         "| CRD-16 | Система должна позволять заказать перевыпуск карты не ранее чем за 60 дней до окончания срока её действия. | Высокий |",
         ["set_consistent", "necessary"]),
    ],
}

DOCX = {"cards"}  # документы, которые собираются в DOCX (таблицы Word)
NFR_MARKERS = ("\n## 3. Нефункциональные требования", "\n## 3. Функционалдық емес талаптар")
_ID_CELL = re.compile(r"^\|\s*([A-ZА-Я]{2,5}-\d+)\s*\|")


def _req_line(text: str, rid: str) -> str:
    return next(line for line in text.splitlines() if f"**{rid}.**" in line or line.startswith(f"| {rid} |"))


def build_doc(name: str) -> tuple[str, dict]:
    text = (HERE / "docs" / f"{name}.md").read_text(encoding="utf-8")
    text = text.replace("БЕНЧМАРК (вымышленный документ)", "БЕНЧМАРК С ВНЕДРЁННЫМИ ДЕФЕКТАМИ (вымышленный документ)")
    defects = []
    for kind, rid, old, new, crit in DEFECTS[name]:
        line = _req_line(text, rid)
        assert old in line, (name, rid, old)
        text = text.replace(line, line.replace(old, new, 1), 1)
        defects.append({"doc": name, "type": kind, "ids": [rid], "criteria": crit, "level": "requirement"})
    add = "\n".join(line for _, _, line, _ in SET_DEFECTS[name])
    marker = next(m for m in NFR_MARKERS if m in text)
    if name in DOCX:  # строки таблицы — в конец таблицы функциональных требований (без пустой строки)
        text = text.replace("\n" + marker, "\n" + add + "\n" + marker, 1)
    else:
        text = text.replace(marker, "\n" + add + "\n" + marker, 1)
    for kind, ids, _, crit in SET_DEFECTS[name]:
        defects.append({"doc": name, "type": kind, "ids": ids, "criteria": crit, "level": "set"})
    all_ids = [line.split("**")[1].rstrip(".") for line in text.splitlines() if line.startswith("- **")] + \
        [m.group(1) for line in text.splitlines() for m in [_ID_CELL.match(line)] if m]
    seeded = {i for d in defects for i in d["ids"]}
    return text, {"defects": defects, "clean_ids": [i for i in all_ids if i not in seeded]}


def write_docx(md: str, path: Path) -> None:
    """Markdown → DOCX: заголовки — стили Heading, таблицы — настоящие таблицы Word, цитаты — обычные абзацы.
    Метаданные фиксированы, чтобы файл был воспроизводимым (одинаковый текст → одинаковое содержимое)."""
    import datetime

    import docx

    d = docx.Document()
    cp = d.core_properties
    cp.author, cp.title = "ReqLens bench", md.splitlines()[0].lstrip("# ").strip()
    cp.created = cp.modified = datetime.datetime(2026, 1, 1)
    cp.last_modified_by, cp.revision = "ReqLens bench", 1
    rows: list[list[str]] = []

    def flush():
        if not rows:
            return
        t = d.add_table(rows=0, cols=len(rows[0]))
        t.style = "Table Grid"
        for r in rows:
            cells = t.add_row().cells
            for i, c in enumerate(r):
                cells[i].text = c
        rows.clear()

    for line in md.splitlines():
        s = line.strip()
        if s.startswith("|"):
            if not re.match(r"^\|?\s*:?-{3,}", s):
                rows.append([c.strip() for c in s.strip("|").split("|")])
            continue
        flush()
        if not s:
            continue
        h = re.match(r"^(#{1,6})\s+(.*)", s)
        if h:
            d.add_heading(h.group(2), level=len(h.group(1)))
        else:
            d.add_paragraph(s.lstrip("> ").strip())
    flush()
    import io
    import zipfile

    buf = io.BytesIO()
    d.save(buf)
    with zipfile.ZipFile(buf) as src, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():  # фиксированное время записей — повторная сборка даёт тот же файл
            zi = zipfile.ZipInfo(item.filename, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(zi, src.read(item.filename))


def build_all() -> dict:
    OUT.mkdir(exist_ok=True)
    truth = {"documents": {}}
    for name in DEFECTS:
        text, t = build_doc(name)
        if name in DOCX:
            write_docx(text, OUT / f"{name}_seeded.docx")
        else:
            (OUT / f"{name}_seeded.md").write_text(text, encoding="utf-8")
        t["file"] = f"bench/out/{name}_seeded.{'docx' if name in DOCX else 'md'}"
        truth["documents"][name] = t
    truth["total_defects"] = sum(len(d["defects"]) for d in truth["documents"].values())
    (HERE / "ground_truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    return truth


def main():
    truth = build_all()
    for name, d in truth["documents"].items():
        print(f"{d['file']}: дефектов {len(d['defects'])}, чистых требований {len(d['clean_ids'])}")
    print(f"Всего внедрено дефектов: {truth['total_defects']}")


if __name__ == "__main__":
    main()
