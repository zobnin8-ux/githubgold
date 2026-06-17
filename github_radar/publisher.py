"""Telegram channel publisher."""

from __future__ import annotations

import html
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from github_radar.config import Config
from github_radar.http_ssl import ssl_verify
from github_radar.models import PostDraft
from github_radar.progress import update
from github_radar.slides import format_license
from github_radar.storage import Storage

logger = logging.getLogger("github_radar.publisher")

TELEGRAM_API = "https://api.telegram.org"
CAPTION_LIMIT = 1024
POST_DELAY_SEC = 2.5


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def _build_hashtags(repo) -> str:
    tags: list[str] = []
    if repo.language:
        tags.append(f"#{repo.language.lower().replace(' ', '')}")
    for topic in repo.topics[:2]:
        tag = topic.lower().replace("-", "").replace("_", "")
        if tag and f"#{tag}" not in tags:
            tags.append(f"#{tag}")
    return " ".join(tags[:3])


def _truncate_text(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def build_caption(draft: PostDraft) -> str:
    repo = draft.repo
    hashtags = _build_hashtags(repo)
    lang = repo.language or "—"

    footer = (
        f"\n\n⭐ {repo.stars}  ·  🍴 {repo.forks}  ·  🐛 {repo.open_issues}  ·  "
        f"{_escape(lang)}\n\n"
        f'<a href="{repo.html_url}">Открыть на GitHub</a>'
    )
    if hashtags:
        footer += f"\n{hashtags}"

    header = f"<b>{_escape(repo.full_name)}</b>\n\n"
    overhead = len(header) + len(footer)
    text_budget = CAPTION_LIMIT - overhead - 10
    body = _truncate_text(_escape(draft.text_ru), max(text_budget, 100))

    return f"{header}{body}{footer}"


class Publisher:
    def __init__(self, config: Config, storage: Storage) -> None:
        self._config = config
        self._storage = storage
        self._base = f"{TELEGRAM_API}/bot{config.telegram_bot_token}"
        self._client = httpx.Client(timeout=30.0, verify=ssl_verify())

    def close(self) -> None:
        self._client.close()

    def _og_image_url(self, repo) -> str:
        return f"https://opengraph.githubassets.com/1/{repo.owner}/{repo.name}"

    def _send_photo(self, chat_id: str, photo_url: str, caption: str) -> Optional[int]:
        response = self._client.post(
            f"{self._base}/sendPhoto",
            data={
                "chat_id": chat_id,
                "photo": photo_url,
                "caption": caption,
                "parse_mode": "HTML",
            },
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("ok"):
                return data["result"]["message_id"]
        logger.warning("sendPhoto failed: %s %s", response.status_code, response.text[:200])
        return None

    def _send_message(self, chat_id: str, text: str) -> Optional[int]:
        response = self._client.post(
            f"{self._base}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("ok"):
                return data["result"]["message_id"]
        logger.error("sendMessage failed: %s %s", response.status_code, response.text[:200])
        return None

    def publish_one(self, draft: PostDraft) -> bool:
        repo = draft.repo
        if self._storage.is_published(repo.id):
            logger.info("Skipping already published: %s", repo.full_name)
            return False

        caption = build_caption(draft)
        chat_id = self._config.telegram_channel_id
        og_url = self._og_image_url(repo)
        readme_image = draft.image_url

        message_id: Optional[int] = None
        if readme_image:
            message_id = self._send_photo(chat_id, readme_image, caption)
            if message_id is None:
                logger.info("README image failed for %s, trying OG card", repo.full_name)
                message_id = self._send_photo(chat_id, og_url, caption)
        else:
            message_id = self._send_photo(chat_id, og_url, caption)

        if message_id is None:
            logger.info("Falling back to sendMessage for %s", repo.full_name)
            message_id = self._send_message(chat_id, caption)

        if message_id is None:
            return False

        card_number = self._storage.next_card_number()
        rarity = draft.rarity_info
        published_at = datetime.now(timezone.utc)
        self._storage.mark_published(
            repo.id,
            repo.full_name,
            message_id=message_id,
            published_at=published_at,
            text_ru=draft.text_ru,
            slide_hook=None,
            slide_headline=draft.slide_headline,
            slide_body=draft.slide_body,
            slide_bullets=draft.slide_bullets,
            category=draft.category,
            image_url=draft.image_url,
            license=format_license(repo.license),
            rarity=rarity.rarity_label if rarity else None,
            rarity_stars=rarity.rarity_stars if rarity else None,
            card_number=card_number,
            hype=draft.hype,
            stars=repo.stars,
            forks=repo.forks,
            open_issues=repo.open_issues,
            is_weird=draft.is_weird,
        )
        draft.card_number = card_number
        draft.message_id = message_id
        draft.published_at = published_at
        logger.info("Published %s (message_id=%s, card #%s)", repo.full_name, message_id, card_number)
        return True

    def publish_all(self, drafts: list[PostDraft]) -> list[PostDraft]:
        published: list[PostDraft] = []
        total = len(drafts)
        update("publish", current=0, total=total, detail="Telegram…")
        for i, draft in enumerate(drafts):
            update(
                "publish",
                current=i + 1,
                total=total,
                detail=draft.repo.full_name,
            )
            if self.publish_one(draft):
                published.append(draft)
            if i < len(drafts) - 1:
                time.sleep(POST_DELAY_SEC)
        return published
