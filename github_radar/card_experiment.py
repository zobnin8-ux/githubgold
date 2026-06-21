"""Telegram carousel-only experiment counter (persisted in data/)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("github_radar.card_experiment")


class CardExperiment:
    """Publish collector cards to Telegram for the next N posts, then revert."""

    def __init__(self, data_dir: Path, *, initial: int = 0) -> None:
        self._path = data_dir / "card_experiment.json"
        self._initial = max(0, initial)
        self._remaining = self._load()

    def _load(self) -> int:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                return max(0, int(data.get("remaining", 0)))
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.warning("Invalid %s, resetting", self._path)
        if self._initial > 0:
            self._save(self._initial)
            return self._initial
        return 0

    def _save(self, remaining: int) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"remaining": remaining}, ensure_ascii=False),
            encoding="utf-8",
        )

    @property
    def remaining(self) -> int:
        return self._remaining

    @property
    def active(self) -> bool:
        return self._remaining > 0

    def record_publish(self) -> tuple[int, bool]:
        if self._remaining <= 0:
            return 0, False
        self._remaining -= 1
        self._save(self._remaining)
        finished = self._remaining == 0
        if finished:
            logger.info("Telegram card experiment finished — reverting to classic")
        else:
            logger.info("Telegram card experiment: %d post(s) left", self._remaining)
        return self._remaining, finished


def notify_experiment_finished(config) -> None:
    """Tell admin the 9-post card experiment is over (classic mode restored)."""
    from github_radar.admin_store import get_admin_chat_id
    from github_radar.telegram_api import TelegramApi

    chat_id = get_admin_chat_id(config.telegram_admin_user_id)
    if chat_id is None:
        logger.warning("Card experiment done but no admin chat_id for notification")
        return
    text = (
        "🏁 Эксперимент завершён: 9 карточек в Telegram опубликованы.\n\n"
        "Канал снова на classic (README + текст).\n\n"
        "Когда решишь — напиши в Cursor: оставить карточки или оставить classic."
    )
    api = TelegramApi(config.telegram_bot_token)
    try:
        if api.send_message(chat_id, text):
            logger.info("Card experiment finish notification sent to admin")
        else:
            logger.warning("Failed to send card experiment notification")
    finally:
        api.close()
