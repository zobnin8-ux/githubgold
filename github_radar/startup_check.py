"""Startup health check with Telegram progress bar."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import httpx

from github_radar.config import Config, find_stale_env_vars
from github_radar.http_ssl import ssl_verify
from github_radar.progress import _bar
from github_radar.storage import Storage
from github_radar.telegram_api import TelegramApi

logger = logging.getLogger("github_radar.startup_check")

STARTUP_PHASES = ("bot", "github", "claude", "database", "ready")

PHASE_LABELS = {
    "bot": "Telegram бот",
    "github": "GitHub API",
    "claude": "Claude API",
    "database": "База данных",
    "ready": "Готов к работе",
}


def _format_startup(
    active: str,
    *,
    results: dict[str, bool | None],
    details: dict[str, str],
    failed: bool = False,
) -> str:
    title = "❌ Запуск — есть проблемы" if failed else "🔄 Запуск бота"
    lines = [title, ""]
    order = list(STARTUP_PHASES)
    active_idx = order.index(active) if active in order else len(order)

    for i, key in enumerate(order):
        label = PHASE_LABELS[key]
        state = results.get(key)
        if state is True:
            lines.append(f"✅ {label}")
            if details.get(key):
                lines.append(f"   {details[key]}")
        elif state is False:
            lines.append(f"❌ {label}")
            if details.get(key):
                lines.append(f"   {details[key]}")
        elif key == active:
            step = i + 1
            lines.append(
                f"▶️ {_bar(step, len(order))}  {label}"
                + (f" — {details[key]}" if details.get(key) else "")
            )
        else:
            lines.append(f"░░░░░░░░░░  {label}  —")
    return "\n".join(lines)


def _format_ready(config: Config, details: dict[str, str]) -> str:
    weird = (
        f"Дичь: {'вкл' if config.weird_enabled else 'выкл'}"
        + (f", резерв {details.get('weird_reserve', '?')}" if config.weird_enabled else "")
    )
    return (
        "✅ Золото GitHub — бот жив и готов\n\n"
        f"@{details.get('bot_user', 'bot')} · канал OK\n"
        f"В базе: {details.get('published', '0')} репо · сегодня: {details.get('today', '0')}\n"
        f"{weird}\n\n"
        "Команды:\n"
        "/status — статус и посты сегодня\n"
        "/run — постинг (прогресс-бар)\n"
        "/dry — тест без канала\n"
        "/today — что вышло сегодня\n"
        "/stats — всего в базе\n"
        "/stop — остановить бот\n"
        "/stopall — полная остановка\n"
        "/help — полный список"
    )


def _check_bot(config: Config) -> tuple[bool, str]:
    try:
        client = httpx.Client(timeout=15.0, verify=ssl_verify())
        try:
            me = client.get(
                f"https://api.telegram.org/bot{config.telegram_bot_token}/getMe"
            ).json()
            if not me.get("ok"):
                return False, me.get("description", "getMe failed")
            user = me["result"].get("username", "?")

            ch = client.get(
                f"https://api.telegram.org/bot{config.telegram_bot_token}/getChat",
                params={"chat_id": config.telegram_channel_id},
            ).json()
            if not ch.get("ok"):
                return False, ch.get("description", "channel unreachable")
            title = ch["result"].get("title", "?")
            return True, f"@{user} · канал «{title}»"
        finally:
            client.close()
    except Exception as exc:
        return False, str(exc)[:120]


def _check_github(config: Config) -> tuple[bool, str]:
    try:
        client = httpx.Client(timeout=20.0, verify=ssl_verify())
        try:
            r = client.get(
                "https://api.github.com/rate_limit",
                headers={
                    "Authorization": f"Bearer {config.github_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}"
            core = r.json().get("resources", {}).get("core", {})
            remaining = core.get("remaining", "?")
            return True, f"rate limit: {remaining} запросов"
        finally:
            client.close()
    except Exception as exc:
        return False, str(exc)[:120]


def _check_claude(config: Config) -> tuple[bool, str]:
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        msg = client.messages.create(
            model=config.anthropic_model,
            max_tokens=8,
            messages=[{"role": "user", "content": "OK"}],
        )
        part = msg.content[0].text if msg.content else ""
        return True, f"{config.anthropic_model} · ответ OK"
    except Exception as exc:
        return False, str(exc)[:120]


def _check_database(config: Config) -> tuple[bool, str]:
    try:
        stale = find_stale_env_vars()
        storage = Storage(config.db_path)
        try:
            total = storage.count_published()
            today = len(storage.published_today(config.timezone))
            weird_n = storage.weird_reserve_count() if config.weird_enabled else 0
        finally:
            storage.close()
        detail = f"опубликовано {total}, сегодня {today}"
        if config.weird_enabled:
            detail += f", резерв дичи {weird_n}"
        if stale:
            detail += f"; stale .env: {stale[0][0]}"
        return True, detail
    except Exception as exc:
        return False, str(exc)[:120]


CHECKS: list[tuple[str, Callable[[Config], tuple[bool, str]]]] = [
    ("bot", _check_bot),
    ("github", _check_github),
    ("claude", _check_claude),
    ("database", _check_database),
]


def run_startup_check(
    api: TelegramApi,
    config: Config,
    chat_id: int | str,
) -> bool:
    """Run phased startup checks; edit one Telegram message like /run progress."""
    results: dict[str, bool | None] = {k: None for k in STARTUP_PHASES}
    details: dict[str, str] = {}

    message_id = api.send_message_id(
        chat_id,
        _format_startup("bot", results=results, details={"bot": "проверка…"}),
    )

    all_ok = True
    for phase, check_fn in CHECKS:
        if message_id is not None:
            api.edit_message(
                chat_id,
                message_id,
                _format_startup(phase, results=results, details={phase: "проверка…"}),
            )
        ok, detail = check_fn(config)
        results[phase] = ok
        details[phase] = detail
        if not ok:
            all_ok = False
        if message_id is not None:
            api.edit_message(
                chat_id,
                message_id,
                _format_startup(phase, results=results, details=details, failed=not all_ok),
            )
        time.sleep(0.35)

    storage = Storage(config.db_path)
    try:
        details["published"] = str(storage.count_published())
        details["today"] = str(len(storage.published_today(config.timezone)))
        if config.weird_enabled:
            details["weird_reserve"] = str(storage.weird_reserve_count())
    finally:
        storage.close()

    me = details.get("bot", "")
    if "@" in me:
        details["bot_user"] = me.split("@")[1].split()[0]

    results["ready"] = all_ok
    final = (
        _format_ready(config, details)
        if all_ok
        else _format_startup("ready", results=results, details=details, failed=True)
        + "\n\nИсправьте ошибки и перезапустите ярлык."
    )

    if message_id is not None:
        api.edit_message(chat_id, message_id, final)
    else:
        api.send_message(chat_id, final)

    logger.info("Startup check complete: ok=%s", all_ok)
    return all_ok
