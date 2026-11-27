"""v13: «Комплаенс и безопасность» — правила (код) с дословными цитатами и ссылками на нормы из kb/law_kz.

Проверки (работают на любом ТЗ, без модели):
  pii_unmasked     — номер карты / ИИН / телефон показываются или передаются, а маскирование нигде не описано;
  secrets_in_logs  — в журнал / лог пишутся ПИН, CVV, пароль, код подтверждения или токен;
  card_storage     — хранение CVV/CVC, ПИН или полного номера карты;
  optional_auth    — подтверждение операции (код, биометрия, 2FA) сделано необязательным;
  no_auth          — есть денежные операции, но подтверждение / аутентификация нигде не описаны;
  no_audit         — есть денежные операции или изменения настроек, но журнал аудита нигде не описан;
  no_consent       — собираются персональные данные или запрос в бюро / госбазу, но согласие клиента не описано.
Узкий проход модели «комплаенс и безопасность» — в профиле deep (focus.PASSES["focus_compliance"]).
Если такое замечание уже найдено, новое не создаётся — проверка ссылается на найденное (как трассировка).
"""
from __future__ import annotations

import re

from .checker import SetFinding, SetRef
from .textutil import clip_quote
from .verify import quote_in

NORMS = {"pdata": "Закон РК «О персональных данных и их защите» — согласие",
         "pdata_storage": "Закон РК «О персональных данных и их защите» — хранение и защита",
         "bank_secrecy": "Закон РК «О банках и банковской деятельности» — банковская тайна",
         "payments": "Закон РК «О платежах и платёжных системах» — безопасность платёжных услуг",
         "infosec": "Требования к информационной безопасности банков — аутентификация и журналирование",
         "pci": "PCI DSS — запрет хранения CVV/ПИН после авторизации, маскирование номера карты"}

_PII = re.compile(r"номер\w* карт\w*|\bPAN\b|\bИИН\b|номер\w* телефон\w*|паспорт\w*|удостоверени\w* личности", re.I)
_SHOW = re.compile(r"\b(показ\w*|отобража\w*|выв(одит|одить|еде\w*)|отправл\w*|переда\w*|печат\w*|выгруж\w*|в чек\w*|в квитанци\w*)",
                   re.I)
_MASK = re.compile(r"маск\w*|скрыт\w*|последни\w* 4|первые \d+ и последние \d+|\*{3,}", re.I)
_LOG = re.compile(r"журнал\w*|\bлог\w*|логир\w*", re.I)
_SECRET = re.compile(r"\bПИН\w*|\bPIN\b|\bCVV\w*|\bCVC\w*|парол\w*|код\w* подтвержд\w*|одноразов\w* код\w*|\bOTP\b|токен\w*",
                     re.I)
_NEG = re.compile(r"\bне (записыва|хран|логир|сохран|переда)|\bзапрещ\w*|\bбез (записи|хранения)|исключ\w*", re.I)
_STORE = re.compile(r"\b(хран\w*|сохран\w*|запомина\w*)", re.I)
_CARD_SECRET = re.compile(r"\bCVV\w*|\bCVC\w*|\bПИН\w*|полн\w* номер\w* карт\w*", re.I)
_AUTH = re.compile(r"подтвержд\w*|одноразов\w* код\w*|\bOTP\b|2FA|двухфактор\w*|биометри\w*|ПИН-код\w*|аутентифика\w*|"
                   r"авториз\w*|Bearer|сесси\w*", re.I)
_OPTIONAL = re.compile(r"по желанию|при необходимости|можно пропустить|необязательн\w*|опционально|по выбору клиента", re.I)
_MONEY = re.compile(r"\b(перев(од|ести|одит)\w*|оплат\w*|списан\w*|списыва\w*|обмен\w*|погаш\w*|перечисл\w*|"
                    r"выда(ча|вать) кредит\w*)", re.I)
_SETTINGS = re.compile(r"\b(измен\w* (настро|лимит|порог)|сохран\w* (настро|порог|лимит))", re.I)
_AUDIT = re.compile(r"аудит\w*|журнал\w* (действий|операций|событий|изменений|аудита)|журналир\w* (действий|операций)", re.I)
_PDATA_COLLECT = re.compile(r"\b(запрашива\w*|собира\w*|получа\w*|провер\w*)\b[^.]{0,60}(ИИН|паспорт|доход|кредитн\w* бюро|"
                            r"государствен\w* баз\w*)", re.I)
_CONSENT = re.compile(r"согласи\w*", re.I)

