# Дизайн-система ReqLens v2

Одна система для сайта, приложения (Studio) и HTML-отчёта. Витрина со всеми токенами и компонентами в обеих темах — `design/styleguide.html`.

## Источник правды

| Что | Где | Как пересобрать |
|---|---|---|
| Токены (цвета, шрифты, отступы, радиусы, тени, движение, слои) | `design/tokens.json` | `python -m req_review.ui.styleguide` → `req_review/ui/tokens.css`, витрина, слайды |
| Компоненты (CSS-классы) | `req_review/ui/assets/base.css` | — |
| Иконки (24×24, линия 1.75, `currentColor`) | `req_review/ui/icons.py` | — |
| Логотип, favicon, иконки PWA | `req_review/ui/brand.py` → `design/brand/` | `python -m req_review.ui.brand` (PNG — нужен Pillow) |

`tokens.css` руками не правят. Тест `tests/test_design.py` падает, если он разошёлся с `tokens.json`.

## Токены

- **Палитра** — опорные шкалы `--green-50…950` и `--gray-50…950`. Компоненты используют только **семантические** токены, а не шкалы напрямую.
- **Семантика** (светлая и тёмная тема):
  - поверхности и текст: `--bg`, `--surface`, `--surface-2`, `--border`, `--text`, `--text-2`, `--text-3`;
  - бренд: `--brand`, `--on-brand`;
  - серьёзность: `--critical`, `--major`, `--minor`, `--ok`, `--info` — у каждого есть варианты `-accent` и `-soft`;
  - деструктивные действия: `--danger`, `--on-danger`.
- **Контраст.** Каждая пара «текст / фон» проходит WCAG AA (≥ 4.5) в обеих темах. Таблица контраста — в витрине, проверка — тест.
- **Шрифт.**
  - Шкала размеров `--fs-xs…3xl` = 12 / 14 / 16 / 20 / 24 / 32 / 48 px, межстрочный интервал — `--lh-*`.
  - Роли интерфейса: `--t-display`, `--t-h1`, `--t-body`, `--t-small` и другие.
- **Отступы** `--s-1…8` = 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 px.
- **Радиусы:** `--r-sm`, `--r-md`, `--r-lg`, `--r-xl`, `--r-2xl`, `--r-full`.
- **Тени** `--shadow-sm/md/lg`.
- **Движение:** `--motion-fast` (120 мс), `--motion-base` (200 мс), `--motion-slow` (280 мс).
  - Микроанимации — не дольше `base`.
  - При `prefers-reduced-motion` анимации выключаются.
- **Слои** `--z-*`: sticky < sidebar < overlay < drawer < popover < modal < tooltip < toast. Числа в `z-index` больше 9 в `base.css` запрещены тестом.

## Компоненты (классы `base.css`)

| Компонент | Классы |
|---|---|
| Кнопки | `.btn` + `.btn-primary` / `-secondary` / `-ghost` / `-danger`; размеры `.btn-sm` / `.btn-lg`; `.btn-icon`, `.btn-round`; состояние `.loading`, `[disabled]` |
| Поля | `.field` > `label` + `.input` (`input`, `select`, `textarea`) + `.hint` / `.err`; ошибка — `.field.invalid` и `aria-invalid` |
| Загрузка файла | `.dropzone` (`.is-over`, когда файл над зоной), `.dz-ic`, `.formats` |
| Бейджи и чипы | `.chip` + `.sev-critical` / `-major` / `-minor` / `-ok` / `-info`, `.chip-brand`, `.chip-outline`, `.kbd`, `.status`, `.verdict-badge` |
| Карточки | `.card`, `.kpi`, `.kpi-hero` |
| Таблица | `.table-wrap` > `.tbl` |
| Вкладки, переключатели | `.tabs` > `.tab[aria-selected]`; `.seg` (`.seg-sm`) > `button[aria-pressed]` — тема и язык |
| Drawer, модальное окно | `.overlay` + `.drawer.open`; `.modal.open` > `.modal-box` (`role="dialog"`, `aria-modal`) |
| Тост | `.toast.show` + `.toast-ok` / `-err` / `-info` |
| Тултип | атрибут `data-tip="…"` (при наведении и при фокусе с клавиатуры) |
| Прогресс этапов | `.stages` (`style="--p:58"`) > `.stages-bar` + `ol > li.done / .run / .fail`; вертикальный — `.stepper` |
| Пустое состояние и загрузка | `.empty` (+ `.empty-ic`, кнопка действия); `.skel`, `.skel-lg`, `.skel-circle`, `.skel-card` |

## Для PWA (человек 1)

- **Иконки** лежат в `design/brand/`:
  - `icon-192.png`, `icon-512.png` (`purpose: any`);
  - `icon-maskable-512.png` (`purpose: maskable`, глиф в безопасной зоне 80 %);
  - `apple-touch-icon.png` (180), `favicon-32.png`, `favicon.svg`.
- **`design/brand/brand.json`** — готовый фрагмент для `manifest.webmanifest`: `name`, `short_name`, `theme_color` `#1F6B45`, `background_color` `#F3F5F3`, массив `icons`. Для тёмной темы — `background_color_dark` `#0E1410`.
- **Офлайн-отчёт.** В шаблонах favicon встраивается через `favicon_href()`, а знак — через `logo_mark(size)`, поэтому отчёт остаётся одним файлом.
