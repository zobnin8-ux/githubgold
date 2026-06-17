"""Re-render collectible cards for published posts (backfill / fix paths)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from github_radar.config import load_config
from github_radar.http_ssl import ssl_verify
from github_radar.slides import SlideRenderer, draft_from_published
from github_radar.timeutil import slide_folder_label
from github_radar.storage import Storage


def main() -> int:
    parser = argparse.ArgumentParser(description="Render slides for published posts")
    parser.add_argument(
        "--last",
        type=int,
        default=3,
        help="How many latest card posts to render (default: 3)",
    )
    parser.add_argument(
        "--card",
        type=str,
        default="",
        help="Comma-separated card numbers instead of --last (e.g. 5,6,7)",
    )
    args = parser.parse_args()

    ssl_verify()
    config = load_config()
    storage = Storage(config.db_path)
    try:
        rows = storage.list_published(limit=100)
        cards = [r for r in rows if r.get("card_number")]
        if args.card.strip():
            wanted = {int(x.strip()) for x in args.card.split(",") if x.strip()}
            cards = [r for r in cards if int(r["card_number"]) in wanted]
            cards = sorted(cards, key=lambda r: int(r["card_number"]))
        else:
            cards = sorted(cards, key=lambda r: int(r["card_number"]), reverse=True)[
                : max(1, args.last)
            ]
            cards = list(reversed(cards))

        if not cards:
            print("No published cards found.")
            return 1

        drafts = [draft_from_published(row, config) for row in cards]
        renderer = SlideRenderer(config)
        try:
            paths = renderer.render_batch(drafts)
        finally:
            renderer.close()
    finally:
        storage.close()

    print(f"Rendered {len(paths)} file(s). TIMEZONE={config.timezone_name}")
    if drafts:
        batch_times = [d.published_at for d in drafts if d.published_at]
        when = min(batch_times) if batch_times else None
        label = slide_folder_label(when, config.timezone)
        print(f"Folder: .../{{carousel|reels}}/{label}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
