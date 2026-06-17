# Отчёт по проблемам — Золото GitHub (`zoloto-github`)

Документ фиксирует все инциденты, возникшие при разработке и первом запуске проекта (июнь 2026), их причины, симптомы и принятые решения.

---

## Сводка

| # | Проблема | Критичность | Статус |
|---|----------|-------------|--------|
| 1 | SSL `CERTIFICATE_VERIFY_FAILED` на Windows | Блокер | ✅ Исправлено |
| 2 | Avast блокирует `raw.githubusercontent.com` | Блокер | ✅ Исправлено |
| 3 | Пустой Telegram-канал после запуска | Высокая | ✅ Объяснено + исправлено |
| 4 | Прерванные фоновые процессы | Высокая | ⚠️ Операционная |
| 5 | Сломанный venv (`D:\stream`, Python 3.12) | Средняя | ℹ️ Другой проект |
| 6 | Долгий цикл без видимого прогресса | Средняя | ✅ Улучшено |
| 7 | Параллельные запуски `main` | Средняя | ⚠️ Операционная |
| 8 | Fine-grained GitHub token — нет блока Permissions | Низкая | ℹ️ Документировано |
| 9 | `UnicodeEncodeError` в `--help` на Windows | Низкая | ✅ Исправлено |
| 10 | Секреты в `.env.example` | Безопасность | ✅ Очищено |

**Итог:** после исправлений #1, #2, #6 боевой запуск успешно опубликовал **3 поста** в канал `-1004344260903`.

---

## 1. SSL: `CERTIFICATE_VERIFY_FAILED`

### Симптомы

```
[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate
```

В логе `data/radar.log`:

- все запросы GitHub Search API падали;
- Trending не парсился;
- `Collected 0 unique repositories`;
- публикации не было.

### Причина

Python 3.14 на Windows по умолчанию использует пакет сертификатов **certifi**, а не системное хранилище Windows. На машине с Avast (или корпоративным MITM-прокси) корневые сертификаты есть в Windows, но **отсутствуют в certifi** — TLS-рукопожатие ломается.

### Почему в Gitrend этого не было

Gitrend — **Node.js / Next.js**. `fetch()` в Node на Windows использует **Schannel** (системные сертификаты Windows). Avast-сертификат уже доверен системой → запросы проходят без доп. настройки.

### Решение

Добавлен модуль `github_radar/http_ssl.py` с пакетом **`truststore`**:

- при старте `main.py` вызывается `ssl_verify()`;
- `truststore.inject_into_ssl()` подключает хранилище Windows к Python SSL;
- все `httpx.Client` используют `verify=ssl_verify()`.

Зависимость добавлена в `requirements.txt`:

```
truststore>=0.10.0
certifi>=2024.0.0
```

### Проверка

```powershell
.\venv\Scripts\python.exe -c "import truststore; truststore.inject_into_ssl(); import httpx; print(httpx.get('https://api.github.com').status_code)"
# Ожидается: 200
```

---

## 2. Avast блокирует `raw.githubusercontent.com`

### Симптомы

Всплывающее окно Avast:

```
Threat secured
We prevented your connection to raw.githubusercontent.com
Threat category: MD:HttpRequest-inf [Susp]
URL: https://raw.githubusercontent.com/jaywcjlove/awesome-mac/master/README.md
Process: cursor.exe / python.exe
```

README-скан останавливался или шёл с ошибками. Канал оставался пустым.

### Причина (двойная)

**Версия 1 (исходный код):** `readme_fetch.py` напрямую ходил на:

```
https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md
```

Avast классифицирует такие запросы как подозрительные (`HttpRequest-inf`).

**Версия 2 (ложное «исправление»):** переход на GitHub API с заголовком:

```
Accept: application/vnd.github.raw
```

GitHub **редиректит** на `raw.githubusercontent.com`. При `follow_redirects=True` httpx всё равно попадал на заблокированный домен — Avast снова срабатывал.

### Почему в Gitrend этого не было

Gitrend тоже использует `Accept: application/vnd.github.raw`, но:

- Node.js `fetch` обрабатывается Avast иначе, чем Python/httpx;
- либо запросы шли в контексте dev-сервера, не попадая под то же правило.

Для Python-проекта нужен **явный обход** raw-домена.

### Решение (финальное)

`readme_fetch.py` переведён на **JSON API без редиректов**:

```
GET https://api.github.com/repos/{owner}/{repo}/readme
Accept: application/vnd.github+json
follow_redirects=False
```

Ответ декодируется из base64 локально — **ни одного запроса к `raw.githubusercontent.com`**.

