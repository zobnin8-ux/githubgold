"""Telegram admin bot — commands like Radar budushchego."""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

from github_radar.admin_store import get_admin_chat_id, load_admin, save_admin
from github_radar.config import Config, load_config
from github_radar.http_ssl import ssl_verify
from github_radar.logging_setup import setup_logging
from github_radar.process_lock import find_radar_main_pids, stop_radar_cycles
from github_radar.storage import Storage
from github_radar.telegram_api import TelegramApi

logger = logging.getLogger("github_radar.admin_bot")

HELP_TEXT = """🏆 Золото GitHub — команды

/status — статус, посты сегодня, режим
/run — опубликовать сейчас (до POSTS_PER_RUN постов, ~5–10 мин)
/dry — тест без канала (~5–10 мин, результат в лог)
/today — что вышло в канал сегодня
/stats — всего опубликовано в базе
/stop — остановить только бот
/stop all — остановить радар (main) + снять lock + остановить бот
/help или /commands — этот список

Автопостинг: Task Scheduler ~3 раза в сутки (9 постов/день)."""

_cycle_lock = threading.Lock()
_cycle_running = False
_cycle_proc: subprocess.Popen[str] | None = None


def _parse_command(text: str) -> tuple[str, list[str]]:
    parts = text.strip().split()
    if not parts:
        return "", []
    token = parts[0].lower()
    at = token.find("@")
    if at >= 0:
        token = token[:at]
    return token, parts[1:]


def _is_admin(config: Config, user_id: int | None) -> bool:
    if user_id is None:
        return False
    if config.telegram_admin_user_id is None:
        return True
    return user_id == config.telegram_admin_user_id


def _cycle_lock_path(config: Config) -> Path:
    return config.db_path.parent / "cycle.lock"


def _is_cycle_running(config: Config) -> bool:
    global _cycle_running
    if _cycle_running:
        return True
    return _cycle_lock_path(config).exists()


def _build_status(config: Config) -> str:
    storage = Storage(config.db_path)
    try:
        today = storage.published_today(config.timezone)
        total = storage.count_published()
    finally:
        storage.close()

    main_pids = find_radar_main_pids()
    if main_pids:
        running = f"🔄 радар работает (main PID: {', '.join(map(str, main_pids))})"
    elif _is_cycle_running(config):
        running = "🔄 цикл выполняется (/run)"
    else:
        running = "🟢 готов"
    lines = [
        running,
        "",
        f"Постов сегодня: {len(today)}",
        f"Всего в базе: {total}",
        f"За запуск: до {config.posts_per_run} постов",
        f"Канал: {config.telegram_channel_id}",
        f"Звёзды: >= {config.min_stars}",
        f"Режим: ~9 постов/день (Task Scheduler)",
    ]
    return "\n".join(lines)


def _build_today(config: Config) -> str:
    storage = Storage(config.db_path)
    try:
        rows = storage.published_today(config.timezone)
    finally:
        storage.close()
    if not rows:
        return "Сегодня постов ещё не было."
    lines = []
    for i, row in enumerate(rows, 1):
        ts = row["published_at"][:16].replace("T", " ")
        lines.append(f"{i}. {row['full_name']}  ({ts})")
    return "\n".join(lines)


def _run_subprocess(config: Config, dry_run: bool) -> int:
    global _cycle_running, _cycle_proc
    lock_file = _cycle_lock_path(config)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_text("1", encoding="utf-8")
    _cycle_running = True
    try:
        cmd = [sys.executable, "-m", "github_radar.main"]
        if dry_run:
            cmd.append("--dry-run")
        project_root = Path(__file__).resolve().parent.parent
        _cycle_proc = subprocess.Popen(
            cmd,
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        stdout, stderr = _cycle_proc.communicate()
        code = _cycle_proc.returncode or 0
        if code != 0:
            logger.error("Cycle stderr: %s", (stderr or stdout)[-2000:])
        return code
    finally:
        _cycle_running = False
        _cycle_proc = None
        if lock_file.exists():
            lock_file.unlink()


def _stop_cycle_subprocess() -> bool:
    global _cycle_proc
    proc = _cycle_proc
    if proc is None or proc.poll() is not None:
        return False
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)
    logger.info("Stopped /run subprocess PID %s", proc.pid)
    return True


def _start_cycle_async(
    api: TelegramApi,
    chat_id: int,
    config: Config,
    dry_run: bool,
) -> None:
    label = "dry-run" if dry_run else "боевой цикл"

    def worker() -> None:
        code = _run_subprocess(config, dry_run=dry_run)
        if dry_run:
            api.send_message(chat_id, f"✅ {label} завершён (код {code}). Смотрите data/radar.log")
        else:
            storage = Storage(config.db_path)
            try:
                n = len(storage.published_today(config.timezone))
            finally:
                storage.close()
            api.send_message(
                chat_id,
                f"✅ {label} завершён. Постов сегодня: {n}. Лог: data/radar.log",
            )

    threading.Thread(target=worker, daemon=True).start()


