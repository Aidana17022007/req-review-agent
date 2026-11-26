# ReqLens App — API v1

Контракт между backend (человек 1) и интерфейсом приложения (человек 2). Интерактивная документация —
`http://localhost:8000/docs` (OpenAPI: `/openapi.json`). Формат отчёта (`report.json` 2.2) — [SCHEMA.md](SCHEMA.md).

- Базовый путь: **`/api/v1`**. Старые эндпоинты Studio (`/api/review`, `/api/jobs/{id}/…`, `/jobs/{id}/{file}`)
  работают как раньше — текущий интерфейс Studio не сломан.
- Ключ модели берётся только из `.env` сервера; **ни один ответ его не содержит**.
- Все тексты ошибок — по-русски, для показа пользователю как есть.

## Ошибки

Любая ошибка `/api/v1/…` — один формат:

```json
{"error": {"code": "not_found", "message": "Прогон не найден"}}
```

| HTTP | `code` | Когда |
|---|---|---|
| 400 | `bad_request` | неверный параметр (профиль, домен, режим, пустое имя/вопрос); иногда есть `allowed` |
| 400 | `unsupported` | расширение не PDF/DOCX/MD/TXT |
| 400 | `empty` | пустой файл |
| 404 | `not_found` | нет проекта / прогона / файла |
| 409 | `busy` | удаление, пока прогон идёт |
| 409 | `finished` | отмена уже завершённого прогона |
| 409 | `not_ready` | вопрос ассистенту, пока отчёта нет |
| 413 | `too_large` | файл больше 10 МБ |
| 415 | `unsupported` | содержимое не соответствует расширению (например, .exe переименован в .md) |
| 422 | `invalid` | тело запроса не JSON / не тот тип |
| 503 | `offline` | только из service worker: нет сети (см. «PWA») |

## Объекты

**Проект**

```json
{"id": "a1b2c3d4e5", "name": "Уведомления о расходах", "created": 1764150000.1, "runs": 2,
 "last_run": { …Прогон… } }
```

**Прогон** (запись истории; `id` прогона = `id` задачи для SSE)

```json
{
  "id": "4f0c2a9e81b7", "project_id": "a1b2c3d4e5", "version": 2,
  "doc_name": "requirements_v2.md", "doc_hash": "e7dae55e…", "document_id": 3,
  "status": "done",                 // queued | running | done | error | cancelled | interrupted
  "mode": "llm",                    // llm — модель из .env; rules — только правила, без модели
  "model": "gemini / gemini-3.5-flash-lite", "agent_version": "v3.0.3, коммит cd99b52 …",
  "created": 1764150000.1, "finished": 1764150057.4,
  "score": 67, "readiness": 53, "critical": 7, "major": 12, "findings": 36,
  "verdict": "нельзя",              // нельзя | условно | можно (как в разделе «6. Итог» отчёта)
  "artifacts": {"Отчёт (Markdown)": "report.md", "Интерактивный отчёт (HTML)": "report.html", "Данные (JSON)": "report.json", …},
  "files": {"Отчёт (Markdown)": "/api/v1/runs/4f0c2a9e81b7/files/report.md", …},   // только в GET /runs/{id}
  "compare": { …сравнение с прошлой версией или null… },
  "error": "",
  // пока прогон идёт:
  "pct": 43, "stage": "Проверка требований", "queue_position": 1
}
```

`compare` (если в проекте была прошлая готовая версия): `before`/`after` — `{score, readiness, set, reqs, findings,
counts{critical,major,minor}, tests_ok, tests_total}`; `fixed`, `new` — списки дефектов `{rid, label, criterion, cname,
severity, problem, quote}`; `rows` — статус каждого требования (`fixed | improved | new | worse | same`).

## Эндпоинты

### Служебные

| Метод и путь | Ответ |
|---|---|
| `GET /api/v1/health` | `{provider, model, key_ok, key_name, mock, steps[7], profiles[], max_upload_mb: 10}` — без ключа |
| `GET /api/v1/sample` | демо-документ (Markdown) для кнопки «Попробовать без своего файла» |

### Проекты