### Рекомендация пользователю

Если Avast снова покажет alert на `raw.githubusercontent.com`:

1. Убедиться, что запущена **актуальная** версия кода (не старый процесс).
2. При необходимости добавить исключение для `python.exe` из `D:\treasure\venv\` — но после фикса это не должно требоваться.

---

## 3. Пустой Telegram-канал после запуска

### Симптомы

Пользователь запускал `python -m github_radar.main`, но в канале `-1004344260903` не появлялось постов.

### Причины (цепочка)

| Этап | Что происходило |
|------|-----------------|
| Запуски 1–2 (04:17) | SSL-ошибка → 0 репозиториев → немедленный выход |
| Запуск 3 (04:18) | SSL починен → 525 репо собрано → **процесс прерван** на этапе README (до Claude/Telegram) |
| Запуски 4–6 | Параллельные прерывания, Avast на raw.githubusercontent.com |
| Запуск 7 (04:26) | Все фиксы применены → цикл дошёл до конца → **3 поста опубликованы** |

### Дополнительный фактор

В БД `published` было **0 записей** до успешного запуска — дедуп не мешал, проблема была именно в **незавершённом пайплайне**.

### Решение

- Исправить SSL и README (см. #1, #2).
- **Не прерывать** процесс 5–10 минут до строки в логе:

  ```
  Cycle complete: published 3 posts
  ```

---

## 4. Прерванные фоновые процессы

### Симптомы

Фоновые shell-задачи в Cursor завершались с кодом `4294967295` (Windows: процесс убит, ≈ `-1`).

Задачи:

- `583931` — Run live publish cycle with SSL fix
- `418625` — Run live publish cycle after Avast fix
- `453287` — Run full publish cycle with logging

### Причина

Пользователь или IDE **backgrounded/killed** долгий процесс до завершения. Цикл не доходил до `curator` и `publisher`.

### Решение

- Запускать вручную в терминале и ждать завершения.
- Следить за прогрессом в `data/radar.log`.
- Успешный запуск: задача `39622` — exit code 0, 3 поста в канале.

---

## 5. Сломанный venv в `D:\stream`

### Симптомы

```
Failed to find real location of C:\Python312\python.exe
```

При запуске `D:\stream\venv\Scripts\pip.exe`.

### Причина

Venv создан под **Python 3.12** (`C:\Python312\`), который удалён или перемещён. На машине сейчас **Python 3.14** (`C:\Python314\`) и **3.11** (через uv).

Папка `D:\stream` на диске **не существует** — команда `cd D:\stream` падала, venv пересоздавался в `D:\treasure\venv`.

### Решение

```powershell
cd D:\treasure
Remove-Item -Recurse -Force venv   # если нужно пересоздать
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
```

К проекту «Золото GitHub» относится `D:\treasure`, не `D:\stream`.

---

## 6. Долгий цикл без видимого прогресса

### Симптомы

После `Collected 525 unique repositories` в логе долго ничего не происходило. Казалось, что скрипт завис.

### Причина

Исходная логика пыталась скачать README для **всех** кандидатов после быстрых отсевов (~400+). Каждый README + опционально releases = 2 API-запроса + паузы → **15–20+ минут** без логов.

### Решение

Изменения в `prefilter.py`:

1. **Быстрый отсев** по метаданным (без README) — библиотеки, awesome-листы.
2. Сортировка по звёздам, скан только топ **`README_SCAN_LIMIT`** (по умолчанию 100).
3. **Прогресс в логе** каждые 10 README:

   ```
   README scan progress: 50/100
   ```

Новая переменная: `README_SCAN_LIMIT=100` в `.env`.

Типичное время цикла после оптимизации: **5–10 минут**.

---

## 7. Параллельные запуски `main`

### Симптомы

Несколько процессов `python.exe` одновременно (PID 33828, 39332 и др.) — все стартовали в ~04:26.

### Причина

Многократный запуск из Cursor, пока предыдущий цикл ещё шёл.

### Последствия

- Лишняя нагрузка на GitHub API (rate limit);
- дублирующие записи в `star_history`;
- путаница в логах.

### Решение

Перед новым запуском убедиться, что предыдущий завершился:

```powershell
Get-Process python -ErrorAction SilentlyContinue
# при необходимости остановить старые процессы treasure
```

Запускать **один** экземпляр за раз.

---

## 8. Fine-grained GitHub token — «нет блока Repository permissions»

### Симптомы

При создании токена на github.com при выборе **Public repositories (read-only)** не отображается отдельный блок Repository permissions.

### Причина

Это **нормальное поведение** GitHub UI. Для public read-only доступ включается автоматически.

### Решение

- Account permissions — **ничего не добавлять**.
- Нажать **Generate token**.
- Если Search API не работает — fallback на **classic token** с scope `public_repo`.

---

## 9. `UnicodeEncodeError` в `--help` (Windows)

### Симптомы

```
UnicodeEncodeError: 'charmap' codec can't encode characters ...
```

При `python -m github_radar.main --help`.

### Причина

`argparse` description содержал кириллицу (`Золото GitHub`), консоль Windows (cp1252) не смогла вывести текст.

### Решение

Description в `main.py` заменён на ASCII: `Zoloto GitHub radar cycle`.

На работу пайплайна не влияло.

---

## 10. Секреты в `.env.example`

### Симптомы

В `.env.example` оказались реальные токены (Telegram, GitHub, Anthropic) вместо плейсхолдеров.

### Риск

Случайный коммит в git → утечка ключей.

### Решение

`.env.example` очищен до пустых плейсхолдеров. Секреты только в `.env` (в `.gitignore`).

### Рекомендация

Если токены могли попасть в git — **отозвать и перевыпустить** все три ключа.

---

## 11. Telegram: `@username` vs числовой ID

### Симптомы

Пользователь изначально настраивал `TELEGRAM_CHANNEL=@your_channel`.

### Решение

Переведено на `TELEGRAM_CHANNEL_ID=-1004344260903`:

- валидация в `config.py` отклоняет `@username`;
- backward compat: читается старый `TELEGRAM_CHANNEL`, если новый ключ пуст.

Проверка: `diagnose.py` → `getChat` возвращает `ok: true`, `type: channel`.

---

## Хронология инцидентов

```
04:17  Запуск #1–2  → SSL fail → 0 repos → exit
04:18  Запуск #3    → truststore → 525 repos → ПРЕРВАН на README
04:21  Запуск #4    → 525 repos → ПРЕРВАН на README 30/100
04:25  Запуск #5    → ПРЕРВАН на Search
04:26  Запуск #6–7  → README JSON fix → 100/100 → Claude → Telegram
04:29  ✅ Published 3 posts
04:31  Запуск #8    → запрошен пользователем (ещё 3 поста)
```

---

## Диагностический чеклист

Если канал снова пустой:

```powershell
cd D:\treasure

