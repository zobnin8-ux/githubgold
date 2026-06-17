"""Render simplified carousel/reel samples: screenshot vs brand plaque."""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from github_radar.config import load_config
from github_radar.http_ssl import ssl_verify
from github_radar.slides import SAMPLES_DIR, SlideRenderer, build_demo_draft


def _skillshare_copy(draft):
    return replace(
        draft,
        slide_headline="Один sync для всех AI-инструментов",
        slide_body=(
            "Держишь промпты и агенты в одном месте, а skillshare сам раскладывает их "
            "в Claude, Codex, Cursor и ещё 60+ инструментов. Одна команда — и везде актуально. "
            "Плюс встроенная проверка на инъекции."
        ),
        category="AI Dev Tools",
    )


def main() -> int:
    ssl_verify()
    config = load_config()
    out_dir = config.slide_dir / SAMPLES_DIR
    renderer = SlideRenderer(config)
    try:
        screen_draft = build_demo_draft(
            config, "langgenius/dify", hype=8.0, card_number=12
        )
        screen_path = renderer.render_one(
            screen_draft,
            fmt="carousel",
            output_path=out_dir / "simplified_with_screenshot.png",
        )
        print("carousel screenshot:", screen_path)

        plaque_draft = _skillshare_copy(
            build_demo_draft(config, "runkids/skillshare", hype=8.5, card_number=14)
        )
        plaque_path = renderer.render_one(
            plaque_draft,
            fmt="carousel",
            output_path=out_dir / "simplified_with_plaque.png",
        )
        print("carousel plaque:", plaque_path)

        reel_screen = renderer.render_one(
            screen_draft,
            fmt="reel",
            output_path=out_dir / "reel_with_screenshot.png",
        )
        print("reel screenshot:", reel_screen)

        reel_plaque = renderer.render_one(
            plaque_draft,
            fmt="reel",
            output_path=out_dir / "reel_with_plaque.png",
        )
        print("reel plaque:", reel_plaque)
    finally:
        renderer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
