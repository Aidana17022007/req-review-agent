"""Автоклассификация требований (R4) и карта покрытия бизнес-процесса.

Категория: детерминированные правила по разделу и тексту + подтверждение моделью в том же запросе проверки
(без лишних обращений). Карта покрытия: шаги типового процесса домена (domains/<домен>.yaml, ключ process)
и требования, которые их покрывают; непокрытые шаги — пропуски набора с вопросом аналитику.
"""
from __future__ import annotations

import re

CATEGORIES = {
    "functional": "функциональное", "performance": "производительность", "availability": "доступность",
    "security": "безопасность", "data": "данные и хранение", "interface": "интерфейс (UI/API)",
    "integration": "интеграция", "regulatory": "регуляторное", "acceptance": "критерий приёмки", "other": "прочее",
}

RULES = [
    ("acceptance", r"критери\w* при[её]мк"),
    ("performance", r"время (?:ответа|отклика|обработки|распознавания)|в течение \w+ (?:секунд|минут)|не позднее|запросов в секунду|rps|нагрузк"),
    ("availability", r"доступност\w* .*%|24/7|отказоустойчив|резервн|надёжн\w*|надежн\w*|без сбоев"),
    ("security", r"авториз|аутентиф|bearer|токен|шифр|tls|одноразов\w* код|блокир|санкц|мошенн|принадлежност\w* карты"),
    ("data", r"хранить|хранени|храниться|база данных|db field|тиын|удаля\w+ через|журнал аудита"),
    ("integration", r"интеграц|процессинг|rest|api|curl|request url|статус\w* \d{3}|^\d{3}\.|controller|endpoint|ответ в случае"),
    ("interface", r"экран|кнопк|поле «|интерфейс|переключател|язык интерфейса|push|sms|уведомлен"),
    ("regulatory", r"персональн\w+ данн|согласи\w+ клиента|закон|регулятор|aml|финмониторинг"),
]


def classify(text: str, section: str = "") -> str:
    s = f"{section} {text}".lower()
    for cat, pat in RULES:
        if re.search(pat, s, re.IGNORECASE):
            return cat
    return "functional"


def apply_categories(rv) -> dict[str, int]:
    """Категория из ответа модели (если валидна) иначе — по правилам. Возвращает сводку по категориям."""
    counts: dict[str, int] = {}
    for rr in rv.req_results:
        if rr.category not in CATEGORIES:
            rr.category = classify(rr.req.text, rr.req.section)
        counts[rr.category] = counts.get(rr.category, 0) + 1
    return counts


def coverage_map(rv, domain: dict | None) -> list[dict]:
    """Шаги процесса домена → покрывающие требования (по ключевым словам шага)."""
    steps = (domain or {}).get("process") or []
    out = []
    for st in steps:
        kws = [k.lower() for k in st.get("keywords", [])]
        reqs = [rr.req.rid for rr in rv.req_results if any(k in rr.req.text.lower() for k in kws)]
        # v13+: шаг описан вне нарезки (таблица ошибок, раздел статусов) — тоже покрыт, ссылка «DOC»
        in_doc = not reqs and any(any(k in ln.text.lower() for k in kws) for ln in rv.doc.lines
                                  if not ln.text.lstrip().startswith("#"))
        out.append({"id": st["id"], "title": st["title"], "reqs": reqs or (["DOC"] if in_doc else []),
                    "covered": bool(reqs) or in_doc, "question": st.get("question", "")})
    return out