# 1. Все API живы?
.\venv\Scripts\python.exe scripts\diagnose.py

# 2. Что в логе?
Get-Content data\radar.log -Tail 30

# 3. Уже что-то опубликовано?
.\venv\Scripts\python.exe -c "import sqlite3; print(sqlite3.connect('data/radar.sqlite').execute('select count(*) from published').fetchone())"

# 4. Тест без постинга
.\venv\Scripts\python.exe -m github_radar.main --dry-run

# 5. Боевой (ждать 5–10 мин!)
.\venv\Scripts\python.exe -m github_radar.main
```

---

## Изменённые файлы (в рамках исправлений)

| Файл | Что сделано |
|------|-------------|
| `github_radar/http_ssl.py` | **Создан** — truststore для Windows SSL |
| `github_radar/readme_fetch.py` | JSON base64 вместо raw.githubusercontent.com |
| `github_radar/prefilter.py` | Быстрый отсев, README_SCAN_LIMIT, прогресс-логи |
| `github_radar/config.py` | `TELEGRAM_CHANNEL_ID`, `README_SCAN_LIMIT` |
| `github_radar/main.py` | `ssl_verify()` при старте |
| `requirements.txt` | `truststore`, `certifi` |
| `scripts/diagnose.py` | **Создан** — проверка всех компонентов |
| `.env.example` | Очищен от секретов, добавлены новые ключи |
| `README.md` | Полная документация |

---

## Открытые операционные риски

| Риск | Митигация |
|------|-----------|
| GitHub rate limit при частых запусках | Не чаще 1 раза в 2–4 часа; паузы в коде |
| Avast обновит сигнатуры для `api.github.com` | Маловероятно; diagnose.py покажет сбой |
| Claude API недоступен / лимит | Лог ошибки; fallback на топ по score без AI-текста — **не реализован** |
| OG-картинка GitHub недоступна | Фолбэк `sendMessage` в `publisher.py` |
| Прерывание длинного цикла | Смотреть `radar.log`, не убивать процесс |

---

*Документ сгенерирован по результатам сессии разработки и первого боевого запуска. Актуален для состояния репозитория `D:\treasure` на 16.06.2026.*
