"""«Дичь» — weird repo discovery, reserve buffer, Claude judge + copy."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import anthropic

from github_radar.config import Config
from github_radar.curator import (
    HEADLINE_MAX,
    _extract_json_array,
    _extract_json_object,
    _truncate,
)
from github_radar.grounding import (
    GROUNDING_RULES,
    build_repo_user_message,
    is_nsfw_or_offensive,
    readme_sufficient,
    response_is_unclear,
)
from github_radar.github_source import GitHubRateLimitError, GitHubSource
from github_radar.image_pick import has_real_screenshot, pick_weird_screenshot
from github_radar.models import PostDraft, RarityInfo, Repo
from github_radar.readme_fetch import ReadmeFetcher
from github_radar.storage import Storage

logger = logging.getLogger("github_radar.weird")

WEIRD_MIN_STARS = 30

DESCRIPTION_SIGNALS = re.compile(
    r"useless|for fun|nobody asked|just because|cursed|toy|pointless|"
    r"desktop pet|ascii art|no purpose|why does|shitpost|meme|"
    r"бесполезн|просто так|для прикола|игрушк",
    re.IGNORECASE,
)

PRODUCTIVE_REJECT = re.compile(
    r"\b(sdk|framework|kubernetes|terraform|enterprise|production[- ]ready|"
    r"cli tool|devtools|boilerplate|starter kit|awesome[- ]list)\b",
    re.IGNORECASE,
)

JUDGE_SYSTEM = """Ты — редактор рубрики «Дичь» в канале «Золото GitHub».

Задача: отобрать репозитории, которые вызовут смех, удивление, желание показать другу.
Нужна гениально-бесполезная, неожиданная, абсурдная дичь — кот за курсором, бесполезная
машина, ASCII-игрушка, генеративный арт, desktop pet.

ОТВЕРГАЙ обычные полезные инструменты, SDK, фреймворки, devtools «для продуктивности».

Суди только по описанию и README в данных кандидата. Не додумывай по названию репозитория.

Верни строго JSON-массив full_name из списка (только одобренные). Пустой массив — если никто не дичь."""

POST_SYSTEM = """Ты — автор рубрики «Дичь» в Telegram «Золото GitHub».

Объясни абсурд так, чтобы ЛЮБОЙ человек сразу понял, почему это странно / смешно / бесполезно.
Простым языком, без внутренних мемов, отсылок, сленга и эмодзи-шифров.
Структура: 1) прямо скажи ЧТО это и в чём нелепость (только факты из README); 2) добей короткой эмоцией.
Не загадка — должно быть понятно с первой строки.

Эталон (OwO — только если это подтверждено README):
slide_headline: «Одно слово "OwO" — на 50 языках»
slide_body: «Чувак переписал программу, которая выводит одно слово "OwO", на 50 разных языках — от Brainfuck до калькулятора. Зачем? Незачем. Просто потому что мог. И это гениально.»

ПРАВИЛА:
- text_ru: 2–4 абзаца, 350–650 символов, по-человечески, с юмором, без инсайдерских шуток.
- slide_headline: ≤50 символов, понятный цепляющий заголовок.
- slide_body: ≤200 символов, объяснение абсурда простым языком, целиком, без многоточия.
- category: 1–3 слова (можно шутливо).

{grounding}

