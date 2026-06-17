"""Render one test carousel card (no Telegram publish)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from github_radar.config import load_config
from github_radar.http_ssl import ssl_verify
from github_radar.slides import render_test_card


def main() -> int:
    parser = argparse.ArgumentParser(description="Render test Instagram carousel card")
    parser.add_argument(
        "--repo",
        default="Stirling-Tools/Stirling-PDF",
        help="GitHub full_name with README screenshot (default: Stirling-PDF)",
    )
    args = parser.parse_args()

    ssl_verify()
    config = load_config()
    out = config.slide_dir / "test_card_carousel.png"
    print(f"Rendering {args.repo} -> {out}")
    path = render_test_card(config, output=out, full_name=args.repo)
    print(f"Done: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