CHECKS = [("pii_unmasked", "Персональные данные без маскирования", "pdata_storage"),
          ("secrets_in_logs", "Секреты в журналах", "infosec"),
          ("card_storage", "Хранение CVV / ПИН / полного номера карты", "pci"),
          ("optional_auth", "Необязательное подтверждение операции", "payments"),
          ("no_auth", "Денежные операции без описанного подтверждения", "payments"),
          ("no_audit", "Нет журнала аудита операций и изменений", "infosec"),
          ("no_consent", "Сбор персональных данных без согласия", "pdata")]


def _sentence(text: str, m: re.Match) -> str:
    """Дословное предложение вокруг совпадения (не длиннее ~160 символов)."""
    s = max(text.rfind(". ", 0, m.start()) + 2 if text.rfind(". ", 0, m.start()) >= 0 else 0, 0)
    e = text.find(". ", m.end())
    q = text[s: e + 1 if e >= 0 else len(text)].strip()
    return clip_quote(q, 160)


def run(rv) -> dict:
    """Проверки → {"checks": [...], "findings": n}; новые замечания добавляются в rv.set_findings."""
    reqs = [rr.req for rr in rv.req_results]
    text = rv.doc.text
    hits: dict[str, list[tuple]] = {c[0]: [] for c in CHECKS}
    applicable = {c[0]: False for c in CHECKS}
    masked = bool(_MASK.search(text))
    for r in reqs:
        t = r.text
        if (m := _PII.search(t)) and _SHOW.search(t):
            applicable["pii_unmasked"] = True
            if not masked and not _MASK.search(t):
                hits["pii_unmasked"].append((r, _sentence(t, m), m.group(0)))
        if _LOG.search(t) and (m := _SECRET.search(t)):
            applicable["secrets_in_logs"] = True
            if not _NEG.search(t):
                hits["secrets_in_logs"].append((r, _sentence(t, m), m.group(0)))
        if _STORE.search(t) and (m := _CARD_SECRET.search(t)):
            applicable["card_storage"] = True
            if not _NEG.search(t):
                hits["card_storage"].append((r, _sentence(t, m), m.group(0)))
        if (m := _AUTH.search(t)) and (o := _OPTIONAL.search(t)):
            applicable["optional_auth"] = True
            hits["optional_auth"].append((r, _sentence(t, o), o.group(0)))
    money = [r for r in reqs if _MONEY.search(r.text)]
    change = [r for r in reqs if _SETTINGS.search(r.text)]
    if money:
        applicable["no_auth"] = True
        if not _AUTH.search(text):
            r = money[0]
            hits["no_auth"].append((r, _sentence(r.text, _MONEY.search(r.text)), ""))
    if money or change:
        applicable["no_audit"] = True
        if not _AUDIT.search(text):
            r = (money or change)[0]
            hits["no_audit"].append((r, _sentence(r.text, (_MONEY.search(r.text) or _SETTINGS.search(r.text))), ""))
    collect = [(r, m) for r in reqs for m in [_PDATA_COLLECT.search(r.text)] if m]
    if collect:
        applicable["no_consent"] = True
        if not _CONSENT.search(text):
            r, m = collect[0]
            hits["no_consent"].append((r, _sentence(r.text, m), m.group(2)))
    checks, new = [], 0
    for cid, title, norm in CHECKS:
        hs = [(r, q, w) for r, q, w in hits[cid] if quote_in(q, r.text)]
        row = {"id": cid, "title": title, "norm": NORMS[norm], "kb": norm,
               "status": "fired" if hs else ("passed" if applicable[cid] else "not_applicable"), "where": [], "finding": None}
        if hs:
            row["where"] = [r.doc_id or r.rid for r, _, _ in hs[:8]]
            f, is_new = _finding(rv, cid, title, norm, hs)
            row["_finding"], row["new"] = f, is_new
            new += is_new
        checks.append(row)
    return {"checks": checks, "findings": new, "fired": sum(c["status"] == "fired" for c in checks)}


