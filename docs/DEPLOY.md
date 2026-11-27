# Деплой: сайт на Cloudflare Pages, бэкенд (Studio + API) на Render

Оба сервиса подключаются к репозиторию **один раз**. Дальше каждый push в `main` выкатывается сам:
Render пересобирает Studio, Cloudflare пересобирает сайт. Ключи в репозиторий не попадают.

Как это выглядит для посетителя:

- **Сайт** (Cloudflare) → кнопка **«Оценить без установки»**. Если Studio отвечает, кнопка ведёт в Studio,
  если нет — в интерактивный отчёт по документу организаторов.
- **Studio** (Render) → **«Открыть готовый пример»** (`/?example=1`): отчёт по документу организаторов открывается
  сразу, без прогона и без квоты. Посетитель может загрузить и свой файл — до 5 проверок в сутки с одного адреса
  и до 20 в сутки всего.

## 1. Бэкенд на Render (Studio, API v1)

### Вариант А — Blueprint (рекомендуется)

1. <https://dashboard.render.com> → **New → Blueprint** → выбрать репозиторий `req-review-agent` (Render попросит
   доступ к GitHub).
2. Render прочитает `render.yaml` и создаст сервис `reqlens-studio`. На запрос значения `GEMINI_API_KEY` вставьте
   ключ Gemini. Ключ хранится только в панели Render: **Environment**.
3. После сборки адрес будет вида `https://reqlens-studio.onrender.com`. Проверка: `/api/health` отвечает 200,
   а `/?example=1` сразу открывает готовый пример.

### Вариант Б — Web Service вручную

**New → Web Service** → репозиторий → Runtime **Python 3**:

| Поле | Значение |
|---|---|
| Build Command | `pip install -r requirements.txt && gunzip -kf reports/requirements-report.html.gz` |
| Start Command | `python -m req_review.web --demo reports/requirements-report.json` |
| Health Check Path | `/api/health` |
| Environment | `GEMINI_API_KEY` (секрет), `STUDIO_HOST=0.0.0.0`, `PYTHON_VERSION=3.12.7`, `REQLENS_DATA=/tmp/reqlens`, `MAX_JOBS=1` |

`--demo` в Start Command включает кнопку «Демо»: она проигрывает сохранённый прогон без обращений к модели.
`gunzip` распаковывает HTML-отчёт для готового примера и «Демо».

### Ключ модели

- `GEMINI_API_KEY` задаётся только в Environment. В git и в браузер он не попадает: `/api/health` сообщает лишь,
  задан ли ключ.
- `GEMINI_API=openai` нужен только там, где ключ подставляет прокси облачной среды. На Render оставьте значение по
  умолчанию (`native`).
- Без ключа Studio работает в режиме «Только правила», а готовый пример доступен всегда.

### Лимиты демо

Загрузки, которые тратят квоту модели, ограничены. Сюда входят новая проверка, «Перепроверить» с ответами аналитика
и старый `/api/review`.

| Переменная | По умолчанию на Render | |
|---|---|---|
| `DEMO_UPLOADS_PER_IP` | `5` | проверок с одного адреса в сутки (UTC); адрес берётся из `X-Forwarded-For` |
| `DEMO_UPLOADS_TOTAL` | `20` | проверок всего в сутки |
| | `0` | лимит выключен |

- Значения по умолчанию включаются сами, потому что Render задаёт переменную `PORT`. В `render.yaml` они прописаны
  явно, чтобы их было видно и можно было поменять в панели.
- Готовый пример, «Демо» и режим «Только правила» в лимит не входят.
- При превышении Studio показывает экран «Дневной лимит демо исчерпан»: когда можно снова и кнопки «Открыть готовый
  пример» и «Проверить без модели».
- Локально (`python -m req_review.web`) лимитов нет. Счётчики живут в памяти и обнуляются при перезапуске.

Бесплатный тариф засыпает без запросов: первый заход после паузы занимает около минуты. История прогонов на
бесплатном тарифе не переживает передеплой (`REQLENS_DATA=/tmp/reqlens`).

## 2. Сайт на Cloudflare Pages

**Вариант А — подключить репозиторий (проще, без секретов).**
<https://dash.cloudflare.com> → **Workers & Pages → Create → Pages → Connect to Git** → репозиторий → настройки сборки:

| Поле | Значение |
|---|---|
| Production branch | `main` |
| Build command | `python3 -m pip install -r requirements.txt markdown && python3 scripts/build_site.py --out public` |
| Build output directory | `public` |
| Environment variables | `STUDIO_URL` = адрес Studio с Render (без `/` в конце); `PYTHON_VERSION` = `3.12`; `REPO_PUBLIC` = `1` — только если репозиторий открыт |

**Вариант Б — GitHub Actions** (`.github/workflows/deploy-site.yml`). В репозитории: Settings → Secrets and variables →
Actions:

- секрет `CLOUDFLARE_API_TOKEN` — токен с правом *Cloudflare Pages: Edit*;
- секрет `CLOUDFLARE_ACCOUNT_ID`;
- переменная `STUDIO_URL`.

Проект Pages `reqlens` создаётся при первом деплое. Без секретов workflow только собирает сайт (артефакт `site`) и
ничего не выкладывает.

**Порядок:** сначала Render, затем Cloudflare. Если сайт собрался, пока Studio ещё не проснулась, нажмите в Cloudflare
**Deployments → Retry deployment**: кнопки переключатся на Studio.

### Ссылки без 404

- **«Оценить без установки».** При сборке `scripts/build_site.py` запрашивает `STUDIO_URL/api/health` и ждёт до 75 с:
  бесплатный Render просыпается до минуты.
  - Ответ 200 — кнопка ведёт в Studio (там готовый пример и загрузка своего файла).
  - Адреса нет или Studio не отвечает — кнопка ведёт в интерактивный отчёт (`/report/`), а «Проверить свой
    документ» — к разделу «Одна команда».
  - Поставить ссылку без проверки: `STUDIO_FORCE=1`.
- **Файлы рядом с отчётом.** Ссылки на журнал прогона, шаблон ответов и повестку решений появляются в `/report/`,
  только если эти файлы лежат в `reports/`. Иначе сборка убирает ссылки, и 404 не будет.
- **GitHub.** Закрытый репозиторий отдаёт посетителю 404, поэтому ссылки на GitHub появляются только при
  `REPO_PUBLIC=1`. Соответствие ТЗ и `llms.txt` лежат на самом сайте (`/tz/`, `/llms.txt`).
- **«Слепые документы».** Раздел на сайте и слайд появляются, только если в `bench/RESULTS.md` есть раздел
  «Слепые документы» с прогоном на модели (его пишет `python bench/blind_eval.py --results`). Прогон на mock и
  выдуманные цифры не показываются.

## Что на сайте

`scripts/build_site.py` собирает папку `public/`:

- главная: цифры из `bench/results.json`, отчёта для сдачи и `scripts/tz_check.py`;
- интерактивный отчёт по документу организаторов (`reports/requirements-report.html.gz`);
- видео «ReqLens за 60 секунд» (`docs/assets/demo-60s.mp4`);
- слайды (`docs/slides.html`);
- соответствие ТЗ (`/tz/`) и `llms.txt`.

Кода агента и ключей на сайте нет. Локальная сборка и просмотр:
`python scripts/build_site.py && python -m http.server -d public 8000`.
