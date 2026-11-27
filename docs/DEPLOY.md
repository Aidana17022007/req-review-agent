# Деплой: сайт на Cloudflare Pages, бэкенд (Studio + API) на Render

Оба сервиса подключаются к репозиторию **один раз**, дальше каждый push в `main` выкатывается сам:
Render пересобирает Studio, Cloudflare пересобирает сайт. Ключи в репозиторий не попадают.

## 1. Бэкенд на Render (Studio, API v1)

1. <https://dashboard.render.com> → **New → Blueprint** → выбрать репозиторий `req-review-agent` (Render попросит доступ к GitHub).
2. Render прочитает `render.yaml` и создаст сервис `reqlens-studio`. Попросит значение `GEMINI_API_KEY` — вставить ключ Gemini.
3. После сборки адрес будет вида `https://reqlens-studio.onrender.com` (проверка: `/api/health`).

Бесплатный тариф засыпает без запросов, первый заход после паузы — около минуты. История прогонов на бесплатном
тарифе не переживает передеплой (`REQLENS_DATA=/tmp/reqlens`).

## 2. Сайт на Cloudflare Pages

**Вариант А — подключить репозиторий (проще, без секретов).**
<https://dash.cloudflare.com> → **Workers & Pages → Create → Pages → Connect to Git** → репозиторий → настройки сборки:

| Поле | Значение |
|---|---|
| Production branch | `main` |
| Build command | `python3 -m pip install -r requirements.txt markdown && python3 scripts/build_site.py --out public` |
| Build output directory | `public` |
| Environment variables | `STUDIO_URL` = адрес Studio с Render; `PYTHON_VERSION` = `3.12`; `REPO_PUBLIC` = `1` — только если репозиторий открыт |

**Вариант Б — GitHub Actions** (`.github/workflows/deploy-site.yml`). В репозитории: Settings → Secrets and variables →
Actions → секреты `CLOUDFLARE_API_TOKEN` (токен с правом *Cloudflare Pages: Edit*), `CLOUDFLARE_ACCOUNT_ID` и
переменная `STUDIO_URL`. Проект Pages `reqlens` создаётся при первом деплое. Без секретов workflow только собирает сайт
(артефакт `site`) и ничего не выкладывает.

### Ссылки без 404

- **Studio.** При сборке `scripts/build_site.py` запрашивает `STUDIO_URL/api/health`. Ответ 200 — кнопки «Проверить
  документ» ведут на Studio. Нет адреса или Studio не отвечает — главная кнопка «Открыть отчёт по документу
  организаторов» (`/report/`), «Проверить свой документ» — к разделу «Одна команда». Бесплатный Render просыпается до
  минуты; сборка ждёт до 75 с. Поставить ссылку без проверки: `STUDIO_FORCE=1`. После того как Studio заработала,
  нажмите в Cloudflare **Deployments → Retry deployment** — кнопки переключатся на Studio.
- **GitHub.** Закрытый репозиторий отдаёт посетителю 404, поэтому ссылки на GitHub появляются только при `REPO_PUBLIC=1`.
  Соответствие ТЗ и `llms.txt` лежат на самом сайте (`/tz/`, `/llms.txt`).

## Что на сайте

`scripts/build_site.py` собирает папку `public/`: главная (цифры из `bench/results.json`, отчёта для сдачи и
`scripts/tz_check.py`), интерактивный отчёт по документу организаторов (`reports/requirements-report.html.gz`), видео
«ReqLens за 60 секунд» (`docs/assets/demo-60s.mp4`), слайды (`docs/slides.html`), соответствие ТЗ (`/tz/`) и `llms.txt`. Кода агента
и ключей на сайте нет. Локально: `python scripts/build_site.py && python -m http.server -d public 8000`.
