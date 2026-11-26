# Поля схемы 2.2 (RAG), которые читает интерфейс — договорённость человек 1 ↔ человек 2

Окончательное описание схемы — в `docs/SCHEMA.md` (ведёт backend). Здесь — что ожидает UI, чтобы обе ветки сошлись.
Пример с заполненными полями: `tests/fixtures/report_v22.json`; предпросмотр отчёта по нему — `python -m req_review.ui.preview`.

Все поля **необязательны**: если backend их не заполнил, соответствующие блоки интерфейса скрыты, отчёт работает как в 2.1.
UI читает их из объектов прогона через `getattr` (`req_review/html_report.py`), ассистент Studio — из `report.json`.

| Поле | Объект прогона → report.json | Формат | Где в UI |
|---|---|---|---|
| `basis` | `Finding.basis` → `requirements[].findings[].basis` | `[{kind, source, clause, quote, url, paraphrase}]` | «Основание» в карточке, таблице, drawer; раздел «База знаний»; источники ассистента |
| `basis` | `SetFinding.basis` → `set_findings[].basis` | то же | «Основание» у замечаний к набору |
| `category` | `ReqResult.category` → `requirements[].category` | строка («Платежи», «Безопасность»…) | чипы и фильтр в таблице требований |
| `rewrite_pattern` | `ReqResult.rewrite_pattern` → `requirements[].rewrite_pattern` | `{ears, template, text}` | «По шаблону EARS» и «Применить шаблон» в «Исправлениях» |
| `coverage` | `ctx.coverage` → `coverage` | `{process, steps: [{id, title, rids[], question}]}` | раздел «Покрытие процесса» |
| `context_mode` | `ctx.passport["context_mode"]` | `"full"` \| `"rag"` | паспорт, карточка агента |
| `context_chunks`, `tokens_per_call` | `ctx.passport[...]` | числа | паспорт, карточка агента |

## Правила для `basis`

- `kind`: `standard` (стандарт), `law` (закон РК), `template` (шаблон). Иное значение UI показывает как `standard`.
- `quote` — **дословный фрагмент из `kb/`** (проверен кодом, как цитаты документа). Без `quote` или `source` основание не показывается.
- `paraphrase: true` — фрагмент kb является собственным пересказом стандарта (платные тексты ISO/IEEE не коммитим); UI пишет «пересказ своими словами».
- `url` — только `https://` (официальный текст, например adilet.zan.kz); иначе ссылка не выводится.
- `clause` — номер пункта («5.2.5 d) Complete», «ст. 22»), для шаблона — название шаблона.

## Ассистент Studio

Ответ `/api/jobs/{id}/ask` дополнен полем `sources`: `{type: "req", id, label}`, `{type: "line", line, rid, text}`,
`{type: "kb", kind, source, clause, quote, url, paraphrase}`. Строки документа берутся из `findings[].span.line` (2.1).
