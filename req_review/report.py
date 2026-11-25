"""Формирование отчёта о проверке на русском языке (Markdown)."""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from .checker import ReviewResult
from .criteria import INDIVIDUAL, SET, SEVERITY, criterion_name, criterion_ref

ICON = {"critical": "🔴", "major": "🟠", "minor": "🟡"}
KIND = {
    "contradiction": "Противоречие", "duplicate": "Дублирование", "terminology": "Терминология",
    "gap": "Пропуск", "dependency": "Зависимость/ссылка", "structure": "Структура/трассируемость", "other": "Прочее",
}
CRITICAL_CRITERIA = {"verifiable", "complete", "set_consistent", "set_complete"}


def _cell(s: str) -> str:
    return " ".join(str(s).replace("|", "\\|").split())


def _q(s: str) -> str:
    return "«" + _cell(s) + "»"


def build_report(rv: ReviewResult, *, model_label: str, agent_version: str, started: datetime,
                 duration_s: float, llm_stats, input_path: str) -> str:
    doc, split = rv.doc, rv.split
    reqs = split.requirements
    by_rid = {r.rid: r for r in reqs}
    L: list[str] = []
    w = L.append

    all_f = [f for rr in rv.req_results for f in rr.findings]
    sev_counts = Counter(f.severity for f in all_f) + Counter(f.severity for f in rv.set_findings)
    total_viol = len(all_f) + len(rv.set_findings)
    reqs_with_issues = [rr for rr in rv.req_results if rr.findings]
    critical_items = [f for f in all_f if f.severity == "critical"]
    set_critical = [f for f in rv.set_findings if f.severity == "critical"]

    w(f"# Отчёт о проверке требований: {doc.title}")
    w("")
    if "mock" in model_label:
        w("> ⚠️ **ТЕСТОВЫЙ ПРОГОН (LLM_PROVIDER=mock).** Модель не вызывалась, замечания сгенерированы эвристиками. "
          "Этот отчёт не является результатом проверки и не подходит для сдачи.")
        w("")

    # ------------------------------------------------------------------ 1
    w("## 1. Паспорт прогона")
    w("")
    w("| Параметр | Значение |")
    w("|---|---|")
    w(f"| Документ | {_cell(doc.title)} |")
    w(f"| Файл | `{_cell(input_path)}` ({doc.fmt.upper()}{f', {doc.pages} стр.' if doc.pages else ''}) |")
    w(f"| SHA-256 файла | `{doc.sha256[:16]}…` |")
    w(f"| Дата и время прогона | {started.strftime('%Y-%m-%d %H:%M:%S %Z').strip()} |")
    w(f"| Модель | {_cell(model_label)} |")
    w(f"| Версия агента | {_cell(agent_version)} |")
    w(f"| Обращений к модели | {llm_stats.calls} (повторов: {llm_stats.retries}) |")
    if llm_stats.prompt_tokens:
        w(f"| Токены (вход / выход) | {llm_stats.prompt_tokens} / {llm_stats.output_tokens} |")
    w(f"| Длительность | {duration_s:.0f} с |")
    method = {"ids": "по идентификаторам документа", "modal": "по модальным формулировкам (номера присвоены агентом)",
              "llm": "моделью (номера присвоены агентом)"}[split.method]
    w(f"| Способ нарезки | {method} |")
    w(f"| Отброшено неподтверждённых цитат модели | {len(rv.dropped)} |")
    w("| Критерии | ISO/IEC/IEEE 29148:2018 п. 5.2.5, 5.2.6; IEEE Std 830-1998 п. 4.3 |")
    w("")
    for warn in doc.warnings + rv.notes:
        w(f"> ⚠️ {warn}")
        w("")
    w("Обозначения серьёзности: 🔴 критичный — требование непроверяемо, противоречиво или неполно настолько, что "
      "реализация и тестирование невозможны; 🟠 существенный; 🟡 незначительный. "
      "Источник «LLM» — замечание модели с проверенной цитатой; «правило» — словарный пред-фильтр агента.")
    w("")

    # ------------------------------------------------------------------ 2
    w("## 2. Нарезка требований")
    w("")
    if split.method != "ids":
        w("В документе нет идентификаторов требований — агент присвоил свои номера; в таблице сохранена полная цитата.")
        w("")
    w("| ID в отчёте | ID в документе | Место в документе | Краткая формулировка |")
    w("|---|---|---|---|")
    for r in reqs:
        text = _cell(r.text) if not r.doc_id else _cell(r.short)
        w(f"| {r.rid} | {_cell(r.doc_id) if r.doc_id else '— (присвоен агентом)'} | {_cell(r.location)} | {text} |")
    w("")
    w(f"Всего выделено требований: **{len(reqs)}**.")
    w("")

    # ------------------------------------------------------------------ 3
    w("## 3. Проверка каждого требования")
    w("")
    for rr in rv.req_results:
        r = rr.req
        worst = min((f.severity for f in rr.findings), key=lambda s: {"critical": 0, "major": 1, "minor": 2}[s], default=None)
        status = {"critical": "🔴 есть критичные дефекты", "major": "🟠 требует доработки",
                  "minor": "🟡 мелкие замечания", None: "✅ замечаний нет"}[worst]
        w(f"### {r.rid}{f' ({r.doc_id})' if r.doc_id else ''} — {status}")
        w("")
        w(f"*Место:* {r.location}")
        w("")
        w(f"> {_cell(r.text)}")
        w("")
        if rr.note:
            w(f"⚠️ {rr.note}")
            w("")
        if rr.findings:
            w("| № | Критерий | Цитата | Проблема | Серьёзность | Как исправить | Источник |")
            w("|---|---|---|---|---|---|---|")
            for i, f in enumerate(rr.findings, 1):
                w(f"| {i} | {criterion_name(f.criterion)} | {_q(f.quote)} | {_cell(f.problem)} | "
                  f"{ICON[f.severity]} {SEVERITY[f.severity]} | {_cell(f.fix)} | {f.source} |")
            w("")
        bad = {f.criterion for f in rr.findings}
        ok = [v[0] for k, v in INDIVIDUAL.items() if k not in bad]
        if rr.llm_checked:
            w(f"Без замечаний по критериям: {', '.join(ok)}.")
            w("")
        if rr.rewrite and rr.findings:
            w(f"**Предлагаемая формулировка:** {_cell(rr.rewrite)}")
            w("")

    # ------------------------------------------------------------------ 4
    w("## 4. Проверка набора требований")
    w("")
    if not rv.set_llm_checked:
        w("⚠️ Модель не ответила на запрос проверки набора; ниже только детерминированные проверки агента.")
        w("")
    w("| Критерий набора | Источник | Замечаний | Статус |")
    w("|---|---|---|---|")
    for k, v in SET.items():
        fs = [f for f in rv.set_findings if f.criterion == k]
        worst = min((f.severity for f in fs), key=lambda s: {"critical": 0, "major": 1, "minor": 2}[s], default=None)
        st = "✅ нарушений не найдено" if not fs else f"{ICON[worst]} {SEVERITY[worst].lower()}"
        w(f"| {v[0]} | {v[1]} | {len(fs)} | {st} |")
    w("")
    if rv.set_findings:
        for i, f in enumerate(rv.set_findings, 1):
            w(f"#### S-{i:02d}. {KIND.get(f.kind, f.kind.capitalize())} — {ICON[f.severity]} {SEVERITY[f.severity]} "
              f"({criterion_name(f.criterion)}; {criterion_ref(f.criterion)})")
            w("")
            for ref in f.refs:
                if ref.req_id in by_rid:
                    r = by_rid[ref.req_id]
                    w(f"- {ref.req_id}{f' ({r.doc_id})' if r.doc_id else ''}, {r.location}: {_q(ref.quote)}")
                else:
                    w(f"- Текст документа: {_q(ref.quote)}")
            w("")
            w(f"**Проблема:** {_cell(f.problem)}")
            w("")
            w(f"**Как исправить:** {_cell(f.fix)}")
            w("")
            w(f"*Источник: {f.source}*")
            w("")
    else:
        w("Нарушений на уровне набора не найдено.")
        w("")

    # ------------------------------------------------------------------ 5
    w("## 5. Сводка")
    w("")
    w("| Показатель | Значение |")
    w("|---|---|")
    w(f"| Требований выделено | {len(reqs)} |")
    w(f"| Требований без замечаний | {len(reqs) - len(reqs_with_issues)} |")
    w(f"| Требований с замечаниями | {len(reqs_with_issues)} |")
    w(f"| Нарушений всего | {total_viol} (по требованиям: {len(all_f)}, по набору: {len(rv.set_findings)}) |")
    for s in ("critical", "major", "minor"):
        w(f"| — {SEVERITY[s].lower()} | {sev_counts.get(s, 0)} |")
    w("")
    w("**Нарушения по критериям:**")
    w("")
    w("| Критерий | Нарушений | Требования |")
    w("|---|---|---|")
    crit_map: dict[str, list[str]] = {}
    for f in all_f:
        crit_map.setdefault(f.criterion, []).append(f.req_id)
    for k, ids in sorted(crit_map.items(), key=lambda x: -len(x[1])):
        uniq = sorted(set(ids))
        w(f"| {criterion_name(k)} | {len(ids)} | {', '.join(uniq)} |")
    for f in rv.set_findings:
        pass
    set_crit = Counter(f.criterion for f in rv.set_findings)
    for k, n in set_crit.items():
        w(f"| {criterion_name(k)} (набор) | {n} | — |")
    w("")
    w("**Критичные дефекты** (непроверяемые, противоречивые, неполные формулировки):")
    w("")
    if not critical_items and not set_critical:
        w("Критичных дефектов не найдено.")
    for f in critical_items:
        r = by_rid[f.req_id]
        w(f"- 🔴 **{f.req_id}{f' ({r.doc_id})' if r.doc_id else ''}** — {criterion_name(f.criterion)}: "
          f"{_q(f.quote)} — {_cell(f.problem)}")
    for i, f in enumerate(rv.set_findings, 1):
        if f.severity == "critical":
            ids = ", ".join(ref.req_id for ref in f.refs)
            w(f"- 🔴 **S-{i:02d}** ({KIND.get(f.kind, f.kind)}; {ids}) — {_cell(f.problem)}")
    w("")

    # ------------------------------------------------------------------ 6
    w("## 6. Итог")
    w("")
    n_crit = sev_counts.get("critical", 0)
    n_major = sev_counts.get("major", 0)
    blocked = {f.req_id for f in critical_items} | {ref.req_id for f in set_critical for ref in f.refs if ref.req_id in by_rid}
    ready = [rr.req.rid for rr in rv.req_results
             if rr.req.rid not in blocked and all(f.severity == "minor" for f in rr.findings)]
    if n_crit:
        w(f"**Вердикт: начинать разработку и тестирование по документу в текущем виде нельзя.** "
          f"Найдено {n_crit} критичных дефектов в {len(blocked)} требованиях — их невозможно однозначно реализовать "
          "или проверить, тест-кейсы и критерии приёмки по ним составить нельзя.")
    elif n_major:
        w("**Вердикт: условно можно.** Критичных дефектов нет, но существенные замечания нужно устранить до "
          "формирования тест-кейсов по затронутым требованиям.")
    else:
        w("**Вердикт: можно начинать разработку и тестирование.** Критичных и существенных дефектов не найдено.")
    w("")
    if ready and n_crit:
        w(f"Без критичных и существенных замечаний (можно брать в работу уже сейчас): {', '.join(ready)}.")
        w("")
    elif not ready and reqs:
        w("Ни одно требование не готово к работе без доработки.")
        w("")
    w("**Что исправить в первую очередь:**")
    w("")
    prio = _priorities(rv, by_rid)
    if not prio:
        w("Обязательных исправлений нет.")
    for i, p in enumerate(prio[:10], 1):
        w(f"{i}. {p}")
    w("")
    w("---")
    w("")
    w("### Приложение. Критерии проверки")
    w("")
    w("| Ключ | Критерий | Источник |")
    w("|---|---|---|")
    for k, v in list(INDIVIDUAL.items()) + list(SET.items()):
        w(f"| `{k}` | {v[0]} | {v[1]} |")
    w("")
    if rv.dropped:
        w(f"### Приложение. Отброшенные замечания модели ({len(rv.dropped)})")
        w("")
        w("Цитата не найдена в тексте документа — замечание считается галлюцинацией и в оценку не входит.")
        w("")
        w("| Где | Цитата модели | Суть |")
        w("|---|---|---|")
        for d in rv.dropped[:50]:
            w(f"| {_cell(d['where'])} | {_q(d['quote']) if d['quote'] else '—'} | {_cell(d['problem'])[:200]} |")
        w("")
    w(f"*Отчёт сформирован автоматически агентом req-review ({_cell(agent_version)}).*")
    return "\n".join(L) + "\n"


