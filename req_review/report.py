"""Формирование отчёта о проверке на русском языке (Markdown)."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime

from .checker import ReviewResult
from .criteria import INDIVIDUAL, SET, SEVERITY, criterion_name, criterion_ref
from .scoring import METHOD_MD, bar

EARS = {"ubiquitous": "постоянное", "event": "по событию", "state": "по состоянию", "unwanted": "нежелательное поведение",
        "optional": "опциональная функция", "complex": "составное"}

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
                 duration_s: float, llm_stats, input_path: str, ctx=None) -> str:
    sc = ctx.scores if ctx is not None else None
    doc, split = rv.doc, rv.split
    reqs = split.requirements
    by_rid = {r.rid: r for r in reqs}
    L: list[str] = []
    w = L.append
    _BASIS_SEEN.clear()

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

    _summary_30s(w, rv, sev_counts, by_rid)

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
    if ctx is not None and ctx.passport.get("model_switches"):
        w(f"| Переключения модели | {_cell('; '.join(ctx.passport['model_switches']))} |")
    w(f"| Версия агента | {_cell(agent_version)} |")
    cached = getattr(llm_stats, "cached", 0)
    w(f"| Обращений к модели | {llm_stats.calls} (повторов: {llm_stats.retries}"
      + (f", из кэша: {cached}" if cached else "") + ") |")
    if ctx is not None:
        w(f"| Профиль / режим | {ctx.passport['profile']} / {ctx.passport['mode']} |")
        cx, rg = ctx.passport.get("context") or {}, ctx.passport.get("rag") or {}
        if cx:
            w(f"| Контекст запросов | {cx['mode']} · ≈{cx['avg_prompt_tokens']} токенов на запрос (документ {cx['doc_chars']} симв.) |")
        if rg.get("kb_chunks"):
            w(f"| База знаний (RAG) | {rg['kb_chunks']} фрагментов · поиск: {rg['search']} · основания у {rg['basis']} замечаний |")
        w(f"| Критик-агент | {'включён' if rv.critic_used else 'выключен (профиль fast)'} |")
        w(f"| **Балл документа** | **{sc.doc_score} / 100** `{bar(sc.doc_score)}` |")
        w(f"| **Готовность к разработке** | **{sc.readiness} %** `{bar(sc.readiness)}` |")
    if llm_stats.prompt_tokens:
        w(f"| Токены (вход / выход) | {llm_stats.prompt_tokens} / {llm_stats.output_tokens} |")
    w(f"| Длительность | {duration_s:.0f} с |")
    method = {"ids": "по идентификаторам документа", "modal": "по модальным формулировкам (номера присвоены агентом)",
              "llm": "моделью (номера присвоены агентом)"}[split.method]
    w(f"| Способ нарезки | {method} |")
    w(f"| Отброшено неподтверждённых цитат модели | {len(rv.dropped)} |")
    dp = getattr(rv, "depth", None) or {}
    if dp.get("line_coverage"):
        lc = dp["line_coverage"]
        w(f"| Учтено строк документа | {lc['accounted']} из {lc['total']} ({lc['percent']} %) — в требованиях или исключены с причиной |")
    if dp.get("review_stats"):
        st = dp["review_stats"]
        w(f"| Самопроверка | предложено {st['proposed']}, подтверждено {st['confirmed']}, отклонено критиком {st['rejected']}, "
          f"без подтверждённой цитаты {st['unconfirmed_quotes']} |")
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
        text = _cell(r.short)  # полный текст — один раз, в разборе требования (раздел 3)
        w(f"| {r.rid} | {_cell(r.doc_id) if r.doc_id else '— (присвоен агентом)'} | {_cell(r.location)} | {text} |")
    w("")
    w(f"Всего выделено требований: **{len(reqs)}**.")
    w("")

    # ------------------------------------------------------------------ 3
    w("## 3. Проверка каждого требования")
    w("")
    order = {"critical": 0, "major": 1, "minor": 2}
    worst_of = lambda rr: min((f.severity for f in rr.findings), key=order.get, default=None)  # noqa: E731
    full = [rr for rr in rv.req_results if worst_of(rr) in ("critical", "major")]
    minor_only = [rr for rr in rv.req_results if worst_of(rr) == "minor"]
    clean = [rr for rr in rv.req_results if not rr.findings]
    w(f"Подробный разбор — у требований с критичными и существенными замечаниями ({len(full)}). Требования только с мелкими "
      f"замечаниями ({len(minor_only)}) — в таблице ниже, без замечаний ({len(clean)}) — списком. Полный текст каждого "
      "требования приведён один раз — в его разборе; приёмочные тесты — в приложении «Тест-пробы».")
    w("")
    for rr in full:
        r = rr.req
        status = {"critical": "🔴 есть критичные дефекты", "major": "🟠 требует доработки"}[worst_of(rr)]
        w(f'<a id="{_anchor(r.rid)}"></a>')
        w("")
        w(f"### {r.rid}{f' ({r.doc_id})' if r.doc_id else ''} — {status}")
        w("")
        meta = f"*Место:* {r.location}"
        if sc is not None:
            meta += f" · *Балл:* `{bar(sc.req[r.rid])}`"
        if rr.ears:
            meta += f" · *Тип (EARS):* {EARS.get(rr.ears, rr.ears)}"
        w(meta)
        w("")
        w(f"> {_cell(r.text)}")
        w("")
        if rr.note:
            w(f"⚠️ {rr.note}")
            w("")
        w("| № | Критерий | Цитата | Проблема | Серьёзность | Как исправить | Источник |")
        w("|---|---|---|---|---|---|---|")
        for i, f in enumerate(rr.findings, 1):
            w(f"| {i} | {criterion_name(f.criterion)} | {_q(f.quote)} | {_cell(f.problem)} | "
              f"{ICON[f.severity]} {SEVERITY[f.severity]} | {_cell(f.fix)} | {f.source} |")
        w("")
        _basis_lines(w, rr.findings)
        if rr.rewrite:
            w(f"**Предлагаемая формулировка:** {_cell(rr.rewrite)}")
            w("")
            if getattr(rr, "rewrite_pattern", None):
                p = rr.rewrite_pattern
                w(f"*Шаблон из базы знаний ({_cell(p['title'])}, `{p['file']}`):* {_cell(p['template'])}")
                w("")
        if rr.test_possible is False:
            w(f"🧪 **Тест-проба: тест составить невозможно** — {_cell(rr.test_reason)} Мешает фрагмент: {_q(rr.test_blocker)}.")
            w("")
    if minor_only:
        w("### Требования с мелкими замечаниями")
        w("")
        w("| Требование | Критерий | Цитата | Проблема | Как исправить | Источник |")
        w("|---|---|---|---|---|---|")
        for rr in minor_only:
            r = rr.req
            for i, f in enumerate(rr.findings):
                head = f'<a id="{_anchor(r.rid)}"></a>{r.rid}{f" ({_cell(r.doc_id)})" if r.doc_id else ""}' if i == 0 else "″"
                w(f"| {head} | {criterion_name(f.criterion)} | {_q(f.quote)} | {_cell(f.problem)} | {_cell(f.fix)} | {f.source} |")
        w("")
    if clean:
        w("### Требования без замечаний")
        w("")
        w(", ".join(f'<a id="{_anchor(rr.req.rid)}"></a>{rr.req.rid}{f" ({_cell(rr.req.doc_id)})" if rr.req.doc_id else ""}'
                    for rr in clean) + " — нарушений критериев не найдено" + (" (проверены моделью и правилами)." if any(
                        rr.llm_checked for rr in clean) else " (проверены правилами)."))
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
            w(f'<a id="s-{i:02d}"></a>')
            w("")
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
            if getattr(f, "values", None):
                parts = []
                for v in f.values:
                    rq = by_rid.get(v["rid"])
                    name = v["rid"] + (f" ({rq.doc_id})" if rq is not None and rq.doc_id else "")
                    parts.append(f"{name} — «{_cell(v['value'])}»")
                vs = " vs ".join(parts)
                w(f"**Конфликтующие значения:** {vs}")
                w("")
            w(f"**Проблема:** {_cell(f.problem)}")
            w("")
            w(f"**Как исправить:** {_cell(f.fix)}")
            w("")
            _basis_lines(w, [f])
            w("")
            w(f"*Источник: {f.source}*")
            w("")
    else:
        w("Нарушений на уровне набора не найдено.")
        w("")

    if rv.domain:
        d = rv.domain
        w(f"### Доменная полнота: {d.name} — покрытие {d.coverage_pct} %")
        w("")
        w(f"*{_cell(d.disclaimer)}*")
        w("")
        w("| Область | Статус | Основание (цитата документа) |")
        w("|---|---|---|")
        st = {"covered": "✅ покрыта", "partial": "🟡 частично", "missing": "🔴 не покрыта"}
        for a in d.areas:
            w(f"| {a.title} | {st[a.status]} | {'; '.join(_q(q) for q in a.quotes) or '—'} |")
        w("")
    if rv.glossary and (rv.glossary.terms or rv.glossary.synonyms):
        w("### Глоссарий и согласованность терминов")
        w("")
        for syn in rv.glossary.synonyms:
            w(f"- ⚠️ Разнобой терминов: {', '.join(_q(t) for t in syn['terms'])} → рекомендуется «{_cell(syn['preferred'])}».")
        if rv.glossary.synonyms:
            w("")
        w("| Термин | Определён в документе | Упоминаний в требованиях |")
        w("|---|---|---|")
        for t in rv.glossary.terms[:20]:
            w(f"| {_cell(t.term)} | {'да' if t.defined else 'нет'} | {t.count} |")
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
    if sc is not None:
        w(f"| **Балл документа** | **{sc.doc_score} / 100** (балл набора — {sc.set_score}) |")
        w(f"| **Готовность к разработке** | **{sc.readiness} %** ({len(sc.ready_ids)} из {len(reqs)} требований без критичных и существенных замечаний, "
          "в том числе к набору) |")
        if sc.tests_total:
            w(f"| Покрыто тест-пробой | {sc.tests_ok} из {sc.tests_total} требований ({round(100 * sc.tests_ok / sc.tests_total)} %) |")
        acc = (getattr(rv, "depth", None) or {}).get("acceptance_coverage") or {}
        if acc.get("percent") is not None:
            unc = ", ".join(u["doc_id"] or u["rid"] for u in acc["uncovered"][:10])
            w(f"| Покрытие правил критериями приёмки | {acc['percent']} % ({len(acc['covered'])} из "
              f"{len(acc['covered']) + len(acc['uncovered'])}){'; без примеров: ' + unc if unc else ''} |")
        if rv.rejected:
            w(f"| Отклонено критиком | {len(rv.rejected)} |")
        w("")
        w("**Профиль качества по критериям** (доля требований без нарушений):")
        w("")
        w("| Критерий | Профиль |")
        w("|---|---|")
        for k, v in sc.radar_req.items():
            w(f"| {INDIVIDUAL[k][0]} | `{bar(v)}` |")
        w("")
    if getattr(rv, "categories", None):
        from .categories import CATEGORIES

        w("**Требования по категориям:** " + " · ".join(f"{CATEGORIES.get(k, k)} — {v}" for k, v in
                                                       sorted(rv.categories.items(), key=lambda x: -x[1])))
        w("")
    if getattr(rv, "coverage", None):
        w("**Покрытие типового процесса:**")
        w("")
        w("| Шаг процесса | Покрыт | Требования |")
        w("|---|---|---|")
        for s in rv.coverage:
            w(f"| {s['title']} | {'✅ да' if s['covered'] else '🔴 нет'} | {', '.join(s['reqs'][:8]) or '—'} |")
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
    ready = list(sc.ready_ids) if sc is not None else [rr.req.rid for rr in rv.req_results
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
    vd = (getattr(rv, "depth", None) or {}).get("verdict")
    if vd:
        icon = {"нельзя": "❌", "с оговорками": "⚠️", "можно": "✅"}
        w("| Разработка | Тестирование |")
        w("|---|---|")
        w(f"| {icon[vd['development']]} {vd['development']} | {icon[vd['testing']]} {vd['testing']} |")
        w("")
        w(f"*Правило:* {vd['rule']}")
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
    plan = [it for it in (getattr(rv, "depth", None) or {}).get("fix_plan", []) if it.get("example")]
    if plan:
        w("**Как переписать (пример правильной формулировки):**")
        w("")
        w("| Пункт | Пример | Источник |")
        w("|---|---|---|")
        for it in plan:
            w(f"| {_cell(', '.join(it['ids'][:4]))}: {_cell(it['title'][:90])} | {_cell(it['example'][:300])} | {it['example_source']} |")
        w("")
    if ctx is not None:
        _extras_tail(w, ctx)
    lc = (getattr(rv, "depth", None) or {}).get("line_coverage")
    if lc:
        w("### Приложение. Учёт строк документа")
        w("")
        w(f"Непустых строк: {lc['total']}; в требованиях: {lc['requirements']}; учтено всего: {lc['accounted']} ({lc['percent']} %).")
        if lc.get("recovered"):
            w(f"Дорезка: из {lc.get('uncovered_before_recovery', 0)} строк вне нарезки модель выделила требований — "
              f"{lc['recovered']}; они проверены вместе с остальными.")
        w("")
        w("| Причина исключения | Строк |")
        w("|---|---|")
        for e in lc["excluded"]:
            w(f"| {e['reason']} | {e['lines']} |")
        w("")
        for u in lc.get("unnumbered", []):
            w(f"- строка {u['line']}: утверждение без идентификатора — «{_cell(u['text'][:120])}»")
        for u in lc["uncovered"]:
            w(f"- ⚠️ строка {u['line']} не учтена: «{_cell(u['text'][:120])}»")
        if lc.get("unnumbered") or lc["uncovered"]:
            w("")
    w("---")
    w("")
    _tests_appendix(w, rv)
    _basis_appendix(w)
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
    if rv.rejected:
        w(f"### Приложение. Замечания, отклонённые критиком ({len(rv.rejected)})")
        w("")
        w("| Где | Цитата | Суть | Причина отклонения |")
        w("|---|---|---|---|")
        for d in rv.rejected[:50]:
            qq = _q(d["quote"]) if d["quote"] else "—"
            w(f"| {_cell(d['where'])} | {qq} | {_cell(d['problem'])[:160]} | {_cell(d['reason'])[:160]} |")
        w("")
    if ctx is not None:
        w("### Приложение. Методика оценки")
        w("")
        w(METHOD_MD)
        w("")
    w(f"*Отчёт сформирован автоматически агентом ReqLens / req-review ({_cell(agent_version)}).*")
    return "\n".join(L) + "\n"


SUMMARY_START, SUMMARY_END = "<!-- reqlens:summary:start -->", "<!-- reqlens:summary:end -->"


def _anchor(rid: str) -> str:
    """Якорь требования или замечания набора: R-006 → r-006, S-02 → s-02 (ссылки вида [R-006](#r-006))."""
    return rid.lower()


def _link(i: str) -> str:
    return f"[{i}](#{_anchor(i)})" if re.match(r"^[RS]-\d+$", i) else i


def _summary_30s(w, rv: ReviewResult, sev_counts, by_rid) -> None:
    """«Итог за 30 секунд»: вердикты, число дефектов по серьёзности и 5–8 пунктов «что исправить первым» со ссылками
    на разборы и примером правильной формулировки."""
    depth = getattr(rv, "depth", None) or {}
    vd, plan = depth.get("verdict"), depth.get("fix_plan") or []
    w(SUMMARY_START)
    w("")
    w("**Итог за 30 секунд**")
    w("")
    if vd:
        icon = {"нельзя": "❌", "с оговорками": "⚠️", "можно": "✅"}
        w("| Разработка | Тестирование | 🔴 Критичных | 🟠 Существенных | 🟡 Незначительных |")
        w("|---|---|---|---|---|")
        w(f"| {icon[vd['development']]} {vd['development']} | {icon[vd['testing']]} {vd['testing']} | "
          f"{sev_counts.get('critical', 0)} | {sev_counts.get('major', 0)} | {sev_counts.get('minor', 0)} |")
        w("")
    if plan:
        w("**Что исправить первым:**")
        w("")
        for n, it in enumerate(plan[:8], 1):
            ids = ", ".join(_link(i) for i in it["ids"][:4]) + (" …" if len(it["ids"]) > 4 else "")
            title = re.sub(rf"^{re.escape(it['ids'][0])}:\s*", "", it["title"]) if it["ids"] else it["title"]
            line = f"{n}. {ICON[it['severity']]} {ids} — {_cell(title)}"
            if it.get("example"):
                line += f" *Пример:* «{_cell(it['example'][:220])}»"
            w(line)
        w("")
    w("Подробности: разделы 3–4 (разбор по каждому требованию и набору), раздел 6 (итог и план), приложения.")
    w("")
    w(SUMMARY_END)
    w("")


def _tests_appendix(w, rv: ReviewResult) -> None:
    ok = [rr for rr in rv.req_results if rr.test_possible is True and rr.test_gherkin]
    if not ok:
        return
    w(f"### Приложение. Тест-пробы: приёмочные тесты составлены ({len(ok)})")
    w("")
    for rr in ok:
        w(f"<details><summary>🧪 {_link(rr.req.rid)}{f' ({rr.req.doc_id})' if rr.req.doc_id else ''}</summary>")
        w("")
        w("```gherkin")
        w(rr.test_gherkin)
        w("```")
        w("</details>")
        w("")


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


def _extras_tail(w, ctx) -> None:
    """Блоки итога: эффект исправлений, цена дефекта, динамика, вопросы заказчику, исправления, граф."""
    sc = ctx.scores
    if ctx.rescore:
        rs = ctx.rescore
        w(f"**Эффект исправлений (повторный прогон исправленного документа):** балл {rs['before']} → **{rs['after']}**, "
          f"готовность {rs['readiness_before']} % → **{rs['readiness_after']} %**.")
        w("")
    if any(h for _, h in sc.cost):
        w("**Цена дефекта** (ориентировочно: трудозатраты на исправление найденных дефектов в зависимости от момента обнаружения):")
        w("")
        w("| Когда исправлять | Трудозатраты |")
        w("|---|---|")
        for name, h in sc.cost:
            w(f"| {name} | ≈ {h:g} ч |")
        w("")
    if ctx.compare:
        c = ctx.compare
        w(f"### Динамика относительно предыдущей версии: средний балл {c['score_before']} → {c['score_after']}")
        w("")
        lab = {"fixed": "✅ исправлено", "improved": "⬆️ улучшилось", "new": "⚠️ новое", "worse": "🔻 ухудшилось",
               "same": "без изменений"}
        line = " · ".join(f"{lab[k]}: {v}" for k, v in c["counts"].items())
        if c["removed"]:
            line += f" · удалено: {len(c['removed'])}"
        w(line)
        w("")
        w("| Требование | Статус | Балл было → стало |")
        w("|---|---|---|")
        for r in c["rows"]:
            if r["status"] == "same":
                continue
            name = r["rid"] + (f" ({r['doc_id']})" if r["doc_id"] else "")
            before = r["before"] if r["before"] is not None else "—"
            w(f"| {name} | {lab[r['status']]} | {before} → {r['after']} |")
        w("")
    if ctx.questions:
        w(f"### Вопросы заказчику ({len(ctx.questions)})")
        w("")
        for i, q in enumerate(ctx.questions[:30], 1):
            w(f"{i}. {ICON.get(q.severity, '')} **{_cell(q.ref)}** — {_cell(q.text)}")
        w("")
    if ctx.changes:
        w("### Исправленный документ")
        w("")
        w(f"Агент подготовил исправленную версию документа ({len(ctx.changes)} формулировок). Топ-10 изменений:")
        w("")
        w("| Требование | Было | Стало |")
        w("|---|---|---|")
        for ch in ctx.changes[:10]:
            name = ch.rid + (f" ({ch.doc_id})" if ch.doc_id else "")
            w(f"| {name} | {_cell(ch.before)} | {_cell(ch.after)} |")
        w("")
    if ctx.graph and ctx.graph.get("edges"):
        from .graph import mermaid

        w("### Граф связей и противоречий")
        w("")
        w("```mermaid")
        w(mermaid(ctx.graph))
        w("```")
        w("")


_BASIS_SEEN: dict = {}  # основания текущего отчёта: (file, section) → запись (цитата — один раз, в приложении)


def _basis_lines(w, findings) -> None:
    """«Основание» из базы знаний kb/ у замечания — короткая ссылка (вид, пункт, файл); дословная цитата из kb/ —
    один раз, в приложении «Основания из базы знаний» (без повторов по всему отчёту)."""
    seen, refs = set(), []
    for f in findings:
        for b in getattr(f, "basis", None) or []:
            key = (b["file"], b["section"])
            if key in seen:
                continue
            seen.add(key)
            _BASIS_SEEN.setdefault(key, b)
            kind = {"standards": "стандарт", "law_kz": "норма РК, пересказ", "patterns": "шаблон"}.get(b.get("kind"), "база знаний")
            refs.append(f"{kind}: {_cell(b['section'])} (`{b['file']}`)")
    if refs:
        w("**Основание:** " + "; ".join(refs))
        w("")


def _basis_appendix(w) -> None:
    if not _BASIS_SEEN:
        return
    w(f"### Приложение. Основания из базы знаний ({len(_BASIS_SEEN)})")
    w("")
    w("Дословные фрагменты файлов `kb/`, на которые ссылаются замечания (нормы РК — пересказ, не текст закона).")
    w("")
    for (file, section), b in sorted(_BASIS_SEEN.items()):
        w(f"- **{_cell(section)}** (`{file}`): «{_cell(b['quote'])}»")
    w("")


