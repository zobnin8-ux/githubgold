"""Hype feature extraction and scoring."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from github_radar.config import Config
from github_radar.config import Config
from github_radar.models import Features, RarityInfo, Repo

GIF_PATTERN = re.compile(r"\.gif\b|asciinema", re.IGNORECASE)

LIBRARY_KEYWORDS = re.compile(
    r"\b(library|lib|framework|sdk|boilerplate|bindings|wrapper)\b",
    re.IGNORECASE,
)

LIST_LEARNING = re.compile(
    r"\b(awesome|roadmap|cheatsheet|course|book|spec)\b",
    re.IGNORECASE,
)


def _text_blob(repo: Repo, readme: str) -> str:
    return f"{repo.full_name} {repo.description} {' '.join(repo.topics)} {readme}".lower()


def _contains_any(text: str, keywords: frozenset[str]) -> bool:
    return any(kw in text for kw in keywords)


def extract_features(
    repo: Repo,
    readme: str,
    config: Config,
    image_url: str | None = None,
) -> Features:
    blob = _text_blob(repo, readme)
    owner_lower = repo.owner_login.lower()

    brand_boost = owner_lower in config.owner_boostlist
    trend_riding = _contains_any(blob, config.hot_trends)
    mass_appeal = _contains_any(blob, config.mass_appeal_keywords)
    niche_ops = _contains_any(blob, config.niche_penalty_keywords) and not mass_appeal
    has_real_screenshot = image_url is not None
    has_gif = bool(GIF_PATTERN.search(readme))
    looks_like_library = bool(LIBRARY_KEYWORDS.search(blob))
    is_list_or_learning = bool(LIST_LEARNING.search(blob))

    return Features(
        brand_boost=brand_boost,
        trend_riding=trend_riding,
        has_real_screenshot=has_real_screenshot,
        has_gif=has_gif,
        mass_appeal=mass_appeal,
        niche_ops=niche_ops,
        looks_like_library=looks_like_library,
        is_list_or_learning=is_list_or_learning,
    )


def compute_hype(features: Features) -> float:
    score = 0.0
    if features.brand_boost:
        score += 4
    if features.trend_riding:
        score += 3
    if features.has_real_screenshot:
        score += 3
    if features.has_gif:
        score += 2
    if features.mass_appeal:
        score += 2
    if features.niche_ops:
        score -= 3
    if features.looks_like_library:
        score -= 4
    if features.is_list_or_learning:
        score -= 5
    return score


_RARITY_TABLE = (
    ("обычная", "ОБЫЧНАЯ", 1, "#6B7280", False),
    ("необычная", "НЕОБЫЧНАЯ", 2, "#3BA776", False),
    ("редкая", "РЕДКАЯ", 3, "#3B82F6", False),
    ("эпическая", "ЭПИЧЕСКАЯ", 4, "#7C5CFF", False),
    ("легендарная", "ЛЕГЕНДАРНАЯ", 5, "#E0B23C", True),
)


def compute_rarity(hype_score: float, config: Config) -> RarityInfo:
    t1, t2, t3, t4 = config.rarity_thresholds
    if hype_score >= t4:
        idx = 4
    elif hype_score >= t3:
        idx = 3
    elif hype_score >= t2:
        idx = 2
    elif hype_score >= t1:
        idx = 1
    else:
        idx = 0
    key, label, stars, color, legendary = _RARITY_TABLE[idx]
    return RarityInfo(
        rarity=key,
        rarity_label=label,
        rarity_stars=stars,
        accent_color=color,
        is_legendary=legendary,
    )


def compute_freshness(repo: Repo) -> float:
    now = datetime.now(timezone.utc)
    created = repo.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_days = (now - created).total_seconds() / 86400
    if age_days <= 30:
        return 3.0
    if age_days <= 120:
        return 2.0
    return 0.0