def _priorities(rv: ReviewResult, by_rid) -> list[str]:
    items: list[tuple[int, str]] = []
    for i, f in enumerate(rv.set_findings, 1):
        if f.severity in ("critical", "major"):
            ids = ", ".join(_label(ref.req_id, by_rid) for ref in f.refs)
            items.append(({"critical": 0, "major": 2}[f.severity],
                          f"{ICON[f.severity]} **S-{i:02d} ({KIND.get(f.kind, f.kind)}; {ids})**: {_cell(f.fix)}"))
    for rr in rv.req_results:
        crit = [f for f in rr.findings if f.severity == "critical"]
        major = [f for f in rr.findings if f.severity == "major"]
        chosen, rank = (crit, 1) if crit else (major, 3)
        if not chosen:
            continue
        f = chosen[0]
        more = f" (+ ещё {len(chosen) - 1})" if len(chosen) > 1 else ""
        items.append((rank, f"{ICON[f.severity]} **{_label(rr.req.rid, by_rid)}** — {criterion_name(f.criterion)}, "
                            f"{_q(f.quote)}: {_cell(f.fix)}{more}"))
    items.sort(key=lambda x: x[0])
    return [t for _, t in items]


def _label(rid: str, by_rid) -> str:
    if rid in by_rid and by_rid[rid].doc_id:
        return f"{rid} ({by_rid[rid].doc_id})"
    return rid if rid != "DOC" else "текст документа"
