"""Render joker «Дичь» card from reserve (grounded copy, real screenshot)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from github_radar.config import load_config
from github_radar.github_source import GitHubSource
from github_radar.http_ssl import ssl_verify
from github_radar.readme_fetch import ReadmeFetcher
from github_radar.slides import SAMPLES_DIR, SlideRenderer
from github_radar.storage import Storage
from github_radar.weird import peek_weird_draft, weird_rarity_info
from dataclasses import replace


def main() -> int:
    ssl_verify()
    config = load_config()
    storage = Storage(config.db_path)
    github = GitHubSource(
        token=config.github_token,
        topics=config.topics,
        hot_trends=config.hot_trends,
        min_stars=config.min_stars,
    )
    readme_fetcher = ReadmeFetcher(token=config.github_token)
    renderer = SlideRenderer(config)
    try:
        draft = peek_weird_draft(config, storage, github, readme_fetcher)
        if not draft:
            print("No weird draft with visual + grounded copy — run seed_weird.py")
            return 1

        draft = replace(draft, card_number=99, rarity_info=weird_rarity_info(config))

        out_dir = config.slide_dir / SAMPLES_DIR
        carousel = renderer.render_one(
            draft,
            fmt="carousel",
            output_path=out_dir / "weird_joker_carousel.png",
        )
        print("carousel:", carousel)
        print("repo:", draft.repo.full_name)
        print("description:", draft.repo.description)
        print("headline:", draft.slide_headline)
        print("body:", draft.slide_body)
        print("image:", draft.image_url)
        return 0
    finally:
        renderer.close()
        readme_fetcher.close()
        github.close()
        storage.close()


if __name__ == "__main__":
    raise SystemExit(main())