| Метод и путь | Тело / параметры | Ответ |
|---|---|---|
| `GET /api/v1/projects` | — | `{"projects": [Проект…]}` (новые сверху) |
| `POST /api/v1/projects` | JSON `{"name": "…"}` | **201** Проект |
| `GET /api/v1/projects/{pid}` | — | Проект |
| `DELETE /api/v1/projects/{pid}` | — | `{"deleted": pid}`; **409** `busy`, если идёт прогон |
| `GET /api/v1/projects/{pid}/runs` | — | `{"project", "runs": [Прогон… по версиям], "trend": [{version, run, score, critical, readiness, created}]}` — данные для графика динамики |

### Проверка документа

`POST /api/v1/projects/{pid}/runs` — `multipart/form-data`:

| Поле | По умолчанию | |
|---|---|---|
| `file` | — | PDF / DOCX / MD / TXT, ≤ 10 МБ, содержимое проверяется |
| `profile` | `fast` | `fast` \| `full` \| `offline` |
| `domain` | `fintech` | `fintech` \| `none` |
| `mode` | `llm` | `llm` \| `rules` (без модели — предложить при ошибке квоты) |
| `force` | `false` | `true` — проверить заново, даже если этот файл уже проверялся |

Ответы:

```json
// тот же файл (SHA-256) уже проверен в проекте — новый прогон НЕ запускается, квота не тратится
{"duplicate": true, "run": { …Прогон… }, "message": "Этот файл уже проверялся — открыт прошлый результат…"}

// новый прогон
{"duplicate": false, "run": { …Прогон, status: "queued"… }, "job": "4f0c2a9e81b7",
 "compare_with": "9d1e…" | null, "events": "/api/v1/jobs/4f0c2a9e81b7/events"}
```

### Прогоны

| Метод и путь | Ответ |
|---|---|
| `GET /api/v1/runs/{rid}` | Прогон с `files` (+ `pct`/`stage`/`queue_position`, пока идёт) |
| `DELETE /api/v1/runs/{rid}` | `{"deleted": rid}`; **409** `busy`, пока идёт — сначала отменить. На фронте — подтверждение «Удалить безвозвратно?» |
| `GET /api/v1/runs/{rid}/files/{name}` | файл отчёта; `name` — **только** из `artifacts` прогона (иначе 404). HTML открывается в браузере, остальное скачивается |
| `POST /api/v1/runs/{rid}/ask` | ассистент, см. ниже |

### Живой прогон и отмена

`GET /api/v1/jobs/{jid}/events` — Server-Sent Events (`data: {json}` на событие, поток закрывается после
`done` / `error` / `cancelled`). Поле `kind`:

| `kind` | Поля | Что показать |
|---|---|---|
| `queued` | `position` | «В очереди: N» (одновременно идёт `MAX_JOBS` прогонов, по умолчанию 2) |
| `started` | — | прогон взял слот |
| `step` | `i` (0–6), `name`, `pct` | этап и прогресс: Чтение → Нарезка → Проверка требований → Проверка набора → Домен и глоссарий → Критик → Отчёты |
| `split` | `total` | сколько требований выделено |
| `batch_start` / `batch_done` / `batch_fail` | `reqs[]` / `results[]` / `rids[]` | живая таблица требований |
| `log` | `msg` | строка журнала |
| `done` | `summary`, `artifacts`, `pct: 100` | итог; запись истории уже обновлена |
| `error` | `msg`, `code` (`key` \| `quota` \| `noreqs` \| `error`); при `quota` — `fallback: "rules"`, `hint` | при `quota` — кнопка «Проверить без модели (только правила)» → тот же файл с `mode=rules` |
| `cancelled` | `msg` | «Прогон отменён» |

`POST /api/v1/jobs/{jid}/cancel` → `{"job", "cancelling": true}`. В очереди отменяется сразу; во время работы —
на ближайшей границе этапа/пакета (уже отправленный запрос к модели не прерывается). **409** `finished`, если прогон завершён.

После перезапуска сервера незавершённые прогоны получают `status: "interrupted"`; поток событий для них недоступен (404).

### Ассистент

