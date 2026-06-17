"""Render sample cards for common and legendary rarities."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from github_radar.config import load_config
from github_radar.hype import compute_rarity
from github_radar.http_ssl import ssl_verify
from github_radar.slides import SlideRenderer, build_demo_draft


def main() -> int:
    ssl_verify()
    config = load_config()
    repo = "Stirling-Tools/Stirling-PDF"
    out_dir = config.slide_dir / "samples"
    out_dir.mkdir(parents=True, exist_ok=True)

    common_rarity = compute_rarity(0.5, config)
    legendary_rarity = compute_rarity(12.0, config)

    renderer = SlideRenderer(config)
    try:
        common_draft = build_demo_draft(
            config, repo, hype=0.5, rarity_override=common_rarity, card_number=101
        )
        legendary_draft = build_demo_draft(
            config, repo, hype=12.0, rarity_override=legendary_rarity, card_number=999
        )

        common_path = renderer.render_one(
            common_draft,
            fmt="carousel",
            output_path=out_dir / "sample_rarity_common.png",
        )
        legendary_path = renderer.render_one(
            legendary_draft,
            fmt="carousel",
            output_path=out_dir / "sample_rarity_legendary.png",
        )
        reel_path = renderer.render_one(
            build_demo_draft(config, repo, hype=7.5, card_number=42),
            fmt="reels",
            output_path=out_dir / "sample_reel.png",
        )
    finally:
        renderer.close()

    print(f"Common:    {common_path}")
    print(f"Legendary: {legendary_path}")
    print(f"Reel:      {reel_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
