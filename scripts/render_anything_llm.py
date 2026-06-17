"""Render anything-llm carousel + reel with updated card template."""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from github_radar.config import load_config
from github_radar.hype import compute_rarity
from github_radar.http_ssl import ssl_verify
from github_radar.slides import SlideRenderer, build_demo_draft
from github_radar.storage import Storage


def main() -> int:
    ssl_verify()
    config = load_config()
    repo = "Mintplex-Labs/anything-llm"
    out_dir = config.slide_dir / "samples"

    draft = build_demo_draft(config, repo, hype=8.5, card_number=1)

    storage = Storage(config.db_path)
    storage.close()
    if config.db_path.exists():
        conn = sqlite3.connect(config.db_path)
        try:
            row = conn.execute(
                """
                SELECT slide_bullets, category, hype
                FROM published WHERE full_name=?
                ORDER BY published_at DESC LIMIT 1
                """,
                (repo,),
            ).fetchone()
        finally:
            conn.close()
        if row:
            draft = replace(
                draft,
                slide_bullets=json.loads(row[0]) if row[0] else draft.slide_bullets,
                category=row[1] or draft.category,
                hype=row[2] or draft.hype,
                rarity_info=compute_rarity(row[2] or draft.hype or 8.5, config),
            )

    print("image_url:", draft.image_url)

    renderer = SlideRenderer(config)
    try:
        carousel = renderer.render_one(
            draft,
            fmt="carousel",
            output_path=out_dir / "anything-llm_carousel.png",
        )
        reel = renderer.render_one(
            draft,
            fmt="reels",
            output_path=out_dir / "anything-llm_reel.png",
        )
    finally:
        renderer.close()

    print("carousel:", carousel)
    print("reel:", reel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
