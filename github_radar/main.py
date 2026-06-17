"""Entry point: one full radar cycle."""

from __future__ import annotations

import argparse
import logging
import sys

from github_radar.config import load_config, find_stale_env_vars
from github_radar.curator import Curator
from github_radar.github_source import GitHubRateLimitError, GitHubSource
from github_radar.http_ssl import ssl_verify
from github_radar.logging_setup import setup_logging
from github_radar.prefilter import build_funnel
from github_radar.process_lock import process_lock
from github_radar.publisher import Publisher
from github_radar.readme_fetch import ReadmeFetcher
from github_radar.storage import Storage

logger = logging.getLogger("github_radar")


def _print_candidate(c) -> None:
    f = c.features
    print(f"\n{'='*60}")
    print(f"  {c.repo.full_name}  (stars {c.repo.stars}, velocity {c.velocity:.1f})")
    print(f"  Hype: {c.hype:.1f}  |  Freshness: {c.freshness:.1f}  |  Final: {c.final_score:.2f}")
    print(
        f"  Features: brand={f.brand_boost} trend={f.trend_riding} "
        f"screenshot={f.has_real_screenshot} gif={f.has_gif} mass={f.mass_appeal}"
    )
    print(
        f"  Flags: niche_ops={f.niche_ops} library={f.looks_like_library} "
        f"list={f.is_list_or_learning}"
    )
    if c.image_url:
        print(f"  Image: {c.image_url}")
    else:
        print("  Image: (none, will use OG card)")


def run_cycle(dry_run: bool = False) -> int:
    config = load_config()
    ssl_verify()
    setup_logging(config.log_path)
    for key, reason in find_stale_env_vars():
        logger.warning("Ignoring .env key %s (%s)", key, reason)
    logger.info("Starting radar cycle (dry_run=%s)", dry_run)

    storage = Storage(config.db_path)
    github = GitHubSource(
        token=config.github_token,
        topics=config.topics,
        hot_trends=config.hot_trends,
        min_stars=config.min_stars,
    )
    readme_fetcher = ReadmeFetcher(token=config.github_token)

    try:
        repos = github.collect_candidates()
        if not repos:
            logger.warning("No repositories collected, exiting")
            return 0

        funnel = build_funnel(repos, config, storage, readme_fetcher, github_source=github)
        if not funnel:
            logger.warning("Empty funnel, nothing to curate")
            return 0

        if dry_run:
            print("\n--- PREFILTER FUNNEL ---")
            for c in funnel:
                _print_candidate(c)

        curator = Curator(config)
        drafts = curator.curate(funnel)

        if not drafts:
            logger.warning("No posts generated")
            return 0

        if dry_run:
            print("\n--- SELECTED & DRAFT POSTS ---")
            for draft in drafts:
                print(f"\n{'='*60}")
                print(f"  {draft.repo.full_name}")
                if draft.image_url:
                    print(f"  Photo: {draft.image_url}")
                else:
                    print("  Photo: OG fallback")
                print("  ---")
                print(draft.text_ru)
            logger.info("Dry run complete: %d drafts, nothing published", len(drafts))
            return 0

        for draft in drafts:
            fresh = github.fetch_repo(draft.repo.full_name)
            if fresh:
                draft.repo = fresh

        publisher = Publisher(config, storage)
        try:
            published = publisher.publish_all(drafts)
            logger.info("Cycle complete: published %d posts", len(published))

            if config.make_slides and published:
                from github_radar.slides import SlideRenderer

                renderer = SlideRenderer(config)
                try:
                    paths = renderer.render_batch(published)
                    logger.info("Rendered %d slide(s)", len(paths))
                finally:
                    renderer.close()

            return len(published)
        finally:
            publisher.close()

    except GitHubRateLimitError as exc:
        logger.error("GitHub rate limit exceeded, aborting cycle: %s", exc)
        return 1
    except Exception:
        logger.exception("Unexpected error during cycle")
        return 1
    finally:
        readme_fetcher.close()
        github.close()
        storage.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Zoloto GitHub radar cycle")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute funnel and generate posts without publishing",
    )
    args = parser.parse_args()

    config = load_config()
    ssl_verify()
    setup_logging(config.log_path)
    lock_path = config.db_path.parent / "radar.lock"

    with process_lock(lock_path) as acquired:
        if not acquired:
            pid = None
            try:
                pid = int(lock_path.read_text(encoding="utf-8").splitlines()[0])
            except (OSError, ValueError, IndexError):
                pass
            msg = (
                "Radar cycle already running"
                + (f" (PID {pid})" if pid else "")
                + f". Lock: {lock_path.resolve()}"
            )
            logger.error(msg)
            print(msg, file=sys.stderr)
            sys.exit(2)

        code = 0 if run_cycle(dry_run=args.dry_run) >= 0 else 1
        sys.exit(code)


if __name__ == "__main__":
    main()
