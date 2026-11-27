"""v10: чек-лист банка в YAML — свои правила проверки без программирования.

    python review.py docs/req.md reports/r.md --rules fintech             (req_review/domains/fintech.rules.yaml)
    python review.py docs/req.md reports/r.md --rules my_bank.rules.yaml  (свой файл; или REQLENS_RULES=путь)

Формат правила (подробно — README, раздел «Свой чек-лист банка»):

    - id: BR-01                      # уникальный идентификатор
      title: Суммы — с валютой        # название для отчёта
      severity: major                # critical | major | minor
      criterion: complete            # ключ критерия из criteria.py (INDIVIDUAL или SET)
      scope: requirement             # requirement (каждое требование) | document (один раз на документ)
      when: {text: 'регулярка', section: 'регулярка'}   # к каким требованиям применимо; строка = {text: ...}
      require: {any: [...]}          # что должно быть: в тексте требования (scope requirement) или документа
      forbid: ['регулярка']          # чего не должно быть в тексте требования
      message: ...                   # проблема — текст замечания
      fix: ...                       # как исправить
      reference: 'Стандарт банка §4.2'   # необязательно
      enabled: false                 # необязательно: правило выключено, reason — почему

Регулярки — без учёта регистра. Каждое срабатывание — замечание с дословной цитатой из текста требования (проверка
verify.quote_in) и источником «правило банка: <id>». Правила добавляют замечания и ничего не удаляют; без --rules
прогон работает как раньше.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .criteria import INDIVIDUAL, SET, criterion_name
from .verify import quote_in

DOMAINS_DIR = Path(__file__).parent / "domains"
SEVERITIES = ("critical", "major", "minor")
FIELDS = {"id", "title", "severity", "criterion", "scope", "when", "require", "forbid", "message", "fix", "reference",
          "enabled", "reason"}
ORDER = {"critical": 0, "major": 1, "minor": 2}


class RulesError(ValueError):
    """Ошибка файла правил: сообщение по-русски, без трейсбека (review.py печатает его и выходит с кодом 2)."""


@dataclass
class BankRule:
    id: str
    title: str
    severity: str
    criterion: str
    message: str
    fix: str
    scope: str = "requirement"
    when_text: list = field(default_factory=list)  # скомпилированные регулярки (любая подходит)
    when_section: list = field(default_factory=list)
    require: list = field(default_factory=list)
    require_mode: str = "any"
    forbid: list = field(default_factory=list)
    reference: str = ""
    enabled: bool = True
    reason: str = ""


@dataclass
class RuleSet:
    name: str
    path: str
    rules: list[BankRule]
    disclaimer: str = ""


def resolve(spec: str) -> Path:
    """«fintech» → req_review/domains/fintech.rules.yaml; иначе путь к файлу."""
    p = Path(spec)
    if p.suffix in (".yaml", ".yml") or p.exists():
        return p
    return DOMAINS_DIR / f"{spec}.rules.yaml"


def _patterns(rid: str, key: str, value) -> list:
    if value is None:
        return []
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not all(isinstance(x, str) and x.strip() for x in items):
        raise RulesError(f"правило {rid}: поле «{key}» — строка или список непустых строк (регулярок)")
    out = []
    for x in items:
        try:
            out.append(re.compile(x, re.I))
        except re.error as e:
            raise RulesError(f"правило {rid}: битая регулярка в «{key}»: «{x}» ({e})") from None
    return out


def _rule(i: int, d) -> BankRule:
    if not isinstance(d, dict):
        raise RulesError(f"правило №{i}: ожидается словарь с полями id, title, severity, criterion, message, fix")
    rid = str(d.get("id") or f"№{i}")
    miss = [k for k in ("id", "title", "severity", "criterion", "message", "fix") if not str(d.get(k) or "").strip()]
    if miss:
        raise RulesError(f"правило {rid}: не заполнены поля: {', '.join(miss)}")
    unknown = sorted(set(d) - FIELDS)
    if unknown:
        raise RulesError(f"правило {rid}: неизвестные поля: {', '.join(unknown)} (допустимы: {', '.join(sorted(FIELDS))})")
    if d["severity"] not in SEVERITIES:
        raise RulesError(f"правило {rid}: severity «{d['severity']}» — допустимы {', '.join(SEVERITIES)}")
    if d["criterion"] not in INDIVIDUAL and d["criterion"] not in SET:
        raise RulesError(f"правило {rid}: неизвестный критерий «{d['criterion']}» — допустимы "
                         f"{', '.join(list(INDIVIDUAL) + list(SET))}")
    scope = d.get("scope", "requirement")
    if scope not in ("requirement", "document"):
        raise RulesError(f"правило {rid}: scope «{scope}» — допустимы requirement, document")
    when = d.get("when")
    if isinstance(when, (str, list)):
        when = {"text": when}
    if when is not None and (not isinstance(when, dict) or set(when) - {"text", "section"}):
        raise RulesError(f"правило {rid}: «when» — регулярка или словарь {{text, section}}")
    when = when or {}
    req = d.get("require")
    mode = "any"
    if isinstance(req, dict):
        if len(req) != 1 or next(iter(req)) not in ("any", "all"):
            raise RulesError(f"правило {rid}: «require» — список регулярок или {{any: [...]}} / {{all: [...]}}")
        mode, req = next(iter(req.items()))
    r = BankRule(id=rid, title=str(d["title"]), severity=d["severity"], criterion=d["criterion"],
                 message=str(d["message"]).strip(), fix=str(d["fix"]).strip(), scope=scope,
                 when_text=_patterns(rid, "when.text", when.get("text")),
                 when_section=_patterns(rid, "when.section", when.get("section")),
                 require=_patterns(rid, "require", req), require_mode=mode,
                 forbid=_patterns(rid, "forbid", d.get("forbid")), reference=str(d.get("reference") or ""),
                 enabled=d.get("enabled", True) is not False, reason=str(d.get("reason") or ""))
    if not r.require and not r.forbid:
        raise RulesError(f"правило {rid}: нужно хотя бы одно из полей «require» или «forbid»")
    if r.scope == "document" and r.forbid:
        raise RulesError(f"правило {rid}: «forbid» проверяется в тексте требования — используйте scope: requirement")
    if not r.enabled and not r.reason:
        raise RulesError(f"правило {rid}: выключено (enabled: false) — укажите причину в поле «reason»")
    return r


def load_rules(spec: str) -> RuleSet:
    path = resolve(spec)
    if not path.exists():
        raise RulesError(f"файл правил не найден: {path} (встроенные наборы: "
                         f"{', '.join(p.name.split('.')[0] for p in DOMAINS_DIR.glob('*.rules.yaml')) or 'нет'})")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f", строка {mark.line + 1}" if mark else ""
        raise RulesError(f"файл правил {path.name}: ошибка YAML{where}: {getattr(e, 'problem', None) or e}") from None
    if isinstance(data, list):
        data = {"rules": data}
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list) or not data["rules"]:
        raise RulesError(f"файл правил {path.name}: нужен список правил (ключ «rules»)")
    rules = [_rule(i, d) for i, d in enumerate(data["rules"], 1)]
    ids = [r.id for r in rules]
    dup = sorted({x for x in ids if ids.count(x) > 1})
    if dup:
        raise RulesError(f"файл правил {path.name}: повторяются id: {', '.join(dup)}")
    return RuleSet(name=str(data.get("name") or path.stem), path=str(path), rules=rules,
                   disclaimer=str(data.get("disclaimer") or "").strip())


def rules_spec(opts_rules: str = "") -> str:
    return opts_rules or os.getenv("REQLENS_RULES", "")


# ---------------------------------------------------------------- применение


def _quote(text: str, a: int, b: int, width: int = 25) -> str:
    """Дословный фрагмент текста вокруг совпадения [a, b): по границам слов, до ~width символов с каждой стороны."""
    lo, hi = max(0, a - width), min(len(text), b + width)
    while lo > 0 and not text[lo - 1].isspace() and lo > a - width - 15:
        lo -= 1
    while hi < len(text) and not text[hi].isspace() and hi < b + width + 15:
        hi += 1
    q = " ".join(text[lo:hi].split()).strip(" ,;:")
    q = re.sub(r"^\W*\*\*[^*]*\*\*\s*", "", q) or q  # без «**Ф-1.**» в начале цитаты
    return q.strip("*").strip()


def _applies(rule: BankRule, req) -> re.Match | None | bool:
    if rule.when_section and not any(p.search(req.section or "") for p in rule.when_section):
        return None
    if rule.when_text:
        for p in rule.when_text:
            m = p.search(req.text)
            if m:
                return m
        return None
    return True


def _satisfied(rule: BankRule, text: str) -> bool:
    if not rule.require:
        return True
    hits = [bool(p.search(text)) for p in rule.require]
    return all(hits) if rule.require_mode == "all" else any(hits)


def _fallback_quote(req) -> str:
    t = " ".join(req.text.split())
    t = re.sub(r"^\W*\*\*[^*]*\*\*\s*", "", t)
    return t[:60].rsplit(" ", 1)[0] if len(t) > 60 else t


def apply_rules(rv, ruleset: RuleSet, log=print) -> dict:
    """Добавляет замечания по правилам банка к требованиям (scope requirement) и к набору (scope document).

    Совпадение с уже найденным замечанием того же критерия на ту же цитату не дублируется: к источнику найденного
    замечания добавляется «+ правило банка: <id>». Возвращает сводку для отчёта и report.json (поле bank_rules)."""
    from .checker import Finding, SetFinding, SetRef

    doc_text = "\n".join(line.text for line in rv.doc.lines)
    reqs = [rr for rr in rv.req_results if getattr(rr.req, "kind", "requirement") == "requirement"]
    rows = []
    for rule in ruleset.rules:
        row = {"id": rule.id, "title": rule.title, "severity": rule.severity, "criterion": rule.criterion,
               "criterion_name": criterion_name(rule.criterion), "scope": rule.scope, "reference": rule.reference,
               "applicable": 0, "hits": 0, "status": "not_applicable", "where": []}
        if not rule.enabled:
            row.update(status="disabled", reason=rule.reason)
            rows.append(row)
            continue
        source = f"правило банка: {rule.id}"
        fix = rule.fix + (f" (основание: {rule.reference})" if rule.reference else "")
        applicable = [(rr, m) for rr in reqs if (m := _applies(rule, rr.req))]
        row["applicable"] = len(applicable)
        if rule.scope == "document":
            if applicable and not _satisfied(rule, doc_text):
                refs = []
                for rr, m in applicable[:3]:
                    q = _quote(rr.req.text, m.start(), m.end()) if isinstance(m, re.Match) else _fallback_quote(rr.req)
                    if quote_in(q, rr.req.text):
                        refs.append(SetRef(rr.req.rid, q))
                if refs:
                    rv.set_findings.append(SetFinding("bank_rule", rule.criterion, refs, f"{rule.title}: {rule.message}",
                                                      rule.severity, fix, source, confidence="high"))
                    row["hits"] = 1
                    row["where"] = [r.req_id for r in refs]
        else:
            for rr, m in applicable:
                quotes = []
                for p in rule.forbid:
                    fm = p.search(rr.req.text)
                    if fm:
                        quotes.append(_quote(rr.req.text, fm.start(), fm.end(), width=12))
                if not quotes and not _satisfied(rule, rr.req.text):
                    quotes.append(_quote(rr.req.text, m.start(), m.end()) if isinstance(m, re.Match)
                                  else _fallback_quote(rr.req))
                for q in quotes[:1]:
                    if not q or not quote_in(q, rr.req.text):  # дословность — как у замечаний модели
                        continue
                    twin = next((f for f in rr.findings if f.criterion == rule.criterion
                                 and (quote_in(q, f.quote) or quote_in(f.quote, q))), None)
                    if twin is not None:
                        if source not in twin.source:
                            twin.source += f" + {source}"
                        if ORDER[rule.severity] < ORDER.get(twin.severity, 2):
                            twin.severity = rule.severity
                    else:
                        rr.findings.append(Finding(rr.req.rid, rule.criterion, q, f"{rule.title}: {rule.message}",
                                                   rule.severity, fix, source, confidence="high"))
                    row["hits"] += 1
                    row["where"].append(rr.req.rid)
        if row["applicable"]:
            row["status"] = "fired" if row["hits"] else "passed"
        rows.append(row)
    st = {"name": ruleset.name, "file": Path(ruleset.path).name, "disclaimer": ruleset.disclaimer,
          "total": len(ruleset.rules), "enabled": sum(1 for r in ruleset.rules if r.enabled),
          "fired": sum(1 for r in rows if r["status"] == "fired"),
          "passed": sum(1 for r in rows if r["status"] == "passed"),
          "not_applicable": sum(1 for r in rows if r["status"] == "not_applicable"),
          "disabled": sum(1 for r in rows if r["status"] == "disabled"),
          "findings": sum(r["hits"] for r in rows), "rules": rows}
    log(f"  чек-лист банка «{st['name']}»: правил {st['total']}, сработало {st['fired']}, замечаний {st['findings']}")
    return st
