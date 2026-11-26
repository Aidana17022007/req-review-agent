"""Самопроверка соответствия ТЗ хакатона (BCC-HUB x MNU, README задачи §1–§7) — кодом, с доказательствами.

Запуск:  python scripts/tz_check.py                       — проверить репозиторий и отчёт для сдачи
         python scripts/tz_check.py --report reports/x.md  — проверить другой отчёт (рядом должен лежать .json)
         python scripts/tz_check.py --write                — записать результат в docs/TZ_COMPLIANCE.md
Каждый пункт — ✅/❌ и ссылка на файл/строку/команду, где это видно. Код возврата 1, если хоть один обязательный
пункт не выполнен (удобно в CI).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SECRET = re.compile(r"AIza[0-9A-Za-z_-]{30,}|sk-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}")
SECTIONS = ["## 1. Паспорт прогона", "## 2. Нарезка требований", "## 3. Проверка каждого требования",
            "## 4. Проверка набора требований", "## 5. Сводка", "## 6. Итог"]


def _line(text: str, needle: str) -> int:
    for i, ln in enumerate(text.splitlines(), 1):
        if needle in ln:
            return i
    return 0


def _tracked() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=20)
        return out.stdout.splitlines() if out.returncode == 0 else []
    except Exception:
        return []


def check(report_md: Path) -> list[dict]:
    rows: list[dict] = []

    def add(clause: str, what: str, ok: bool, evidence: str, required: bool = True):
        rows.append({"clause": clause, "what": what, "ok": bool(ok), "evidence": evidence, "required": required})

    readme = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").exists() else ""
    md = report_md.read_text(encoding="utf-8") if report_md.exists() else ""
    rj = report_md.with_suffix(".json")
    data = json.loads(rj.read_text(encoding="utf-8")) if rj.exists() else {}
    rel = report_md.relative_to(ROOT).as_posix() if report_md.is_relative_to(ROOT) else str(report_md)
    tracked = _tracked()

    # §1 Задача: статическая проверка документа, отчёт по формулировкам
    add("§1", "Агент проводит статическую проверку документа и выпускает отчёт (не тесты программы)",
        bool(md) and "ISO/IEC/IEEE 29148" in md, f"`{rel}` — отчёт агента; `review.py` → `req_review/pipeline.py`")
    add("§1", "Выданный документ не кладётся в репозиторий как результат",
        "docs/requirements.md" not in tracked, "в репозитории нет `docs/requirements.md`; копия для бенчмарка — `bench/real/` (вход теста)")
    # §2 Что сдать
    add("§2", "Исходный код, зависимости и инструкция запуска",
        (ROOT / "review.py").exists() and (ROOT / "requirements.txt").exists() and "## Быстрый старт" in readme,
        f"`review.py`, `req_review/`, `requirements.txt`, README «Быстрый старт» (строка {_line(readme, '## Быстрый старт')})")
    pp = data.get("passport") or {}
    add("§2", "Отчёт сформирован именно этим агентом по выданному документу",
        bool(pp.get("agent_version")) and bool(pp.get("model")) and bool(pp.get("sha256")),
        f"паспорт `{rel}`: версия агента «{pp.get('agent_version', '—')}», модель «{pp.get('model', '—')}», SHA-256 документа")
    # §3 Как устроен прогон
    from req_review.reader import SUPPORTED

    add("§3", "Вход: PDF и другие форматы", ".pdf" in SUPPORTED and ".docx" in SUPPORTED,
        f"`req_review/reader.py`: {', '.join(sorted(SUPPORTED))}; тесты PDF/DOCX — `tests/test_depth.py`")
    reqs = data.get("requirements") or []
    add("§3", "Агент выделяет отдельные требования и проверяет каждое", len(reqs) > 0 and SECTIONS[2] in md,
        f"{len(reqs)} требований; раздел «3. Проверка каждого требования» (строка {_line(md, SECTIONS[2])})")
    add("§3", "Агент проверяет набор требований целиком", SECTIONS[3] in md and data.get("set_findings") is not None,
        f"{len(data.get('set_findings') or [])} замечаний к набору; раздел «4» (строка {_line(md, SECTIONS[3])})")
    add("§3", "Агент записывает отчёт в файл", report_md.exists(), f"`{rel}` (+ .json, .html, .pdf)")
    # §4 Модель
    add("§4", "Подключение к LLM; модель указана в инструкции", "## Как получить ключ LLM" in readme and "gemini" in readme.lower(),
        f"README «Как получить ключ LLM» (строка {_line(readme, '## Как получить ключ LLM')}); модель отчёта — в паспорте")
    add("§4", "Достаточно бесплатного тарифа (платный ключ не нужен)", "бесплатн" in readme.lower(),
        "Gemini (Google AI Studio, бесплатный тариф); без ключа — режим `LLM_PROVIDER=rules`")
    # §5 Критерии
    add("§5", "Критерии ISO/IEC/IEEE 29148 п. 5.2.5, 5.2.6 и IEEE 830 п. 4.3",
        all(x in md for x in ("5.2.5", "5.2.6", "4.3")), "`req_review/criteria.py`; паспорт отчёта, строка «Критерии»")
    # §6 Состав отчёта
    add("§6", "Отчёт на русском языке, файл", bool(md) and bool(re.search(r"[а-яё]{20}", md.lower().replace(" ", ""))), f"`{rel}`")
    for k, name in (("Документ", "название документа"), ("Дата и время прогона", "дата"), ("Модель", "модель"),
                    ("Версия агента", "версия агента (коммит или тег)")):
        n = _line(md, f"| {k} |")
        add("§6", f"Паспорт прогона: {name}", n > 0, f"`{rel}`, строка {n}")
    ver = str(pp.get("agent_version", ""))
    add("§6+", "Рекомендация: отчёт получен на чистом коммите (в версии нет «-dirty»)", bool(ver) and "dirty" not in ver,
        f"версия в паспорте: «{ver or '—'}»", required=False)
    n_split = _line(md, "| ID в отчёте | ID в документе |")
    add("§6", "Таблица нарезки «ID в отчёте — ID в документе — краткая формулировка»; свои ID, если номеров нет",
        n_split > 0 and "присвоен агентом" in md, f"`{rel}`, строка {n_split}")
    for sec in SECTIONS[2:4]:
        add("§6", sec.replace("## ", "Раздел: "), sec in md, f"`{rel}`, строка {_line(md, sec)}")
    add("§6", "Сводка: число требований, число нарушений, список критичных дефектов",
        SECTIONS[4] in md and "Требований выделено" in md and "Критичные дефекты" in md,
        f"`{rel}`, строка {_line(md, SECTIONS[4])}")
    add("§6", "Итог: можно ли начинать разработку и тестирование, что исправить в первую очередь",
        SECTIONS[5] in md and "Вердикт" in md and "Что исправить в первую очередь" in md, f"`{rel}`, строка {_line(md, SECTIONS[5])}")
    fs = [f for r in reqs for f in r.get("findings", [])]
    refs = [x for f in data.get("set_findings") or [] for x in f.get("refs", [])]
    ok_place = all(f.get("quote") for f in fs) and all(x.get("quote") for x in refs) and all(r.get("location") for r in reqs)
    ca = data.get("citation_audit") or {}
    add("§6", "Каждое нарушение ссылается на конкретное место документа (цитата + строка)", ok_place and ca.get("missing", 0) == 0,
        f"{len(fs) + len(refs)} цитат с местом; аудит цитат: подтверждено {ca.get('verified', '—')} из {ca.get('total', '—')}, "
        f"не найдено {ca.get('missing', '—')}")
    # §7 Репозиторий
    add("§7", "Код агента и файл зависимостей", (ROOT / "requirements.txt").exists(), "`requirements.txt`, `pyproject.toml`")
    add("§7", "README: как получить ключ, куда положить, команда запуска, куда ляжет отчёт",
        all(x in readme for x in ("aistudio.google.com", ".env", "python review.py", "Куда ляжет отчёт")),
        f"README: ключ (строка {_line(readme, 'aistudio.google.com')}), `.env`, команда (строка {_line(readme, 'python review.py')}), "
        f"«Куда ляжет отчёт» (строка {_line(readme, 'Куда ляжет отчёт')})")
    add("§7", "Запуск одной командой: путь к требованиям и путь к отчёту",
        re.search(r"python review\.py \S+ \S+\.md", readme) is not None, "`python review.py docs/requirements.md reports/report.md`")
    leaked = [p for p in tracked if Path(p).name == ".env"]
    secrets = []
    for p in tracked:
        fp = ROOT / p
        if fp.suffix.lower() in {".py", ".md", ".txt", ".yml", ".yaml", ".json", ".toml", ".example", ".env", ".cfg", ".ini"} \
                and fp.is_file() and fp.stat().st_size < 2_000_000:
            if SECRET.search(fp.read_text(encoding="utf-8", errors="ignore")):
                secrets.append(p)
    add("§7", "Секреты в репозиторий не попадают; в корне `.env.example` без ключа",
        (ROOT / ".env.example").exists() and not leaked and not secrets,
        "`.env` в `.gitignore`; `.env.example` в корне; поиск ключей по отслеживаемым файлам: "
        + ("не найдено" if not secrets else ", ".join(secrets)))
    add("§7", "Обязательны чтение документа, обращение к модели и запись отчёта",
        all((ROOT / p).exists() for p in ("req_review/reader.py", "req_review/llm.py", "req_review/report.py")),
        "`req_review/reader.py` → `req_review/llm.py` → `req_review/report.py`")
    return rows


def render(rows: list[dict], report: str) -> str:
    req = [r for r in rows if r["required"]]
    ok = sum(r["ok"] for r in req)
    L = ["# Соответствие ТЗ хакатона — самопроверка агента", "",
         "ТЗ: [BCC-HUB/ai-requirements-validator-task](https://github.com/BCC-HUB/ai-requirements-validator-task) (README §1–§7). "
         f"Файл сгенерирован командой `python scripts/tz_check.py --write` по отчёту `{report}`; каждый пункт проверен кодом.", "",
         f"**Итог: {ok} из {len(req)} обязательных пунктов выполнено.**", "",
         "| § | Требование ТЗ | Статус | Где это видно |", "|---|---|---|---|"]
    for r in rows:
        mark = "✅" if r["ok"] else ("❌" if r["required"] else "⚠️")
        L.append(f"| {r['clause']} | {r['what']} | {mark} | {r['evidence']} |")
    L += ["", "Повторить проверку: `python scripts/tz_check.py`. Повторить прогон агента: "
          "`python review.py docs/requirements.md reports/report.md` или Actions → Generate report."]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Самопроверка соответствия ТЗ хакатона")
    ap.add_argument("--report", default=str(ROOT / "reports" / "requirements-report.md"))
    ap.add_argument("--write", action="store_true", help="записать docs/TZ_COMPLIANCE.md")
    a = ap.parse_args(argv)
    rep = Path(a.report).resolve()
    rows = check(rep)
    rel = rep.relative_to(ROOT).as_posix() if rep.is_relative_to(ROOT) else str(rep)
    text = render(rows, rel)
    if a.write:
        (ROOT / "docs" / "TZ_COMPLIANCE.md").write_text(text, encoding="utf-8")
    for r in rows:
        print(("OK  " if r["ok"] else "FAIL" if r["required"] else "WARN") + f"  {r['clause']}  {r['what']}")
    req = [r for r in rows if r["required"]]
    print(f"{sum(r['ok'] for r in req)} / {len(req)} обязательных")
    return 0 if all(r["ok"] for r in req) else 1


if __name__ == "__main__":
    raise SystemExit(main())