_PROBLEM = {
    "pii_unmasked": "Персональные данные ({w}) показываются или передаются, но маскирование в документе не описано — "
                    "полный номер / ИИН увидит любой, у кого открыт экран, чек или уведомление.",
    "secrets_in_logs": "В журнал записывается секрет ({w}) — утечка журнала раскрывает средства доступа клиента.",
    "card_storage": "Требование допускает хранение {w} — после авторизации эти данные хранить нельзя.",
    "optional_auth": "Подтверждение операции сделано необязательным («{w}») — операцию можно провести без проверки клиента.",
    "no_auth": "Описаны денежные операции, но ни подтверждение (код, биометрия, ПИН), ни аутентификация клиента нигде не описаны.",
    "no_audit": "Есть денежные операции или изменения настроек, но журнал аудита (кто, что, когда) нигде не описан — "
                "спорную операцию нельзя разобрать.",
    "no_consent": "Собираются персональные данные или запрос во внешний источник ({w}), но согласие клиента нигде не описано.",
}
_FIX = {
    "pii_unmasked": "Описать маскирование: номер карты — первые 6 и последние 4 цифры, ИИН и телефон — частично; где полный показ разрешён.",
    "secrets_in_logs": "Записать явно: ПИН, CVV, пароли, коды подтверждения и токены в журналы не пишутся (или маскируются).",
    "card_storage": "Убрать хранение CVV/ПИН; полный номер карты — только в защищённом хранилище (токенизация), в остальных местах маскировать.",
    "optional_auth": "Указать, при каких операциях и суммах подтверждение обязательно и чем (одноразовый код, биометрия); убрать «по желанию».",
    "no_auth": "Добавить требование: каждая денежная операция выполняется после аутентификации и подтверждения клиентом (способ, срок кода).",
    "no_audit": "Добавить требование к журналу аудита: событие, клиент или сотрудник, время, старое и новое значение, срок хранения.",
    "no_consent": "Добавить требование о согласии клиента (момент получения, текст, хранение, отзыв) до сбора данных или запроса.",
}
_LINK = {"pii_unmasked": r"маск", "secrets_in_logs": r"журнал|лог", "card_storage": r"CVV|CVC|ПИН|PIN",
         "optional_auth": r"подтвержд|2FA|OTP|биометр", "no_auth": r"подтвержд|аутентиф|2FA|OTP",
         "no_audit": r"аудит|журнал", "no_consent": r"согласи"}


def _finding(rv, cid, title, norm, hs) -> tuple[SetFinding, bool]:
    key = re.compile(_LINK[cid], re.I)
    words = ", ".join(dict.fromkeys(w for _, _, w in hs if w)) or "—"
    rids = {r.rid for r, _, _ in hs}
    for f in list(rv.set_findings) + [f for rr in rv.req_results for f in rr.findings]:  # уже найдено — связать
        if f.source == "комплаенс (правило)":
            continue  # свои же замечания других проверок — не «уже найдено»
        refs = {x.req_id for x in getattr(f, "refs", [])} or {getattr(f, "req_id", "")}
        if key.search(f.problem) and (refs & rids or cid in ("no_auth", "no_audit", "no_consent")):
            return f, False
    sev = "critical" if cid in ("secrets_in_logs", "card_storage", "optional_auth") else "major"
    f = SetFinding("gap", "set_complete", [SetRef(r.rid, q) for r, q, _ in hs[:4]],
                   _PROBLEM[cid].format(w=words) + f" Норма: {NORMS[norm]}.", sev, _FIX[cid], "комплаенс (правило)")
    rv.set_findings.append(f)
    return f, True


def to_json(rv) -> dict:
    from .traceability import finding_id

    c = getattr(rv, "compliance", None) or {}
    if not c:
        return {}
    checks = [{k: v for k, v in x.items() if not k.startswith("_")} | {"finding": finding_id(rv, x["_finding"]) if x.get("_finding") else ""}
              for x in c["checks"]]
    return {"checks": checks, "fired": c["fired"], "new_findings": c["findings"]}


def report_md(rv) -> list[str]:
    c = to_json(rv)
    if not c:
        return []
    icon = {"fired": "⚠️", "passed": "✅", "not_applicable": "—"}
    w = ["### Комплаенс и безопасность (правила, нормы — kb/law_kz)", "",
         "| Проверка | Итог | Где | Замечание | Норма |", "|---|---|---|---|---|"]
    for x in c["checks"]:
        fid = x.get("finding") or ""
        mark = (f"[{fid}](#{fid.lower()})" + ("" if x.get("new") else " (уже найдено)")) if fid else "—"
        st = {"fired": "нарушение", "passed": "описано", "not_applicable": "не применимо"}[x["status"]]
        w.append(f"| {x['title']} | {icon[x['status']]} {st} | {', '.join(x['where']) or '—'} | {mark} | {x['norm']} |")
    w += ["", "Это проверка по тексту требований, а не юридическое заключение; нормы — краткий пересказ команды (kb/).", ""]
    return w
