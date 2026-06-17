# Золото GitHub

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Автопилот для Telegram-канала про хайповые репозитории GitHub** — с коллекционными карточками для Instagram.

Канал отвечает на один вопрос: *«Почему мне хочется открыть это прямо сейчас?»*  
Посты пишет Claude в голосе «крутого знакомого», картинки — реальные скриншоты из README (или OG-карточка GitHub).

**Режим:** `POSTS_PER_RUN=3` × 3 запуска в сутки ≈ **9 постов/день** (Task Scheduler / cron).

---

## Содержание

- [Возможности](#возможности)
- [Как это работает](#как-это-работает)
- [Коллекционные карточки (Instagram)](#коллекционные-карточки-instagram)
- [Структура проекта](#структура-проекта)
- [Установка](#установка)
- [Конфигурация](#конфигурация)
- [Запуск](#запуск)
- [Админ-бот](#админ-бот)
- [Расписание](#расписание)
- [Скрипты](#скрипты)
- [Диагностика и типичные проблемы](#диагностика-и-типичные-проблемы)
- [Лицензия](#лицензия)

---

## Возможности

| Слой | Что делает |
|------|------------|
| **Радар** | GitHub Search + Trending → hype score (бренд, тренд, визуал, velocity) |
| **Куратор** | Claude отбирает ~70% хайпа / ~30% пользы, пишет пост + текст карточки |
| **Паблишер** | Telegram `sendPhoto` (README-скрин → OG fallback) |
| **Карточки** | Playwright рендер PNG: карусель 4:5 + reels 9:16, редкость, нумерация |

Отсев мусора: форки, архивы, awesome-листы, SDK/библиотеки, пустые терминалы, YouTube-превью, широкие баннеры.

---

## Как это работает

```
GitHub Search + Trending
    → README + image_pick + hype
    → prefilter (velocity, final_score)
    → curator (Claude: отбор + тексты)
    → publisher (Telegram)
    → slides (Playwright PNG)   [если MAKE_SLIDES=true]
    → SQLite (дедуп, история звёзд, карточки)
```

**Hype score** учитывает: бренд владельца, горячие тренды, массовую аудиторию, скриншот в README, gif, velocity, свежесть. Штрафы — за ops-нишу, библиотеки, подборки.

---

## Коллекционные карточки (Instagram)

После каждого боевого цикла (или вручную) генерируются PNG для ленты и Stories/Reels.

### Форматы

| Формат | Размер | Куда | Папка |
|--------|--------|------|-------|
| **carousel** | **1080×1350** (4:5) | Лента Instagram | `data/instagram/carousel/` |
| **reel** | **1080×1920** (9:16) | Reels / Stories | `data/instagram/reels/` |

Размеры **жёстко фиксированы** — после рендера проверяется PIL; неверный размер = ошибка.

Карусель: safe-zone **70px** сверху (лого, редкость) и снизу (тэглайн, @handle), `overflow: hidden`, контент ужимается внутрь 1350px.

### Структура папок

```
data/instagram/
├── carousel/{YYYY-MM-DD}/{HH-MM}/owner_repo_carousel.png
├── reels/{YYYY-MM-DD}/{HH-MM}/owner_repo_reel.png
├── _cache/images/          # кэш скачанных картинок
└── _samples/               # тестовые рендеры (не боевые)
```

Дата и время — в часовом поясе `TIMEZONE` (IANA). Все карточки **одного батча** попадают в одну папку `{дата}/{HH-MM}`.

### Дизайн карточки

- Шапка: бренд «Золото GitHub», бейдж редкости (звёзды), `#номер`
- Арт-окно 16:10, `object-fit: cover`, привязка к верху
- `slide_headline` + `slide_body` (отдельно от текста поста)
- 3 буллета, стат-бар (звёзды / форки / issues), футер

### Выбор картинки (`image_pick.py`)

Цепочка: сохранённый URL → лучший скрин из README → OG GitHub.

Отсекается: shields/badges, YouTube, баннеры aspect ≥2.5, почти пустые терминалы (`has_rich_visual_content`, `is_good_card_art`).

### Перерендер

```powershell
# последние N карточек
python scripts/render_published_slides.py --last 3

# конкретные номера
python scripts/render_published_slides.py --card 5,6,7
```

### Уборка дублей

```powershell
python scripts/cleanup_slides.py
python scripts/cleanup_slides.py --remove-cyrillic   # удалить legacy карусель/рилс
```

---

## Структура проекта

```
treasure/
├── github_radar/
│   ├── main.py              # python -m github_radar.main [--dry-run]
│   ├── config.py            # .env, ENV_KNOWN, валидация
│   ├── github_source.py     # Search API + Trending
│   ├── readme_fetch.py      # README через API (base64, без raw redirect)
│   ├── image_pick.py        # скриншот из README + визуальный фильтр
│   ├── hype.py              # признаки и hype score
│   ├── prefilter.py         # воронка, velocity, final_score
│   ├── curator.py           # Claude: отбор + slide_headline/body
│   ├── publisher.py         # Telegram
│   ├── slides.py            # Playwright рендер карточек
│   ├── timeutil.py          # TIMEZONE, папки слайдов
│   ├── storage.py           # SQLite
│   ├── bot.py / admin_bot.py
│   └── http_ssl.py          # truststore для Windows
├── templates/
│   ├── card.html            # шаблон карточки
│   └── assets/              # шрифты, logo, paper (setup_card_assets)
├── scripts/
│   ├── diagnose.py
│   ├── render_published_slides.py
│   ├── cleanup_slides.py
│   ├── render_test_card.py
│   ├── setup_card_assets.py
│   ├── run_cycle.bat
│   └── setup_task_scheduler.ps1
├── launcher/                # ярлык админ-бота без терминала
├── data/                    # gitignored: sqlite, логи, instagram/
├── .env.example
└── requirements.txt
```

---

## Установка

**Требования:** Python 3.11+, токены Telegram / GitHub / Anthropic.

```powershell
cd D:\treasure
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
python scripts/setup_card_assets.py
```

Заполните `.env` (см. ниже). Секреты в git не коммитятся.

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
| `POSTS_PER_RUN` | `3` | Постов за один запуск |
| `HYPE_UTILITY_RATIO` | `70` | Доля хайпа в отборе Claude |
| `MIN_STARS` | `100` | Минимум звёзд |
| `STRICT_NO_LIBS` | `true` | Резать библиотеки/SDK |
| `MAKE_SLIDES` | `true` | Рендерить карточки после постинга |
| `SLIDE_FORMATS` | `carousel,reels` | Форматы (алиас `reel` → папка `reels`) |
| `SLIDE_DIR` | `./data/instagram` | Корень слайдов |
| `TIMEZONE` | `Europe/Moscow` | Папки слайдов и «посты сегодня» |
| `TELEGRAM_ADMIN_USER_ID` | — | ID для админ-бота |

Полный список — в `.env.example`. Неизвестные ключи в `.env` логируются как stale (`ENV_KNOWN` в `config.py`).

### Telegram

1. [@BotFather](https://t.me/BotFather) → токен бота  
2. Канал → бот **админ** с правом публикации  
3. ID канала: [@getidsbot](https://t.me/getidsbot) → `TELEGRAM_CHANNEL_ID=-100...`

### GitHub token

[Settings → Tokens](https://github.com/settings/tokens) — classic с `public_repo` или fine-grained read на публичные репо.

---

## Запуск

```powershell
# тест: воронка + тексты, без Telegram и слайдов в канал
python -m github_radar.main --dry-run

# боевой: постинг + карточки
python -m github_radar.main
```

Цикл **~5–10 мин**. Не прерывать до `Cycle complete: published N posts` в `data/radar.log`.

Повторный запуск не дублирует репо (SQLite `published`).

---

## Админ-бот

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_shortcut.ps1
# двойной клик по Zoloto GitHub.lnk
```

| Команда | Действие |
|---------|----------|
| `/run` | Опубликовать сейчас |
| `/dry` | Тест без канала |
| `/status` | Посты сегодня, режим |
| `/today` | Что вышло сегодня |
| `/stats` | Всего в базе |

---

## Расписание

**9 постов/день:** Task Scheduler, `scripts/run_cycle.bat`, повтор каждые **8 часов**.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_task_scheduler.ps1
```

Linux cron:

```cron
0 */8 * * * cd /path/to/treasure && ./venv/bin/python -m github_radar.main >> data/cron.log 2>&1
```

ПК должен быть включён в момент триггера (или «выполнить при пропуске» в планировщике).

---

## Скрипты

| Скрипт | Назначение |
|--------|------------|
| `diagnose.py` | GitHub, README, Claude, Telegram, SQLite — без публикации |
| `render_published_slides.py` | Перерендер карточек из БД |
| `cleanup_slides.py` | Удаление дублей и legacy-папок |
| `render_test_card.py` | Одна тестовая карточка → `_samples/` |
| `setup_card_assets.py` | Шрифты и ассеты шаблона |

---

## Диагностика и типичные проблемы

```powershell
python scripts/diagnose.py
```

| Симптом | Решение |
|---------|---------|
| `SSL: CERTIFICATE_VERIFY_FAILED` | `pip install -r requirements.txt` (truststore) |
| Канал пустой после запуска | Дождаться конца цикла; смотреть `data/radar.log` |
| `Collected 0 repositories` | Проверить `GITHUB_TOKEN` |
| Карусель обрезается в Instagram | PNG должен быть ровно 1080×1350; перерендер |
| Слайды в «не той» дате | Проверить `TIMEZONE` |
| Stale keys в `.env` | Удалить ключи из warning в логе |

---

## Лицензия

MIT
