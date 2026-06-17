# Золото GitHub (`zoloto-github`)

**«Золото GitHub» = хайп-радар + живой копирайтинг.**  
Канал — это коллекция находок с GitHub, которые хочется **попробовать сегодня же / сохранить / показать другу**.

> **Версия:** v5 FINAL · режим **9 постов/день** на ПК (Task Scheduler)

Два слоя:
- **что постить**: бренды, тренды, визуал, массовость, «дичь», скорость роста;
- **как писать**: голос «крутого знакомого», крючок в первых двух строках, результат/вау вместо технологий.

---

## Содержание

- [Что делает сервис](#что-делает-сервис)
- [Философия отбора](#философия-отбора)
- [Структура проекта](#структура-проекта)
- [Архитектура и поток данных](#архитектура-и-поток-данных)
- [Установка](#установка)
- [Настройка Telegram](#настройка-telegram)
- [Настройка GitHub Token](#настройка-github-token)
- [Настройка Anthropic API](#настройка-anthropic-api)
- [Конфигурация (.env)](#конфигурация-env)
- [Запуск](#запуск)
- [Расписание (cron / Task Scheduler)](#расписание-cron--task-scheduler)
- [Формат поста в Telegram](#формат-поста-в-telegram)
- [База данных](#база-данных)
- [Диагностика](#диагностика)
- [Типичные проблемы](#типичные-проблемы)
- [Отличие от Gitrend](#отличие-от-gitrend)
- [Ограничения API и производительность](#ограничения-api-и-производительность)
- [Критерии приёмки](#критерии-приёмки)

---

## Что делает сервис

Один запуск `python -m github_radar.main` выполняет полный цикл:

1. **Сбор** — свежие и взлетающие репозитории с GitHub Search API + парсинг Trending.
2. **Hype Score** — признаки хайпа (бренд/тренд/массовость/визуал/дичь) + freshness + velocity.
3. **Префильтр** — отсев только мусора, топ-30 по `final_score` в Claude.
4. **Курация** — Claude выбирает ~70% хайпа + до 30% «пользы с характером», пишет живые тексты.
5. **Публикация** — `sendPhoto` с **реальным скриншотом из README** (фолбэк: OG GitHub).
6. **История** — SQLite: дедуп опубликованного, снимки звёзд для velocity.

**Режим работы (v3):** **9 постов в день** = `POSTS_PER_RUN=3` × запуск **каждые 8 часов** (3 раза в сутки) на вашем ПК через Windows Task Scheduler.

**Готово =** Task Scheduler стабильно крутит цикл → ~9 самородков в день без участия человека (пока ПК включён).

---

## Философия отбора

Пост должен отвечать на вопрос: **«почему мне хочется это открыть/попробовать прямо сейчас?»**

Крючки хайпа (достаточно одного):
- **громкое имя** (Apple/NVIDIA/Google/OpenAI/знаменитость) — сразу клик;
- **едет на волне** (AI/агенты/Claude/GPT/MCP/vibe-coding/локальные LLM);
- **массовая боль** (Windows/macOS/телефон/браузер/буфер/скриншоты);
- **визуал** (реальный скриншот/гифка);
- **скорость роста** (velocity) + свежесть;
- **«дичь»** (смелое/странное/неожиданное).

Баланс: **~70% хайп / ~30% полезное с характером** (без скучных нишевых ops-CLI).

---

## Структура проекта

```
treasure/                          # корень проекта (zoloto-github)
├── github_radar/
│   ├── __init__.py
│   ├── main.py                    # точка входа, флаг --dry-run
│   ├── config.py                  # загрузка .env, валидация
│   ├── github_source.py           # Search API + Trending
│   ├── readme_fetch.py            # README через GitHub API (JSON base64)
│   ├── image_pick.py              # выбор скриншота из README
│   ├── hype.py                    # признаки + Hype Score
│   ├── prefilter.py               # отсевы, velocity, final score
│   ├── curator.py                 # Claude: отбор + тексты на русском
│   ├── publisher.py               # Telegram sendPhoto / sendMessage
│   ├── storage.py                 # SQLite
│   ├── models.py                  # dataclass Repo, Features, Candidate, PostDraft
│   ├── bot.py                     # долгоживущий админ-бот (команды)
│   ├── admin_bot.py               # обработка /run, /status, ...
│   ├── telegram_api.py
│   ├── admin_store.py
│   ├── logging_setup.py
│   └── http_ssl.py
├── launcher/
│   ├── Start-ZolotoGitHub.ps1     # запуск админ-бота (скрыто)
│   ├── Zoloto-GitHub.vbs          # без окна терминала
│   └── create-shortcut.ps1        # создаёт ярлык в корне
├── Zoloto GitHub.lnk              # ярлык (создаётся один раз, см. ниже)
├── scripts/
│   ├── diagnose.py
│   ├── run_cycle.bat              # автопостинг (Task Scheduler)
│   ├── run_bot.bat                # запасной запуск бота (терминал)
│   ├── setup_shortcut.ps1         # обёртка для create-shortcut.ps1
│   └── setup_task_scheduler.ps1
├── data/
├── .env
├── requirements.txt
└── README.md
```

---

## Архитектура и поток данных

```
http_ssl → github_source → readme_fetch → image_pick + hype → prefilter (+storage, velocity)
      → curator (Claude: отбор + тексты) → publisher (Telegram) → storage (mark_published)
```

### Модули

| Модуль | Назначение |
|--------|------------|
| `github_source.py` | GitHub Search API (несколько запросов) + парсинг `github.com/trending` |
| `readme_fetch.py` | README через `GET /repos/{owner}/{repo}/readme` (JSON + base64) |
| `image_pick.py` | Вытаскивает первый «настоящий» скриншот/гиф из README (режет бейджи/логотипы) |
| `hype.py` | Hype-признаки + формула хайп-скора |
| `prefilter.py` | Быстрые отсевы → скан README (лимит) → velocity → `final_score` |
| `curator.py` | Claude: шаг 1 — хайп-отбор (70/30), шаг 2 — текст в голосе «рекомендация от знакомого» |
| `publisher.py` | `sendPhoto` со скриншотом из README (фолбэк: OG), затем `sendMessage` |
| `storage.py` | `published`, `star_history`, дедуп по `repo_id` |

### Источники репозиториев

**GitHub Search API** (`GET /search/repositories`):

- Свежие популярные: `stars:>300 pushed:>{7д_назад}`
- Молодые взлёты: `created:>{30д_назад} stars:>150`
- По темам из `TOPICS`: `topic:{topic} pushed:>{7д_назад} stars:>150`

**GitHub Trending** (парсинг HTML, официального API нет):

- `?since=daily` и `?since=weekly`
- По каждому `owner/repo` — полные данные через `GET /repos/{owner}/{repo}`

Результаты дедуплицируются по `repo.id`.

---

## Установка

### Требования

- **Python 3.11+** (рекомендуется; протестировано на 3.14)
- Windows / Linux / macOS
- Токены: Telegram Bot, GitHub PAT, Anthropic API

### Шаги

```powershell
cd D:\treasure
python -m venv venv

# Windows
.\venv\Scripts\activate
.\venv\Scripts\pip install -r requirements.txt

# Linux/macOS
source venv/bin/activate
pip install -r requirements.txt
```

Скопируйте конфиг:

```powershell
copy .env.example .env
```

Заполните секреты в `.env` (см. ниже).

---

## Настройка Telegram

### 1. Создать бота

1. Откройте [@BotFather](https://t.me/BotFather)
2. `/newbot` → придумайте имя и username
3. Сохраните **токен** → `TELEGRAM_BOT_TOKEN`

### 2. Создать канал

Публичный или приватный — не важно. Бот должен быть **администратором** с правом **публикации сообщений**.

### 3. Узнать ID канала

Используйте **числовой ID**, не `@username`:

1. Перешлите любой пост из канала боту [@getidsbot](https://t.me/getidsbot)
2. Получите число вида `-1004344260903` → `TELEGRAM_CHANNEL_ID`

Альтернатива: после публикации тестового поста ботом посмотрите `chat.id` в [getUpdates](https://core.telegram.org/bots/api#getupdates).

> **Важно:** в `.env` указывайте именно `TELEGRAM_CHANNEL_ID=-100...`, не `@channel_name`.

---

## Настройка GitHub Token

1. [github.com/settings/tokens](https://github.com/settings/tokens)

### Вариант A — Fine-grained (рекомендуется)

- **Repository access:** Public repositories (read-only)
- **Permissions:** ничего в Account; для Repository достаточно автоматического read-доступа к публичным репо
- Generate → скопируйте `github_pat_...`

### Вариант B — Classic (проще, надёжнее для Search API)

- **Generate new token (classic)**
- Scope: **`public_repo`**
- Generate → скопируйте `ghp_...`

Токен нужен для:

- Search API (5000 req/час вместо 60 без токена)
- Метаданные репозиториев, releases, README

---

## Настройка Anthropic API

1. [console.anthropic.com](https://console.anthropic.com/) → API Keys
2. Скопируйте ключ → `ANTHROPIC_API_KEY`

Модели:

| Переменная | Значение | Когда использовать |
|------------|----------|-------------------|
| `claude-sonnet-4-6` | по умолчанию | Баланс цена/качество |
| `claude-opus-4-8` | для максимального качества отбора | Дороже, лучше курация |

---

## Конфигурация (.env)

Полный пример — в `.env.example`.

### Обязательные

```env
TELEGRAM_BOT_TOKEN=123456789:AAF...
TELEGRAM_CHANNEL_ID=-1004344260903
GITHUB_TOKEN=github_pat_...   # или ghp_...
ANTHROPIC_API_KEY=sk-ant-...
```

### Опциональные

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Модель Claude для отбора и текстов |
| `POSTS_PER_RUN` | `3` | Сколько постов за один запуск |
| `HYPE_UTILITY_RATIO` | `70` | Баланс хайпа/пользы для отбора (примерно) |
| `MIN_STARS` | `100` | Минимум звёзд у кандидата (потолка нет) |
| `STRICT_NO_LIBS` | `true` | Если true — режем библиотеки/SDK/обёртки |
| `PREFILTER_LIMIT` | `30` | Сколько кандидатов отдать в Claude |
| `README_SCAN_LIMIT` | `100` | Сколько README скачать на этапе префильтра |
| `OWNER_BOOSTLIST` | `apple,nvidia,...` | Владельцы-бренды (boost) |
| `HOT_TRENDS` | `ai,agents,mcp,...` | Горячие тренды (boost) |
| `MASS_APPEAL_KEYWORDS` | `windows,macos,...` | Массовые темы (boost) |
| `NICHE_PENALTY_KEYWORDS` | `kubernetes,terraform,...` | Нишевые ops-слова (penalty) |
| `TOPICS` | `ai,llm,agent,...` | Темы для Search API |
| `DB_PATH` | `./data/radar.sqlite` | Путь к SQLite |
| `LOG_PATH` | `./data/radar.log` | Путь к лог-файлу |

---

## Запуск

### Тест без публикации (рекомендуется сначала)

```powershell
cd D:\treasure
.\venv\Scripts\python.exe -m github_radar.main --dry-run
```

Вывод в консоль:

- воронка кандидатов с Hype-признаками + `final_score` + URL выбранной картинки;
- выбор Claude;
- готовые тексты постов.

**Ничего не публикуется.**

### Боевой запуск (постинг в канал)

```powershell
.\venv\Scripts\python.exe -m github_radar.main
```

Публикует до `POSTS_PER_RUN` постов. Между постами пауза ~2.5 сек.

### Ещё посты

Повторный запуск подберёт **новые** репозитории — уже опубликованные отфильтруются из БД (`storage.is_published`).

### Сколько ждать

Полный цикл занимает **~5–10 минут**:

| Этап | Время |
|------|-------|
| Сбор 500+ репо (Search + Trending) | ~2–3 мин |
| Скан 100 README + releases | ~2–3 мин |
| Claude: отбор + 3 текста | ~1–3 мин |
| Telegram: 3 поста | ~10 сек |

Прогресс README-скана пишется в `data/radar.log`:

```
README scan progress: 50/100
```

**Не прерывайте процесс** до строки `Cycle complete: published N posts`.

---

## Админ-бот (команды в Telegram)

Как в «Радаре будущего»: отдельный процесс слушает личку бота и при **запуске** присылает список команд.

### 1. Укажите свой Telegram ID в `.env`

Узнайте ID через [@userinfobot](https://t.me/userinfobot) или `/start` у бота (покажет ID, если ещё не настроен):

```env
TELEGRAM_ADMIN_USER_ID=123456789
```

### 2. Запустите админ-бота

**Рекомендуется (как Gitrend / Jarvis):** один раз создать ярлык, потом двойной клик без терминала.

```powershell
cd D:\treasure
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_shortcut.ps1
```

Появится **`D:\treasure\Zoloto GitHub.lnk`** — двойной клик запускает админ-бота в фоне. Лог: `data\radar.log`.  
Ярлык можно положить в автозагрузку Windows (`Win+R` → `shell:startup`).

Альтернатива в терминале:

```powershell
cd D:\treasure
.\venv\Scripts\python.exe -m github_radar.bot
```

Или `scripts\run_bot.bat` (видно окно консоли).

При старте в личку придёт **✅ Бот запущен** и список команд. В меню Telegram (кнопка «/») тоже появятся команды.

### Команды

| Команда | Действие |
|---------|----------|
| `/start` | Регистрация админа + список команд |
| `/status` | Посты сегодня, всего в базе, режим |
| `/run` | Опубликовать сейчас (~5–10 мин) |
| `/dry` | Тест без канала |
| `/today` | Что вышло сегодня |
| `/stats` | Всего опубликовано |
| `/stop` | Остановить бот (запуск снова — `Zoloto GitHub.lnk`) |
| `/help` | Список команд |

**Важно:** админ-бот и Task Scheduler — разные процессы. Планировщик постит сам по расписанию; бот нужен для ручного `/run` и статуса. Держите **`Zoloto GitHub.lnk`** в автозагрузке Windows, если хотите команды всегда под рукой.

---

## Расписание — режим 9 постов/день (Windows Task Scheduler)

**Формула:** `POSTS_PER_RUN=3` × 3 запуска в сутки (каждые 8 ч) = **~9 постов/день**.

Один запуск = один полный цикл (~5–10 мин). Не прерывать до `Cycle complete: published N posts`.

### Запуск вручную

```powershell
cd D:\treasure
.\venv\Scripts\python.exe -m github_radar.main --dry-run   # тест
.\venv\Scripts\python.exe -m github_radar.main             # боевой (3 поста)
```

### Обёртка `scripts/run_cycle.bat`

Для планировщика — лог в `data\cron.log`:

```bat
@echo off
chcp 65001 >nul
cd /d D:\treasure
D:\treasure\venv\Scripts\python.exe -m github_radar.main >> data\cron.log 2>&1
```

### Быстрая настройка Task Scheduler

Один раз в PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File D:\treasure\scripts\setup_task_scheduler.ps1
```

Создаёт задачу **«Zoloto GitHub»**: ежедневно с 09:00, повтор каждые **8 часов** (~09:00, 17:00, 01:00).

### Ручная настройка Task Scheduler

| Поле | Значение |
|------|----------|
| Имя задачи | `Zoloto GitHub` |
| Триггер | Ежедневно, начало 09:00, повтор **каждые 8 часов**, бессрочно |
| Действие | Program: `D:\treasure\scripts\run_cycle.bat` |
| Start in | `D:\treasure` |
| Условия | Снять «Только при питании от сети» (ноутбук) |
| Параметры | Включить **«Выполнять задачу как можно скорее после пропуска»** |

### ⚠️ Ограничение «на моём ПК»

- Задача срабатывает, **только если ПК включён и не спит** в момент триггера.
- Выключили / уснули → запуск пропущен (догонится после включения, если стоит галка выше).
- Для стабильных 9/день: в **Параметры питания Windows** отключить сон на время работы канала.
- Для 24/7 независимо от ПК — перенос на VPS с тем же `run_cycle` под cron (вне текущей сборки).

### Linux/macOS (cron)

```cron
0 */8 * * * cd /path/to/treasure && /path/to/venv/bin/python -m github_radar.main >> data/cron.log 2>&1
```

---

## Формат поста в Telegram

### Картинка

OG-превью GitHub:

```
https://opengraph.githubassets.com/1/{owner}/{repo}
```

### Caption (HTML)

```html
<b>{owner}/{repo}</b>

{text_ru}

⭐ {stars}  ·  🍴 {forks}  ·  {language}

<a href="{html_url}">Открыть на GitHub</a>
#cli #rust
```

- Лимит caption у `sendPhoto` — **1024 символа**; текст обрезается при необходимости.
- При недоступной картинке — фолбэк `sendMessage`.

---

## Hype Score (v5)

Сервис ранжирует кандидатов по «хайпу» (бренд/тренд/массовость/визуал/дичь) + скорости роста.

### Признаки (из README + метаданных)

| Признак | Как детектится |
|---------|----------------|
| `brand_boost` | `owner_login` ∈ `OWNER_BOOSTLIST` |
| `trend_riding` | совпадения по `HOT_TRENDS` в name/desc/topics/README |
| `has_real_screenshot` | найден реальный скриншот в README (`image_pick`) |
| `has_gif` | `.gif` или asciinema |
| `mass_appeal` | совпадения по `MASS_APPEAL_KEYWORDS` |
| `niche_ops` | совпадения по `NICHE_PENALTY_KEYWORDS` (и при этом не consumer) |
| `looks_like_library` | library/sdk/framework/wrapper/... |
| `is_list_or_learning` | awesome/roadmap/course/book/spec |

### Формула

```
hype =
    +4 brand_boost   +3 trend_riding   +3 has_real_screenshot
    +2 has_gif       +2 mass_appeal
    −3 niche_ops     −4 looks_like_library   −5 is_list_or_learning

freshness = +3 (<30 дней) | +2 (<120 дней) | 0
final = hype*1.5 + velocity_rank*1.0 + freshness*0.5
```

### Жёсткие отсевы (только мусор)

- уже публиковалось;
- fork / archived;
- описание < 15 символов;
- `stars < MIN_STARS`;
- `is_list_or_learning`;
- `looks_like_library` если `STRICT_NO_LIBS=true`.

---

## База данных

SQLite: `data/radar.sqlite`

```sql
CREATE TABLE published (
    repo_id      INTEGER PRIMARY KEY,
    full_name    TEXT NOT NULL,
    published_at TEXT NOT NULL,
    message_id   INTEGER
);

CREATE TABLE star_history (
    repo_id INTEGER NOT NULL,
    stars   INTEGER NOT NULL,
    ts      TEXT NOT NULL
);
```

Проверить опубликованное:

```powershell
.\venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('data/radar.sqlite'); print(list(c.execute('SELECT full_name, published_at FROM published')))"
```

---

## Диагностика

Скрипт проверяет все компоненты **без публикации**:

```powershell
.\venv\Scripts\python.exe scripts\diagnose.py
```

Проверяет:

1. `.env` — все ключи на месте
2. GitHub Search API
3. README через `api.github.com` (без редиректа на `raw.githubusercontent.com`)
4. Anthropic API (тестовый запрос к модели)
5. Telegram: `getMe` + `getChat` по `TELEGRAM_CHANNEL_ID`
6. SQLite: количество опубликованных

---

## Типичные проблемы

### Канал пустой после запуска

| Причина | Решение |
|---------|---------|
| Процесс прерван до конца | Дождаться `Cycle complete` в логе (~5–10 мин) |
| SSL-ошибки в логе | Убедиться, что `truststore` установлен (`pip install -r requirements.txt`) |
| `Collected 0 repositories` | Проверить `GITHUB_TOKEN`, запустить `diagnose.py` |
| Параллельные запуски | Не запускать два `main` одновременно |

### `SSL: CERTIFICATE_VERIFY_FAILED` (Windows)

Python по умолчанию не доверяет корпоративным/Avast-сертификатам.  
Проект использует **`truststore`** — подключает хранилище сертификатов Windows.  
Убедитесь, что пакет установлен и `http_ssl.py` вызывается при старте.

### Avast блокирует `raw.githubusercontent.com`

**Причина:** старые версии кода или GitHub API с заголовком `Accept: application/vnd.github.raw` редиректит на `raw.githubusercontent.com`.

**Решение (уже в проекте):** README качается через JSON + base64 с `api.github.com`, `follow_redirects=False`.

Если Avast всё равно ругается — проверьте, что запущена **актуальная** версия `readme_fetch.py`, а не старый процесс.

### `TELEGRAM_CHANNEL_ID must be a number`

Используйте `-100...`, не `@username`.

### Бот не может постить

- Бот — **админ** канала с правом публикации
- `getChat` в `diagnose.py` должен вернуть `ok: true`

### Claude вернул пустой отбор

Скрипт не падает — берёт топ по `final_score`. Смотрите `data/radar.log`.

### Повторные посты

Не должны появляться: дедуп по `repo_id` в SQLite. Если появились — проверьте, не удаляли ли `data/radar.sqlite`.

---

## Отличие от Gitrend

| | **Золото GitHub** (этот проект) | **Gitrend** |
|--|--------------------------------|-------------|
| Язык | Python 3.11+ | TypeScript / Next.js |
| Цель | Автопостинг в Telegram | Локальный дашборд + radar |
| Отбор | Hype Score + Claude (хайп+дичь, 70/30) | Рост звёзд, AI-саммари |
| README | GitHub API JSON (base64) | `fetch()` + `api.github.com` |
| SSL на Windows | `truststore` (нужен для Python) | Node.js использует Schannel — проблем нет |
| Запуск | `python -m github_radar.main` | `npm run dev` / radar-скрипты |

Проекты **независимы** — код Gitrend не импортируется.

---

## Ограничения API и производительность

### GitHub rate limit

- С токеном: **5000 req/час**, Search — **30 req/мин**
- При `403/429` — читается `X-RateLimit-Reset`, ожидание или прерывание с логом
- README/releases — только для кандидатов после быстрых отсевов
- **Не запускать чаще ~1 раза в 4 часа** (режим 8 ч безопасен)

### Claude недоступен

При ошибке генерации текста репо **не публикуется** (без фолбэка на английское описание). Смотрите `data/radar.log`.

### Идемпотентность

- Дедуп по `repo.id` при сборе
- Перед публикацией повторная проверка `is_published`

### Пустая воронка

Скрипт корректно завершается, ничего не постит, пишет в лог.

---

## Критерии приёмки (v5)

- [x] `--dry-run` печатает Hype-признаки, URL картинки, выбор Claude и тексты (без публикации)
- [x] В выборке есть хайп: бренды / тренды / массовость / визуал / «дичь» (высокие звёзды не режутся)
- [x] У большинства постов картинка — реальный скриншот из README (иначе OG fallback)
- [x] Баланс ~70/30: 2 хайп + 1 полезное с характером (без скучных нишевых ops-CLI)
- [x] Тексты звучат как рекомендация «от знакомого»: крючок в первых двух строках, результат/вау, без аналитических оборотов
- [x] Повторный запуск не дублирует репо
- [x] `diagnose.py` проверяет GitHub/README/Anthropic/Telegram/SQLite + пример `image_pick`
- [x] SSL + Avast: truststore + README через `api.github.com` (JSON base64)
- [x] Rate limit / пустая воронка / Claude down — не падает, не постит мусор
- [ ] Task Scheduler: 3 запуска/сутки → ~9 постов/день (настроить на ПК)

---

## Лицензия

MIT
