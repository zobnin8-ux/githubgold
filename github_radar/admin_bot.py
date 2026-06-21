"""Telegram admin bot — commands like Radar budushchego."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from github_radar.admin_store import get_admin_chat_id, load_admin, save_admin
from github_radar.config import Config, load_config
from github_radar.http_ssl import ssl_verify
from github_radar.logging_setup import setup_logging
from github_radar.process_lock import (
    ProcessLock,
    find_radar_main_pids,
    purge_stale_locks,
    stop_everything,
)
from github_radar.progress import (
    CycleProgress,
    format_telegram,
    is_running,
    progress_path,
    read,
)
from github_radar.startup_check import run_startup_check
from github_radar.storage import Storage
from github_radar.telegram_api import TelegramApi

logger = logging.getLogger("github_radar.admin_bot")

_instance_lock: ProcessLock | None = None


def _release_instance_lock() -> list[str]:
    """Release this bot's instance lock and purge any leftover lock files."""
    global _instance_lock
    data_dir: Path | None = None
    if _instance_lock is not None:
        data_dir = _instance_lock.path.parent
        _instance_lock.release()
        _instance_lock = None
    if data_dir is None:
        return []
    return purge_stale_locks(data_dir)

HELP_TEXT = """🏆 Золото GitHub — команды

/status — статус, посты сегодня, режим
/run — опубликовать сейчас (прогресс-бар)
/dry — тест без канала (прогресс-бар)
/today — что вышло в канал сегодня
/stats — всего опубликовано в базе
/stop — остановить только бот
/stopall — полная остановка: main, все боты, все lock-файлы
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


_progress_poll_interval = 5.0


def _build_status(config: Config) -> str:
    storage = Storage(config.db_path)
    try:
        today = storage.published_today(config.timezone)
        total = storage.count_published()
    finally:
        storage.close()

    prog_path = progress_path(config.db_path.parent)
    prog_data = read(prog_path)

    main_pids = find_radar_main_pids()
    if is_running(prog_path) or main_pids:
        running = format_telegram(prog_data, title="🔄 Радар")
        if main_pids:
            running += f"\n\nPID: {', '.join(map(str, main_pids))}"
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


def _poll_progress_loop(
    api: TelegramApi,
    chat_id: int,
    message_id: int,
    config: Config,
    stop_event: threading.Event,
) -> None:
    path = progress_path(config.db_path.parent)
    last_text = ""
    while not stop_event.wait(_progress_poll_interval):
        data = read(path)
        if data.get("status") not in ("running",):
            break
        text = format_telegram(data)
        if text and text != last_text:
            if api.edit_message(chat_id, message_id, text):
                last_text = text


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
    label = "Dry-run" if dry_run else "Боевой цикл"
    prog_path = progress_path(config.db_path.parent)
    CycleProgress(prog_path).reset()

    def worker() -> None:
        initial = format_telegram(
            {
                "status": "running",
                "dry_run": dry_run,
                "phase": "trending",
                "current": 0,
                "total": 0,
                "detail": "Запуск…",
            },
            title=f"🔄 {label}",
        )
        message_id = api.send_message_id(chat_id, initial)
        stop_event = threading.Event()
        poller: threading.Thread | None = None
        if message_id is not None:
            poller = threading.Thread(
                target=_poll_progress_loop,
                args=(api, chat_id, message_id, config, stop_event),
                daemon=True,
            )
            poller.start()

        code = _run_subprocess(config, dry_run=dry_run)
        stop_event.set()
        if poller is not None:
            poller.join(timeout=2.0)

        data = read(prog_path)
        if data.get("status") not in ("done", "error"):
            if code == 0:
                CycleProgress(prog_path).done(detail=f"Код выхода {code}")
            else:
                CycleProgress(prog_path).error(f"Код выхода {code}")
            data = read(prog_path)

        final = format_telegram(data, title=f"✅ {label}" if code == 0 else f"❌ {label}")
        if dry_run and code == 0:
            final += "\n\nСмотрите data/radar.log"
        elif code == 0:
            storage = Storage(config.db_path)
            try:
                n = len(storage.published_today(config.timezone))
            finally:
                storage.close()
            final += f"\n\nПостов сегодня: {n}"

        if message_id is not None:
            api.edit_message(chat_id, message_id, final)
        else:
            api.send_message(chat_id, final)

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
        if _is_cycle_running(config) or is_running(progress_path(config.db_path.parent)):
            api.send_message(chat_id, "⏳ Уже выполняется цикл. Смотрите /status")
            return False
        _start_cycle_async(api, chat_id, config, dry_run=False)
    elif cmd == "/dry":
        if _is_cycle_running(config) or is_running(progress_path(config.db_path.parent)):
            api.send_message(chat_id, "⏳ Уже выполняется цикл.")
            return False
        _start_cycle_async(api, chat_id, config, dry_run=True)
    elif cmd == "/stopall":
        global _cycle_running
        api.send_message(chat_id, "🛑 Полная остановка…")
        subprocess_stopped = _stop_cycle_subprocess()
        result = stop_everything(config.db_path.parent)
        _cycle_running = False
        for name in _release_instance_lock():
            if name not in result.locks_removed:
                result.locks_removed.append(name)

        parts: list[str] = []
        if result.killed_main:
            parts.append(f"main: PID {', '.join(map(str, result.killed_main))}")
        elif subprocess_stopped:
            parts.append("main: /run subprocess")
        else:
            parts.append("main: не было")
        if result.killed_bots:
            parts.append(f"бот (другие): PID {', '.join(map(str, result.killed_bots))}")
        parts.append(f"бот (этот): PID {os.getpid()} — выключается")
        if result.locks_removed:
            parts.append(f"lock: {', '.join(result.locks_removed)}")
        else:
            parts.append("lock: не было")

        left = result.remaining_main + result.remaining_bots
        if left:
            verify = (
                f"⚠️ Не удалось остановить: PID {', '.join(map(str, left))}\n"
                "Проверьте Диспетчер задач вручную."
            )
        else:
            verify = "✅ Проверка: других процессов github_radar не осталось"

        api.send_message(
            chat_id,
            "🛑 Полная остановка.\n\n"
            + "\n".join(parts)
            + f"\n\n{verify}\n\n"
            "Запуск снова: нажми ярлык Zoloto GitHub.lnk — он перезапустит бота и пришлёт прогресс в Telegram.",
        )
        time.sleep(0.6)
        api.close()
        os._exit(0)
    elif cmd == "/stop":
        api.send_message(
            chat_id,
            "🛑 Останавливаю бот.\n\n"
            "Радар (main) продолжит работу, если запущен отдельно.\n"
            "Остановить всё: /stopall\n\n"
            "Запуск снова: нажми ярлык Zoloto GitHub.lnk — он перезапустит бота.",
        )
        time.sleep(0.6)
        _release_instance_lock()
        api.close()
        os._exit(0)
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
    return run_startup_check(api, config, chat_id)


def run_admin_bot() -> None:
    ssl_verify()
    config = load_config()
    setup_logging(config.log_path)

    if not config.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    global _instance_lock
    _instance_lock = ProcessLock(config.db_path.parent / "bot.instance.lock")
    if not _instance_lock.acquire():
        logger.error("Another bot instance is already running")
        return

    api = TelegramApi(config.telegram_bot_token)
    try:
        api.delete_webhook()
        api.set_my_commands()
        load_admin()

        chat_id = get_admin_chat_id(config.telegram_admin_user_id)
        if chat_id is not None:
            api.send_message(chat_id, "🔄 Запуск бота…")

        send_startup_to_admin(api, config)

        offset = 0
        logger.info("Telegram admin bot listening...")

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
        _release_instance_lock()