`POST /api/v1/runs/{rid}/ask` — JSON `{"q": "вопрос", "stream": false}`.

```json
{
  "answer": "Исправить в первую очередь: [[R-006]] …",
  "mode": "по данным отчёта" | "модель по источникам",
  "source": "отчёт" | "источники",
  "refs": ["R-006"],
  "sources": [
    {"kind": "requirement", "ref": "R-006", "label": "FR-06", "quote": "…", "line": 21, "note": "critical: …"},
    {"kind": "document", "ref": "L42", "label": "строка 42", "quote": "…", "line": 42},
    {"kind": "kb", "ref": "law_kz/fintech_norms.md", "label": "…", "quote": "…", "file": "kb/law_kz/fintech_norms.md",
     "url": "https://…", "paraphrase": true, "note": "пересказ нормы, не текст закона"}
  ],
  "suggest": ["Что исправить первым?", …]
}
```

- Типовые вопросы («Почему R-006 критичное?», «Что исправить первым?», «Какие противоречия?») — по `report.json`,
  без модели и без расхода квоты; `[[R-006]]` в тексте — ссылка на требование в отчёте.
- Остальные — по источникам трёх видов; модель (если доступна) отвечает **только** по ним и ссылается `[n]` на номер
  источника. При 429 / без сети — ответ из самих источников без модели.
- У фрагментов норм РК (`kb/law_kz`) всегда `paraphrase: true` — показывать подпись «пересказ, не текст закона».
- `stream: true` — `text/event-stream`: `event: sources` (`{sources}`), затем несколько `event: answer` (`{text}` —
  куски ответа по предложениям), в конце `event: done` (остальные поля).

## PWA

| Путь | |
|---|---|
| `/manifest.webmanifest` | имя «ReqLens», `display: standalone`, `theme_color` = `--brand` (#1F6B45), иконки 192/512/maskable |
| `/sw.js` | service worker (область — всё приложение) |
| `/static/{icon.svg, icon-192.png, icon-512.png, icon-maskable-512.png, apple-touch-icon.png}` | знак дизайн-системы v2 (`design/brand/`) |
| `/offline` | экран «Нет интернета» |

Кэш service worker: оболочка и статика — из кэша; `GET /api/v1/…` (проекты, история, прогоны) и открытые отчёты —
«сначала сеть, иначе кэш» (офлайн видна история); SSE не кэшируется; `POST` без сети → **503**
`{"error": {"code": "offline", "message": "Нужен интернет: проверка документа обращается к модели…"}}`.

Теги манифеста, `theme-color`, `apple-touch-icon` и регистрация service worker — в шаблоне `studio.html.j2`;
серверная вставка (`app.py`, `PWA_HEAD`) поэтому не срабатывает и остаётся только как запасной вариант.

## Экраны Studio на API v1

| Экран | Эндпоинты |
|---|---|
| Новая проверка (выбор проекта, режим «С моделью / Только правила») | `POST /projects` (проект по имени файла), `POST /projects/{pid}/runs`; `duplicate: true` — открывается прошлый результат с кнопкой «Проверить заново» (`force=true`) |
| Проекты | `GET /projects`, `POST /projects`, `DELETE /projects/{pid}` (подтверждение) |
| Проект: KPI, график `trend`, история версий | `GET /projects/{pid}/runs` (пока идёт прогон — обновление раз в 2,5 с), `DELETE /runs/{rid}` («Удалить безвозвратно?») |
| Живой прогон: очередь, этап, процент, отмена | `GET /jobs/{jid}/events`, `POST /jobs/{jid}/cancel`; при `error.code = quota` — «Проверить без модели (только правила)» → тот же файл с `mode=rules` |
| Отчёт и ассистент с источниками | `GET /runs/{rid}`, `GET /runs/{rid}/files/{name}`, `POST /runs/{rid}/ask` |
| До / После | поле `compare` прогона; «Проверить исправленный агентом» загружает `*_requirements_fixed.md` прогона новой версией |

Режим «Демо» (`--demo`) по-прежнему идёт через старые эндпоинты Studio и в историю не попадает.
