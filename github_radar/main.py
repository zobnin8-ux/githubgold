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
from github_radar.progress import bind, progress_path, update
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


def _print_weird_status(
    config,
    storage,
    *,
    weird_slot: bool,
    weird_draft,
    added: int,
) -> None:
    if not config.weird_enabled:
        print("\n--- WEIRD ---\n  disabled (WEIRD_ENABLED=false)")
        return
    print("\n--- WEIRD ---")
    print(
        f"  Reserve: {storage.weird_reserve_count()}/{config.weird_reserve_target}"
        f" (+{added} this run)"
    )
    print(
        f"  Posted today: {storage.weird_posted_today(config.timezone)}"
        f"/{config.weird_per_day}"
    )
    if weird_slot:
        if weird_draft:
            print(f"  Slot: 1 joker -> {weird_draft.repo.full_name}")
            print(f"  Headline: {weird_draft.slide_headline}")
            print(f"  Body: {weird_draft.slide_body}")
        else:
            print("  Slot: skipped (reserve empty / quality-gate) -> extra hype")
    else:
        print("  Slot: daily quota filled - this run is hype-only")


def run_cycle(dry_run: bool = False) -> int:
    config = load_config()
    ssl_verify()
    setup_logging(config.log_path)
    prog = bind(progress_path(config.db_path.parent))
    prog.start(dry_run=dry_run)

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
            prog.error("Не собрано ни одного репозитория")
            return 0

        funnel = build_funnel(repos, config, storage, readme_fetcher, github_source=github)

        weird_added = 0
        weird_slot = False
        weird_draft = None
        if config.weird_enabled:
            from github_radar.weird import (
                needs_weird_slot,
                peek_weird_draft,
                pop_weird_draft,
                purge_weird_reserve_no_visual,
                refill_weird_reserve,
            )

            purge_weird_reserve_no_visual(
                storage, github, readme_fetcher
            )
            weird_added = refill_weird_reserve(
                config, storage, github, readme_fetcher
            )
            weird_slot = needs_weird_slot(config, storage)

        weird_can_post = (
            config.weird_enabled
            and weird_slot
            and storage.weird_reserve_count() > 0
        )
        if not funnel and not weird_can_post:
            logger.warning("Empty funnel, nothing to curate")
            prog.error("Пустая воронка после README")
            return 0

        if config.weird_enabled:
            funnel = [c for c in funnel if not storage.weird_is_known(c.repo.id)]

        hype_count = config.posts_per_run
        if config.weird_enabled and weird_slot:
            hype_count = max(0, config.posts_per_run - 1)

        if dry_run:
            print("\n--- PREFILTER FUNNEL ---")
            for c in funnel:
                _print_candidate(c)

        update("curator", detail="Claude отбирает и пишет тексты…")
        curator = Curator(config)
        drafts: list = []
        if hype_count > 0 and funnel:
            drafts = curator.curate(funnel, count=hype_count)

        if config.weird_enabled and weird_slot:
            if dry_run:
                weird_draft = peek_weird_draft(
                    config, storage, github, readme_fetcher
                )
            else:
                weird_draft = pop_weird_draft(
                    config, storage, github, readme_fetcher
                )
            if weird_draft:
                drafts.append(weird_draft)

        if (
            config.weird_enabled
            and weird_slot
            and not weird_draft
            and len(drafts) < config.posts_per_run
            and funnel
        ):
            missing = config.posts_per_run - len(drafts)
            used_ids = {d.repo.id for d in drafts}
            remaining = [c for c in funnel if c.repo.id not in used_ids]
            if remaining:
                extra = curator.curate(remaining, count=missing)
                if extra:
                    logger.info(
                        "Weird slot empty - filled %d hype post(s) instead",
                        len(extra),
                    )
                    drafts.extend(extra)

        if config.weird_enabled:
            _print_weird_status(
                config,
                storage,
                weird_slot=weird_slot,
                weird_draft=weird_draft,
                added=weird_added,
            )

        if not drafts:
            logger.warning("No posts generated")
            prog.error("Куратор не сгенерировал посты")
            return 0

        if dry_run:
            print("\n--- SELECTED & DRAFT POSTS ---")
            for draft in drafts:
                print(f"\n{'='*60}")
                tag = " 🃏 ДИЧЬ" if draft.is_weird else ""
                print(f"  {draft.repo.full_name}{tag}")
                if draft.image_url:
                    print(f"  Photo: {draft.image_url}")
                else:
                    print("  Photo: OG fallback")
                print("  ---")
                print(draft.text_ru)

            print("\n--- CARD QA ---")
            from github_radar.card_qa import CardQAError, format_qa_report
            from github_radar.slides import SlideRenderer
            import os
            import tempfile

            renderer = SlideRenderer(config)
            qa_pass = 0
            qa_total = 0
            try:
                for draft in drafts:
                    fresh = github.fetch_repo(draft.repo.full_name)
                    if fresh:
                        draft.repo = fresh
                    already = storage.is_published(draft.repo.id)
                    for fmt in ("carousel", "reel"):
                        qa_total += 1
                        fd, tmpname = tempfile.mkstemp(suffix=f"_{fmt}.png")
                        os.close(fd)
                        tmp = Path(tmpname)
                        try:
                            renderer.render_one(
                                draft,
                                fmt=fmt,
                                output_path=tmp,
                                fresh_repo=fresh,
                                is_already_published=already,
                            )
                            if renderer.last_qa:
                                print(format_qa_report(renderer.last_qa))
                                if renderer.last_qa.passed:
                                    qa_pass += 1
                        except CardQAError as exc:
                            print(
                                f"  QA [FAIL] {exc.repo} ({exc.fmt}) | "
                                + "; ".join(exc.errors)
                            )
                        finally:
                            tmp.unlink(missing_ok=True)
            finally:
                renderer.close()

            print(f"\n  QA итог: {qa_pass}/{qa_total} карточек прошли")
            logger.info(
                "Dry run complete: %d drafts, QA %d/%d",
                len(drafts),
                qa_pass,
                qa_total,
            )
            prog.done(
                published=0,
                detail=f"Dry-run: {len(drafts)} черновиков, QA {qa_pass}/{qa_total}",
            )
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
                    logger.info("Saved %d card(s) to disk", len(paths))
                finally:
                    renderer.close()

            prog.done(published=len(published), detail=f"Постов: {len(published)}")
            return len(published)
        finally:
            publisher.close()

    except GitHubRateLimitError as exc:
        logger.error("GitHub rate limit exceeded, aborting cycle: %s", exc)
        prog.error("GitHub rate limit — подождите и повторите")
        return 1
    except Exception as exc:
        logger.exception("Unexpected error during cycle")
        prog.error(str(exc)[:200])
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
