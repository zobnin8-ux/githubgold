"""Light filters, velocity, freshness, and hype ranking."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from github_radar.config import Config
from github_radar.hype import compute_freshness, compute_hype, compute_rarity, extract_features
from github_radar.image_pick import pick_readme_image
from github_radar.models import Candidate, Repo
from github_radar.readme_fetch import ReadmeFetcher
from github_radar.storage import Storage

logger = logging.getLogger("github_radar.prefilter")

LIST_LEARNING = re.compile(
    r"\b(awesome|roadmap|cheatsheet|course|book|spec)\b",
    re.IGNORECASE,
)


def _repo_age_days(repo: Repo) -> float:
    now = datetime.now(timezone.utc)
    created = repo.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return max((now - created).total_seconds() / 86400, 1.0)


def compute_velocity(repo: Repo, storage: Storage) -> float:
    storage.record_stars(repo.id, repo.stars)
    past = storage.stars_n_days_ago(repo.id, days=7)
    if past is not None:
        return float(repo.stars - past)
    return repo.stars / _repo_age_days(repo)


def _velocity_ranks(velocities: list[float]) -> list[float]:
    if not velocities:
        return []
    if len(velocities) == 1:
        return [1.0]
    sorted_vals = sorted(velocities)
    ranks: list[float] = []
    for v in velocities:
        idx = sorted_vals.index(v)
        ranks.append(idx / (len(sorted_vals) - 1))
    return ranks


def _quick_list_check(repo: Repo) -> bool:
    blob = f"{repo.full_name} {repo.description} {' '.join(repo.topics)}"
    return bool(LIST_LEARNING.search(blob))


def early_reject(repo: Repo, config: Config, storage: Storage) -> str | None:
    if storage.is_published(repo.id):
        return "already published"
    if repo.is_fork:
        return "fork"
    if repo.is_archived:
        return "archived"
    if not repo.description or len(repo.description) < 15:
        return "short description"
    if repo.stars < config.min_stars:
        return f"stars < {config.min_stars}"
    if _quick_list_check(repo):
        return "list/learning"
    return None


def feature_reject(features, config: Config) -> str | None:
    if features.is_list_or_learning:
        return "list/learning"
    if config.strict_no_libs and features.looks_like_library:
        return "library/sdk"
    return None


def build_funnel(
    repos: list[Repo],
    config: Config,
    storage: Storage,
    readme_fetcher: ReadmeFetcher,
    github_source=None,
) -> list[Candidate]:
    pre_readme: list[Repo] = []

    for repo in repos:
        reason = early_reject(repo, config, storage)
        if reason:
            logger.debug("Rejected %s: %s", repo.full_name, reason)
            continue
        pre_readme.append(repo)

    # Хайп: приоритет свежим и быстрорастущим (высокие звёзды — ок)
    pre_readme.sort(key=lambda r: (r.pushed_at, r.stars), reverse=True)
    scan_pool = pre_readme[: config.readme_scan_limit]
    logger.info(
        "Prefilter: %d collected -> %d after quick filters -> scanning %d READMEs",
        len(repos),
        len(pre_readme),
        len(scan_pool),
    )

    survivors: list[Candidate] = []

    for i, repo in enumerate(scan_pool, start=1):
        if i % 10 == 0 or i == len(scan_pool):
            logger.info("README scan progress: %d/%d", i, len(scan_pool))

        readme = readme_fetcher.fetch(repo)
        if github_source and not repo.has_releases:
            repo.has_releases = github_source._check_releases(repo.full_name)

        image_url = pick_readme_image(readme, repo)
        features = extract_features(repo, readme, config, image_url=image_url)
        reason = feature_reject(features, config)
        if reason:
            logger.debug("Rejected %s: %s", repo.full_name, reason)
            continue

        hype = compute_hype(features)
        freshness = compute_freshness(repo)
        velocity = compute_velocity(repo, storage)
        rarity_info = compute_rarity(hype, config)
        survivors.append(
            Candidate(
                repo=repo,
                readme=readme,
                features=features,
                hype=hype,
                freshness=freshness,
                velocity=velocity,
                image_url=image_url,
                rarity_info=rarity_info,
            )
        )

    if not survivors:
        logger.warning("Empty funnel after filters")
        return []

    velocities = [c.velocity for c in survivors]
    ranks = _velocity_ranks(velocities)
    for candidate, rank in zip(survivors, ranks):
        candidate.velocity_rank = rank
        candidate.final_score = (
            candidate.hype * 1.5 + rank * 1.0 + candidate.freshness * 0.5
        )

    survivors.sort(key=lambda c: c.final_score, reverse=True)
    top = survivors[: config.prefilter_limit]
    logger.info(
        "Funnel: %d -> %d after README scan, top %d for curator",
        len(repos),
        len(survivors),
        len(top),
    )
    return top