Если проект понятен — ФОРМАТ: JSON с полями text_ru, slide_headline, slide_body, category.
Если непонятен из README/описания — только {{"unclear": true}}.""".format(
    grounding=GROUNDING_RULES.strip()
)

WEIRD_BODY_MAX = 200


def weird_rarity_info(config: Config) -> RarityInfo:
    return RarityInfo(
        rarity="дичь",
        rarity_label=config.weird_badge.upper(),
        rarity_stars=0,
        accent_color=config.weird_accent,
        is_legendary=False,
    )


def _emoji_density(text: str) -> int:
    return sum(1 for ch in text if ord(ch) > 0x2600)


def mechanical_weird_score(repo: Repo) -> int:
    blob = f"{repo.description or ''} {' '.join(repo.topics)} {repo.name}".lower()
    score = 0
    if DESCRIPTION_SIGNALS.search(blob):
        score += 3
    if _emoji_density(repo.description or "") >= 2:
        score += 2
    weird_topics = {t.lower() for t in repo.topics}
    for topic in weird_topics:
        if topic in {"fun", "joke", "meme", "toy", "art", "ascii", "cursed"}:
            score += 2
    if PRODUCTIVE_REJECT.search(blob):
        score -= 4
    if repo.stars >= 500:
        score += 1
    return score


def collect_weird_repos(github: GitHubSource, config: Config) -> list[Repo]:
    """Search GitHub by weird topics — no freshness filter."""
    seen: dict[int, Repo] = {}
    min_s = min(WEIRD_MIN_STARS, max(10, config.min_stars // 3))

    for topic in config.weird_topics:
        query = f"topic:{topic} stars:>{min_s}"
        try:
            for repo in github.search_repositories(query, per_page=30):
                if repo.id not in seen and mechanical_weird_score(repo) >= 1:
                    seen[repo.id] = repo
        except GitHubRateLimitError:
            raise
        except Exception as exc:
            logger.warning("Weird search failed for topic %s: %s", topic, exc)

    ranked = sorted(seen.values(), key=lambda r: mechanical_weird_score(r), reverse=True)
    return ranked[:25]


def _payload_from_draft_fields(
    repo: Repo,
    data: dict[str, Any],
    image_url: str | None,
) -> dict[str, Any]:
    return {
        "text_ru": str(data.get("text_ru") or "").strip(),
        "slide_headline": _truncate(str(data.get("slide_headline") or ""), HEADLINE_MAX),
        "slide_body": _truncate(str(data.get("slide_body") or ""), WEIRD_BODY_MAX),
        "category": _truncate(str(data.get("category") or "Дичь"), 24),
        "image_url": image_url,
        "has_real_screenshot": bool(image_url),
        "stars": repo.stars,
        "forks": repo.forks,
        "open_issues": repo.open_issues,
        "language": repo.language,
        "license": repo.license,
    }


class WeirdCurator:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    def _call(self, system: str, user: str, max_tokens: int = 1200) -> str:
        message = self._client.messages.create(
            model=self._config.anthropic_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts = [block.text for block in message.content if block.type == "text"]
        return "\n".join(parts).strip()

    def judge(
        self,
        repos: list[Repo],
        readmes: dict[str, str] | None = None,
    ) -> list[Repo]:
        if not repos:
            return []
        readmes = readmes or {}
        payload = []
        for r in repos[:15]:
            readme = readmes.get(r.full_name, "")
            payload.append(
                {
                    "full_name": r.full_name,
                    "description": r.description,
                    "topics": r.topics,
                    "stars": r.stars,
                    "language": r.language,
                    "readme_excerpt": (readme or "")[:2500],
                }
            )
        user_msg = (
            "Какие из этих репозиториев — настоящая «дичь» для рубрики?\n\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )
        try:
            raw = self._call(JUDGE_SYSTEM, user_msg, max_tokens=512)
            names = _extract_json_array(raw)
        except Exception as exc:
            logger.error("Weird judge failed: %s", exc)
            return []

        valid = {r.full_name: r for r in repos}
        approved: list[Repo] = []
        for name in names:
            if isinstance(name, str) and name in valid and name not in {a.full_name for a in approved}:
                approved.append(valid[name])
        return approved

    def generate_copy(
        self, repo: Repo, readme: str, image_url: str | None
    ) -> Optional[dict[str, Any]]:
        if not readme_sufficient(readme):
            logger.warning(
                "Weird skip (short README) %s: %d chars",
                repo.full_name,
                len((readme or "").strip()),
            )
            return None
        if is_nsfw_or_offensive(repo, readme):
            logger.info("Weird skip (NSFW/offensive): %s", repo.full_name)
            return None

        user_msg = build_repo_user_message(repo, readme, image_url=image_url)
        try:
            raw = self._call(POST_SYSTEM, user_msg, max_tokens=1200)
            data = _extract_json_object(raw)
            if response_is_unclear(data):
                logger.warning("Weird unclear for %s, skipping", repo.full_name)
                return None
            payload = _payload_from_draft_fields(repo, data, image_url)
            if payload["text_ru"] and payload["slide_headline"]:
                return payload
            logger.warning("Weird empty copy for %s, skipping", repo.full_name)
        except Exception as exc:
            logger.error("Weird copy failed for %s: %s", repo.full_name, exc)
        return None


def draft_from_payload(
    repo: Repo,
    payload: dict[str, Any],
    config: Config,
    readme: str = "",
) -> PostDraft:
    return PostDraft(
        repo=repo,
        text_ru=payload["text_ru"],
        slide_headline=payload["slide_headline"],
        slide_body=payload["slide_body"],
        slide_bullets=[],
        category=payload.get("category") or "Дичь",
        image_url=payload.get("image_url"),
        readme=readme,
        hype=0.0,
        rarity_info=weird_rarity_info(config),
        is_weird=True,
    )


def _weird_visual_url(
    readme: str, repo: Repo, readme_fetcher: ReadmeFetcher
) -> str | None:
    return pick_weird_screenshot(
        readme, repo, http_client=readme_fetcher.http_client
    )


def purge_weird_reserve_no_visual(
    storage: Storage,
    github: GitHubSource,
    readme_fetcher: ReadmeFetcher,
) -> int:
    """Drop reserve rows without a real README screenshot/gif."""
    removed = 0
    for row in storage.weird_reserve_list(limit=100):
        repo = github.fetch_repo(row["full_name"])
        if not repo:
            storage.weird_reserve_delete(row["repo_id"])
            removed += 1
            logger.info("Weird reserve purge (repo gone): %s", row["full_name"])
            continue
        readme = readme_fetcher.fetch(repo)
        if _weird_visual_url(readme, repo, readme_fetcher):
            continue
        storage.weird_reserve_delete(row["repo_id"])
        removed += 1
        logger.info("Weird reserve purge (no visual): %s", row["full_name"])
    return removed


def weird_reserve_visual_count(
    storage: Storage,
    github: GitHubSource,
    readme_fetcher: ReadmeFetcher,
) -> int:
    count = 0
    for row in storage.weird_reserve_list(limit=100):
        payload = json.loads(row["payload"])
        if not payload.get("image_url"):
            continue
        repo = github.fetch_repo(row["full_name"])
        if not repo:
            continue
        readme = readme_fetcher.fetch(repo)
        if _weird_visual_url(readme, repo, readme_fetcher):
            count += 1
    return count


def _draft_from_reserve_row(
    row: dict[str, Any],
    config: Config,
    github: GitHubSource,
    readme_fetcher: ReadmeFetcher,
) -> Optional[PostDraft]:
    full_name = row["full_name"]
    fresh = github.fetch_repo(full_name)
    if not fresh:
        return None
    readme = readme_fetcher.fetch(fresh)
    if not readme_sufficient(readme):
        logger.info("Weird skip (short README): %s", full_name)
        return None
    if is_nsfw_or_offensive(fresh, readme):
        logger.info("Weird skip (NSFW/offensive): %s", full_name)
        return None
    image_url = _weird_visual_url(readme, fresh, readme_fetcher)
    if not image_url:
        return None
    curator = WeirdCurator(config)
    payload = curator.generate_copy(fresh, readme, image_url)
    if not payload:
        return None
    return draft_from_payload(fresh, payload, config, readme=readme)


def _take_weird_draft(
    config: Config,
    storage: Storage,
    github: GitHubSource,
    readme_fetcher: ReadmeFetcher,
    *,
    remove: bool,
) -> Optional[PostDraft]:
    attempts = max(1, storage.weird_reserve_count())
    for _ in range(attempts):
        row = (
            storage.weird_reserve_pop_oldest()
            if remove
            else storage.weird_reserve_peek_oldest()
        )
        if not row:
            return None
        draft = _draft_from_reserve_row(row, config, github, readme_fetcher)
        if draft:
            if remove and storage.is_published(draft.repo.id):
                logger.info(
                    "Weird reserve entry already published: %s", draft.repo.full_name
                )
                continue
            return draft
        logger.info("Weird skip (no visual): %s", row["full_name"])
        if not remove:
            storage.weird_reserve_delete(row["repo_id"])
    return None


def refill_weird_reserve(
    config: Config,
    storage: Storage,
    github: GitHubSource,
    readme_fetcher: ReadmeFetcher,
) -> int:
    """Find new weird repos and add to reserve until target size."""
    if not config.weird_enabled:
        return 0

    purge_weird_reserve_no_visual(storage, github, readme_fetcher)

    need = config.weird_reserve_target - storage.weird_reserve_count()
    if need <= 0:
        return 0

    candidates = collect_weird_repos(github, config)
    fresh = [r for r in candidates if not storage.weird_is_known(r.id)]
    if not fresh:
        logger.info("Weird refill: no new mechanical candidates")
        return 0

    curator = WeirdCurator(config)
    readme_map: dict[str, str] = {}
    judged_repos: list[Repo] = []
    for repo in fresh:
        if is_nsfw_or_offensive(repo, ""):
            continue
        readme = readme_fetcher.fetch(repo)
        if is_nsfw_or_offensive(repo, readme):
            logger.info("Weird skip (NSFW/offensive): %s", repo.full_name)
            continue
        if not readme_sufficient(readme):
            continue
        readme_map[repo.full_name] = readme
        judged_repos.append(repo)

    approved = curator.judge(judged_repos, readmes=readme_map)
    if not approved:
        logger.info("Weird refill: Claude approved none")
        return 0

    added = 0
    for repo in approved:
        if added >= need:
            break
        if storage.weird_is_known(repo.id):
            continue
        readme = readme_map.get(repo.full_name) or readme_fetcher.fetch(repo)
        if not readme_sufficient(readme):
            continue
        image_url = _weird_visual_url(readme, repo, readme_fetcher)
        if not image_url:
            logger.info("Weird skip (no visual): %s", repo.full_name)
            continue
        payload = curator.generate_copy(repo, readme, image_url)
        if not payload:
            continue
        if storage.weird_reserve_add(repo.id, repo.full_name, payload):
            added += 1
            logger.info("Weird reserve +%s (%s)", repo.full_name, added)
    return added


def needs_weird_slot(config: Config, storage: Storage) -> bool:
    if not config.weird_enabled:
        return False
    return storage.weird_posted_today(config.timezone) < config.weird_per_day


def peek_weird_draft(
    config: Config,
    storage: Storage,
    github: GitHubSource,
    readme_fetcher: ReadmeFetcher,
) -> Optional[PostDraft]:
    """Preview oldest reserve entry with visual (dry-run)."""
    return _take_weird_draft(
        config, storage, github, readme_fetcher, remove=False
    )


def pop_weird_draft(
    config: Config,
    storage: Storage,
    github: GitHubSource,
    readme_fetcher: ReadmeFetcher,
) -> Optional[PostDraft]:
    """Take oldest reserve entry with visual and build a publishable draft."""
    return _take_weird_draft(
        config, storage, github, readme_fetcher, remove=True
    )


def peek_weird_reserve(storage: Storage, limit: int = 3) -> list[dict[str, Any]]:
    rows = storage.weird_reserve_list(limit=limit)
    out = []
    for row in rows:
        payload = json.loads(row["payload"])
        out.append(
            {
                "full_name": row["full_name"],
                "added_at": row["added_at"],
                "slide_headline": payload.get("slide_headline", ""),
            }
        )
    return out
