"""Pre-fill weird_reserve with classic weird repos (GitHub API + Claude)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from github_radar.config import load_config
from github_radar.github_source import GitHubSource
from github_radar.http_ssl import ssl_verify
from github_radar.logging_setup import setup_logging
from github_radar.readme_fetch import ReadmeFetcher
from github_radar.storage import Storage
from github_radar.weird import (
    WeirdCurator,
    collect_weird_repos,
    refill_weird_reserve,
)
from github_radar.grounding import is_nsfw_or_offensive, readme_sufficient
from github_radar.image_pick import pick_weird_screenshot

logger = logging.getLogger("seed_weird")

# Names to try if search does not fill the reserve (verified via API, not invented).
SEED_FULL_NAMES = [
    "Externalizable/bongo.cat",
    "adryd325/oneko",
    "FriedZombiehom/Flying-Toasters",
    "jart/sectorc",
    "alex-goff/terminal-typer",
]


def _seed_named_repos(
    config,
    storage: Storage,
    github: GitHubSource,
    readme_fetcher: ReadmeFetcher,
    target: int,
) -> int:
    curator = WeirdCurator(config)
    added = 0
    for full_name in SEED_FULL_NAMES:
        if storage.weird_reserve_count() >= target:
            break
        repo = github.fetch_repo(full_name)
        if not repo or storage.weird_is_known(repo.id):
            continue
        readme = readme_fetcher.fetch(repo)
        if not readme_sufficient(readme):
            logger.info("Seed skip (short README): %s", full_name)
            continue
        if is_nsfw_or_offensive(repo, readme):
            logger.info("Seed skip (NSFW): %s", full_name)
            continue
        image_url = pick_weird_screenshot(
            readme, repo, http_client=readme_fetcher.http_client
        )
        if not image_url:
            logger.info("Seed skip (no visual): %s", full_name)
            continue
        approved = curator.judge([repo], readmes={full_name: readme})
        if not approved:
            logger.info("Seed skip (judge): %s", full_name)
            continue
        payload = curator.generate_copy(repo, readme, image_url)
        if not payload:
            continue
        if storage.weird_reserve_add(repo.id, repo.full_name, payload):
            added += 1
            print(f"+ {full_name}")
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill weird_reserve buffer")
    parser.add_argument(
        "--target",
        type=int,
        default=None,
        help="Reserve size target (default: WEIRD_RESERVE_TARGET)",
    )
    args = parser.parse_args()

    ssl_verify()
    config = load_config()
    setup_logging(config.log_path)
    target = args.target if args.target is not None else config.weird_reserve_target

    if not config.weird_enabled:
        print("WEIRD_ENABLED=false — enable in .env first")
        return 1

    storage = Storage(config.db_path)
    github = GitHubSource(
        token=config.github_token,
        topics=config.topics,
        hot_trends=config.hot_trends,
        min_stars=config.min_stars,
    )
    readme_fetcher = ReadmeFetcher(token=config.github_token)
    try:
        before = storage.weird_reserve_count()
        added_search = refill_weird_reserve(config, storage, github, readme_fetcher)
        added_named = _seed_named_repos(
            config, storage, github, readme_fetcher, target
        )
        after = storage.weird_reserve_count()
        print(
            f"Reserve: {before} → {after} (search +{added_search}, named +{added_named})"
        )
        for row in storage.weird_reserve_list(limit=target):
            print(f"  · {row['full_name']} ({row['added_at'][:16]})")
        return 0
    finally:
        readme_fetcher.close()
        github.close()
        storage.close()


if __name__ == "__main__":
    raise SystemExit(main())