def handle_command(
    api: TelegramApi,
    config: Config,
    chat_id: int,
    user_id: int | None,
    text: str,
) -> bool:
    """Handle one command. Returns True if the bot should shut down."""
    cmd, args = _parse_command(text)

    if cmd == "/start":
        if not _is_admin(config, user_id):
            api.send_message(
                chat_id,
                f"⛔ Нет доступа.\n\nВаш ID: {user_id}\nДобавьте в .env:\nTELEGRAM_ADMIN_USER_ID={user_id}",
            )
            return False
        if user_id is not None:
            save_admin(chat_id, user_id)
        api.send_message(chat_id, "✅ Бот «Золото GitHub» запущен. Вы администратор.")
        api.send_message(chat_id, HELP_TEXT)
        return False

    if not _is_admin(config, user_id):
        api.send_message(
            chat_id,
            f"⛔ Нет доступа.\n\nВаш ID: {user_id}\nTELEGRAM_ADMIN_USER_ID={user_id}",
        )
        return False

    if config.telegram_admin_user_id is None and user_id is not None:
        save_admin(chat_id, user_id)

    if cmd in ("/help", "/commands"):
        api.send_message(chat_id, HELP_TEXT)
    elif cmd == "/status":
        api.send_message(chat_id, _build_status(config))
    elif cmd == "/today":
        api.send_message(chat_id, _build_today(config))
    elif cmd == "/stats":
        storage = Storage(config.db_path)
        try:
            total = storage.count_published()
        finally:
            storage.close()
        api.send_message(chat_id, f"Всего опубликовано репозиториев: {total}")
    elif cmd == "/run":
        if _is_cycle_running(config):
            api.send_message(chat_id, "⏳ Уже выполняется цикл. Подождите ~5–10 мин.")
            return False
        api.send_message(chat_id, "⏳ Запускаю боевой цикл (~5–10 мин)...")
        _start_cycle_async(api, chat_id, config, dry_run=False)
    elif cmd == "/dry":
        if _is_cycle_running(config):
            api.send_message(chat_id, "⏳ Уже выполняется цикл.")
            return False
        api.send_message(chat_id, "⏳ Запускаю dry-run (~5–10 мин)...")
        _start_cycle_async(api, chat_id, config, dry_run=True)
    elif cmd in ("/stop", "/stopall"):
        stop_all = cmd == "/stopall" or (
            args and args[0].lower() in ("all", "все")
        )
        if stop_all:
            subprocess_stopped = _stop_cycle_subprocess()
            killed = stop_radar_cycles(config.db_path.parent)
            parts: list[str] = []
            if killed:
                parts.append(f"main: PID {', '.join(map(str, killed))}")
            elif subprocess_stopped:
                parts.append("main: /run subprocess")
            else:
                parts.append("main: не найден")
            parts.append("lock: снят")
            api.send_message(
                chat_id,
                "🛑 Остановлен радар и бот.\n\n"
                + "\n".join(parts)
                + "\n\nЗапуск снова: Zoloto GitHub.lnk в D:\\treasure",
            )
            time.sleep(0.4)
            return True
        api.send_message(
            chat_id,
            "🛑 Останавливаю бот.\n\n"
            "Радар (main) продолжит работу, если запущен отдельно.\n"
            "Остановить всё: /stop all\n\n"
            "Запуск снова: Zoloto GitHub.lnk в папке D:\\treasure",
        )
        time.sleep(0.4)
        return True
    elif cmd.startswith("/"):
        api.send_message(chat_id, "Неизвестная команда. Список: /help")

    return False


def _bot_launch_lock_path(config: Config) -> Path:
    return config.db_path.parent / "bot.launch.lock"


def _cleanup_launch_lock(config: Config) -> None:
    lock = _bot_launch_lock_path(config)
    if lock.exists():
        lock.unlink(missing_ok=True)


def send_startup_to_admin(api: TelegramApi, config: Config) -> bool:
    chat_id = get_admin_chat_id(config.telegram_admin_user_id)
    if not chat_id:
        logger.warning(
            "Укажите TELEGRAM_ADMIN_USER_ID в .env или напишите боту /start в личку"
        )
        return False

    startup = "✅ Золото GitHub — бот запущен!\n\n" + HELP_TEXT
    for attempt in range(1, 4):
        if api.send_message(chat_id, startup):
            logger.info("Startup + commands sent to Telegram (chat %s)", chat_id)
            return True
        logger.warning("Failed to send startup message, attempt %d/3", attempt)
        time.sleep(2)
    return False


def run_admin_bot() -> None:
    ssl_verify()
    config = load_config()
    setup_logging(config.log_path)

    if not config.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    api = TelegramApi(config.telegram_bot_token)
    api.delete_webhook()
    api.set_my_commands()
    load_admin()

    send_startup_to_admin(api, config)

    offset = 0
    logger.info("Telegram admin bot listening...")

    try:
        while True:
            try:
                updates = api.get_updates(offset)
                for update in updates:
                    offset = update["update_id"] + 1
                    msg = update.get("message")
                    if not msg or not msg.get("text"):
                        continue
                    text = msg["text"]
                    if not text.startswith("/"):
                        continue
                    if handle_command(
                        api,
                        config,
                        msg["chat"]["id"],
                        msg.get("from", {}).get("id"),
                        text,
                    ):
                        logger.info("Shutdown requested via Telegram")
                        break
            except Exception:
                logger.exception("Admin bot poll error")
            time.sleep(0.5)
    finally:
        _cleanup_launch_lock(config)
        api.close()
