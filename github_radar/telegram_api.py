"""Telegram Bot API helpers."""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from github_radar.http_ssl import ssl_verify

logger = logging.getLogger("github_radar.telegram_api")


class TelegramApi:
    def __init__(self, token: str) -> None:
        self._base = f"https://api.telegram.org/bot{token}"
        self._client = httpx.Client(timeout=35.0, verify=ssl_verify())

    def close(self) -> None:
        self._client.close()

    def _post(self, method: str, payload: dict) -> dict:
        response = self._client.post(f"{self._base}/{method}", json=payload)
        data = response.json()
        if not data.get("ok"):
            logger.warning("Telegram %s failed: %s", method, data.get("description"))
        return data

    def send_message(self, chat_id: int | str, text: str) -> bool:
        return self.send_message_id(chat_id, text) is not None

    def send_message_id(self, chat_id: int | str, text: str) -> Optional[int]:
        data = self._post(
            "sendMessage",
            {"chat_id": chat_id, "text": text, "disable_web_page_preview": False},
        )
        if not data.get("ok"):
            return None
        result = data.get("result") or {}
        return result.get("message_id")

    def edit_message(self, chat_id: int | str, message_id: int, text: str) -> bool:
        data = self._post(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "disable_web_page_preview": False,
            },
        )
        return bool(data.get("ok"))

    def get_updates(self, offset: int, timeout: int = 30) -> list[dict]:
        response = self._client.get(
            f"{self._base}/getUpdates",
            params={"offset": offset, "timeout": timeout},
            timeout=timeout + 10,
        )
        data = response.json()
        if not data.get("ok"):
            return []
        return data.get("result") or []

    def delete_webhook(self) -> None:
        try:
            self._client.get(f"{self._base}/deleteWebhook", params={"drop_pending_updates": True})
        except Exception:
            pass

    def set_my_commands(self) -> bool:
        commands = [
            {"command": "status", "description": "Статус и посты сегодня"},
            {"command": "run", "description": "Опубликовать сейчас"},
            {"command": "dry", "description": "Тест без канала"},
            {"command": "today", "description": "Что вышло сегодня"},
            {"command": "stop", "description": "Остановить только бот"},
            {"command": "stopall", "description": "Полная остановка всего"},
            {"command": "help", "description": "Список команд"},
        ]
        data = self._post("setMyCommands", {"commands": commands})
        return bool(data.get("ok"))
