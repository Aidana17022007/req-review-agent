# Где интерфейс показывает поля схемы 2.2 (RAG)

Контракт полей — `docs/SCHEMA.md` (ведёт backend). Здесь — как интерфейс их читает и где показывает.
Все поля необязательны: нет данных — блок скрыт, отчёт работает как в 2.1. Пример полного report.json 2.2 — `tests/fixtures/report_v22.json`
(mock-прогон backend с RAG; предпросмотр отчёта по нему — `python -m req_review.ui.preview`).

| Поле backend | Как читает UI (`req_review/html_report.py`) | Где в интерфейсе |
|---|---|---|
| `findings[].basis[]`, `set_findings[].basis[]` `{source, section, quote, url, kind, license, file}` | `kind`: `standards`→стандарт, `law_kz`→закон РК, `patterns`→шаблон; `section` — пункт; `license` с «пересказ» → пометка «пересказ своими словами»; `url` — только `https://`; без `quote` или `source` основание не выводится | блок «Основание» (карточка у фрагмента, таблица, drawer, замечания набора), раздел «База знаний», источники ассистента |
| `requirements[].rewrite_pattern` `{id, title, template, file}` | название и шаблон из `kb/patterns`, текст — формулировка агента (`rewrite`) | «По шаблону «…»» и «Применить шаблон» в «Исправлениях» |
| `requirements[].category` (functional, security…) | подпись из `categories.CATEGORIES` | чипы и фильтр «Категория» в таблице требований |
| `coverage_map[]` / `rv.coverage` `{id, title, reqs, covered, question}` | шаги процесса домена | раздел «Покрытие процесса»: непокрытый шаг — красная метка и вопрос аналитику |
| `passport.context` `{mode, avg_prompt_tokens, doc_chars}` | «RAG-выборка» / «полный текст» | карточка агента и паспорт прогона |
| `passport.rag` `{kb_chunks, search, embedder, basis, law, patterns}` или `{enabled: false}` | размер базы знаний и число оснований | карточка агента и паспорт прогона |

Ассистент Studio (`/api/jobs/{id}/ask`) приводит `basis` к тому же виду и возвращает `sources`:
`{type: "req"}` — требование, `{type: "line", line}` — строка документа (из `findings[].span.line`), `{type: "kb", source, clause, quote, url}` — фрагмент базы знаний.
