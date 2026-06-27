# Золото GitHub

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Автопилот для Telegram-канала про хайповые репозитории GitHub** — с коллекционными карточками для Instagram.

Канал отвечает на один вопрос: *«Почему мне хочется открыть это прямо сейчас?»*  
Посты пишет Claude по **реальному README** (не по названию репо). Картинки — скриншоты из README или брендовая плашка; раз в день — карта-джокер **«ДИЧЬ»**.

**Режим:** `POSTS_PER_RUN=3` × 3 запуска в сутки ≈ **9 хайп-постов/день** + **1 дичь/день** (Task Scheduler / cron).

> Подробная база знаний для Obsidian: [`docs/obsidian/Золото GitHub.md`](docs/obsidian/Золото%20GitHub.md)

---

## Содержание

- [Возможности](#возможности)
- [Как это работает](#как-это-работает)
- [Рубрика «Дичь»](#рубрика-дичь)
- [Коллекционные карточки](#коллекционные-карточки-instagram)
- [QA карточек](#qa-карточек)
- [Структура проекта](#структура-проекта)
- [Установка](#установка)
- [Конфигурация](#конфигурация)
- [Запуск](#запуск)
- [Админ-бот](#админ-бот)
- [Скрипты](#скрипты)
- [Диагностика](#диагностика-и-типичные-проблемы)

---

## Возможности

| Слой | Что делает |
|------|------------|
| **Радар** | GitHub Search + Trending → hype score (бренд, тренд, визуал, velocity) |
| **Куратор** | Claude отбирает ~70% хайпа / ~30% пользы, пишет пост + текст карточки **по README** |
| **Дичь** | Резерв `weird_reserve`, 1 джокер/день, неоновый бейдж, только со скриншотом |
| **Паблишер** | Telegram `sendPhoto` (README-скрин → OG fallback для хайпа) |
| **Карточки** | Playwright PNG 1080×1350 / 1080×1920, редкость или «ДИЧЬ», QA перед сохранением |
| **Грунтинг** | Тексты только из README/API; `unclear` → репо пропускается |

Отсев: форки, архивы, awesome-листы, SDK, пустые терминалы, YouTube-превью, NSFW (для дичи), выдумки из названия репо.

---

## Как это работает

```
GitHub Search + Trending
    → README + image_pick + hype
    → prefilter (velocity, final_score)
    → refill weird_reserve (параллельно)
    → curator: POSTS_PER_RUN−1 хайп (+ 1 дичь если слот свободен)
    → publisher (Telegram)
    → slides + card_qa (Playwright PNG)   [MAKE_SLIDES=true]
    → SQLite (published, weird_reserve, дедуп)
```

**Hype score:** бренд, тренды, массовая аудитория, скриншот в README, gif, velocity, свежесть.

---

## Рубрика «Дичь»

Отдельная категория — **1 карта-джокер в сутки**, не на лестнице редкости.

| Механика | Описание |
|----------|----------|
| **Резерв** | `weird_reserve` до `WEIRD_RESERVE_TARGET` (10); пополняется каждый прогон |
| **Слот** | Если `weird_posted_today < WEIRD_PER_DAY` → в прогоне `POSTS_PER_RUN−1` хайп + 1 дичь |
| **Quality-gate** | Пустой резерв или нет скриншота → слот пропускается |
| **Визуал** | Только реальный скрин/гиф из README; плашка для дичи **запрещена** |
| **Текст** | Простой язык, без внутряк-мемов; `slide_body` ≤ 200 символов |

```env
WEIRD_ENABLED=true
WEIRD_PER_DAY=1
WEIRD_RESERVE_TARGET=10
WEIRD_ACCENT=#FF3D9A
WEIRD_BADGE=ДИЧЬ
```

Предзагрузка резерва: `python scripts/seed_weird.py`

---

## Коллекционные карточки (Instagram)

### Форматы

| Формат | Размер | Папка |
|--------|--------|-------|
| **carousel** | **1080×1350** (4:5) | `data/instagram/carousel/` |
| **reel** | **1080×1920** (9:16) | `data/instagram/reels/` |

Safe-zone: шапка и футер ≥ **70px** от краёв.

### Дизайн (минимализм, 6 блоков)

1. Шапка — бренд + бейдж (редкость или **★ ДИЧЬ**)
2. Арт-окно — скрин `object-fit: cover` или брендовая плашка (только хайп)
3. Имя репо + мета (язык • лицензия)
4. `slide_headline` + `slide_body`
5. Статы одной строкой: ⭐ · 🍴 · ◎ issues
6. Футер — тэглайн + @handle

Текст в зоне copy **не наезжает на стат-бар**: JS уменьшает кегль до 36px, в крайнем случае — `…`.

### Папки

```
data/instagram/
├── carousel/{YYYY-MM-DD}/{HH-MM}/owner_repo_carousel.png
├── reels/{YYYY-MM-DD}/{HH-MM}/owner_repo_reel.png
├── _cache/images/
└── _samples/               # тестовые рендеры
```

---

## QA карточек

Модуль `github_radar/card_qa.py` — **каждая карточка проверяется до сохранения PNG**.

| Проверка | Критерий |
|----------|----------|
| Размер | Ровно 1080×1350 или 1080×1920 |
| Текст | Влезает целиком, зазор до стат-бара ≥ 10px |
| Арт | `screenshot` / `plaque` / `missing`; дичь только `screenshot` |
| Статы | Совпадают с GitHub API |
| README | ≥ 200 символов; `slide_body` ≤ 200 |

Брак → PNG удаляется, `CardQAError`, пост не получает битую карточку.

В `--dry-run` блок **`--- CARD QA ---`** с логом по каждой карточке.

---

## Структура проекта

```
treasure/
├── github_radar/
│   ├── main.py              # python -m github_radar.main [--dry-run]
│   ├── config.py
│   ├── github_source.py
│   ├── readme_fetch.py
│   ├── image_pick.py
│   ├── hype.py / prefilter.py
│   ├── curator.py           # хайп + грунтинг
│   ├── weird.py             # дичь: резерв, судья, слот
│   ├── grounding.py         # правила README-only
│   ├── card_qa.py           # QA перед сохранением PNG
│   ├── card_experiment.py   # legacy A/B counter (unused)
│   ├── publisher.py
│   ├── slides.py            # Playwright
│   ├── storage.py           # published + weird_reserve
│   ├── process_lock.py      # radar.lock, /stopall
│   └── admin_bot.py
├── templates/card.html
├── scripts/
│   ├── seed_weird.py
│   ├── render_weird_sample.py
│   ├── preview_grounded_posts.py
│   └── …
├── docs/obsidian/           # база для Obsidian
└── data/                    # gitignored
```

---

## Установка

```powershell
cd D:\treasure
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
python scripts/setup_card_assets.py
```

Заполните `.env`. Секреты в git не коммитятся.

---

## Конфигурация

### Обязательные

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_ID=-100...
GITHUB_TOKEN=
ANTHROPIC_API_KEY=
```

### Ключевые опции

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `POSTS_PER_RUN` | `3` | Постов за запуск (1 слот может уйти дичи) |
| `WEIRD_ENABLED` | `true` | Рубрика «Дичь» |
| `WEIRD_PER_DAY` | `1` | Джокеров в сутки |
| `MAKE_SLIDES` | `true` | Рендер карточек после постинга |
| `SLIDE_FORMATS` | `carousel,reels` | Форматы |
| `TELEGRAM_CARD_MODE` | `true` | Пост в Telegram как PNG-карточка (Playwright); `false` — классический текст+фото |
| `TIMEZONE` | `Europe/Moscow` | Папки слайдов, «посты сегодня» |

Полный список — `.env.example`.

---

## Запуск

```powershell
# тест: воронка + тексты + CARD QA, без Telegram
$env:PYTHONIOENCODING='utf-8'
python -m github_radar.main --dry-run

# боевой
python -m github_radar.main
```

Цикл **~5–15 мин** (зависит от README/Claude). Смотреть `data/radar.log`.

---

## Админ-бот

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_shortcut.ps1
```

| Команда | Действие |
|---------|----------|
| `/run` | Опубликовать сейчас |
| `/dry` | Dry-run с CARD QA |
| `/stop` | Остановить только бот |
| `/stopall` | Убить main + все боты, снять lock-файлы |
| `/status` | Посты сегодня, прогресс |
| `/today` | Что вышло сегодня |
| `/stats` | Всего в базе |

### Формат поста в Telegram

По умолчанию **`TELEGRAM_CARD_MODE=true`**: канал получает **PNG-коллекционную карточку** (1080×1350), а не длинный текст. Рендер — Playwright (`slides.py`), QA — `card_qa.py`. Классический режим (текст + README-скрин) — `TELEGRAM_CARD_MODE=false`.

> `github_radar/card_experiment.py` — legacy-счётчик A/B; заменён на постоянный `TELEGRAM_CARD_MODE`. Переменная `TELEGRAM_CARD_EXPERIMENT` удалена.

---

## Скрипты

| Скрипт | Назначение |
|--------|------------|
| `diagnose.py` | GitHub, README, Claude, Telegram, SQLite |
| `seed_weird.py` | Предзагрузка `weird_reserve` |
| `render_weird_sample.py` | Карта-джокер → `_samples/` |
| `preview_grounded_posts.py` | Проверка грунтинга текстов vs README |
| `render_published_slides.py` | Перерендер из БД |
| `cleanup_slides.py` | Удаление дублей слайдов |
| `render_test_card.py` | Тестовая карточка |

---

## Диагностика и типичные проблемы

```powershell
python scripts/diagnose.py
```

| Симптом | Решение |
|---------|---------|
| `SSL: CERTIFICATE_VERIFY_FAILED` | `pip install -r requirements.txt` (truststore) |
| Кириллица в консоли | `$env:PYTHONIOENCODING='utf-8'` |
| `Card QA rejected` | Текст длинный / нет скрина / неверный размер — смотреть лог |
| Текст выдуман из названия | Грунтинг в `grounding.py`; перегенерировать резерв |
| Дубли ботов | `/stopall`, перезапустить один ярлык |
| `Collected 0 repositories` | Проверить `GITHUB_TOKEN` |

---

## Лицензия

MIT
