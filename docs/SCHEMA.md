# Формат report.json (контракт backend ↔ UI)

Версия схемы: **2.2**. Правило: изменения только добавляющие — поля 2.0 не переименовываются и не удаляются.

## Что добавлено в 2.2 (RAG и аналитика)

| Поле | Где | Описание |
|---|---|---|
| `requirements[].findings[].basis[]` | замечание | основания из базы знаний `kb/`: `{"source","section","quote","url","kind","license","file"}`; `quote` — дословный фрагмент файла `kb/` (проверяется кодом) |
| `set_findings[].basis[]` | замечание набора | то же для замечаний к набору |
| `requirements[].rewrite_pattern` | требование | шаблон хорошего требования из `kb/patterns`, на который опирается правка: `{"id","title","template","file"}` |
| `requirements[].category` | требование | functional / performance / availability / security / data / interface / integration / regulatory / acceptance / other |
| `categories` | корень | число требований по категориям |
| `coverage_map[]` | корень | шаги типового процесса домена: `{"id","title","reqs","covered","question"}` |
| `passport.rag` | паспорт | `{"kb_chunks","search","embedder","basis","law","patterns"}` или `{"enabled": false}` |
| `passport.context` | паспорт | `{"mode": "полный текст" \| "RAG-выборка", "avg_prompt_tokens", "doc_chars"}` |
| `passport.model_switches[]` | паспорт | переключения на резервную модель при 503 |

## Что добавлено в 2.1

| Поле | Где | Описание |
|---|---|---|
| `requirements[].char_start` | требование | смещение начала требования в исходном тексте (символы) |
| `requirements[].tests[]` | требование | 1–3 сценария `{"title", "gherkin"}`; `test.gherkin` = все сценарии одним текстом (совместимость с 2.0) |
| `requirements[].findings[].span` | замечание | `{"line", "start", "end", "offset"}` — точное место цитаты в документе |
| `requirements[].findings[].confidence_score` | замечание | уверенность 0–1 (метка `confidence` high/medium/low сохранена) |
| `set_findings[].values[]` | замечание набора | конфликтующие значения `{"rid", "value", "quote"}` — «3 неверных вводов» vs «5 неверных вводов» |
| `set_findings[].refs[].span` | ссылка | место цитаты каждого задействованного требования |
| `set_findings[].confidence_score` | замечание набора | уверенность 0–1 |
| `changes[].unified` | исправление | unified diff формулировки «было → стало» |
| `questions[].rid`, `questions[].criterion` | вопрос | привязка к требованию (R-xxx) или замечанию набора (S-xx) |
| `graph.nodes[].type`, `.score`, `.nfind` | граф | тип EARS, балл требования, число дефектов |

## Уверенность 0–1

| Источник | Значение |
|---|---|
| тест-проба (тест составить невозможно, цитата подтверждена) | 0.95 |
| числовое противоречие, найденное правилом (и подтверждённое моделью) | 0.90 (0.95) |
| подтверждено критиком и двумя источниками (модель + правило) | 0.90 |
| подтверждено критиком | 0.75 |
| только правило / доменный чек-лист | 0.60 |
| только модель, без критика | 0.55 |

## Артефакты прогона (рядом с отчётом `<имя>.md`)

`<имя>.html`, `<имя>.json`, `<имя>_requirements_fixed.md`, `<имя>_fixed.diff`, `<имя>_tests.feature`,
`<имя>_traceability.xlsx`, `<имя>_jira_import.csv`.
