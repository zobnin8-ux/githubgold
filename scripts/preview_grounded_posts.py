"""Preview grounded posts: show README excerpt vs Claude-generated text."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from github_radar.config import load_config
from github_radar.curator import Curator
from github_radar.github_source import GitHubSource
from github_radar.grounding import readme_sufficient
from github_radar.http_ssl import ssl_verify
from github_radar.hype import compute_hype, extract_features
from github_radar.image_pick import pick_readme_image, pick_weird_screenshot
from github_radar.models import Candidate
from github_radar.readme_fetch import ReadmeFetcher
from github_radar.weird import WeirdCurator

# Repos with rich READMEs for verification (real GitHub names).
SAMPLE_REPOS = [
    "langgenius/dify",
    "knadh/dns.toys",
    "lklynet/hypermind",
]


def _candidate(config, repo, readme) -> Candidate:
    image_url = pick_readme_image(readme, repo)
    features = extract_features(repo, readme, config, image_url=image_url)
    hype = compute_hype(features)
    return Candidate(
        repo=repo,
        readme=readme,
        image_url=image_url,
        features=features,
        hype=hype,
        velocity=0.0,
        freshness=0.0,
        final_score=hype,
    )


def main() -> int:
    ssl_verify()
    config = load_config()
    github = GitHubSource(
        token=config.github_token,
        topics=config.topics,
        hot_trends=config.hot_trends,
        min_stars=config.min_stars,
    )
    readme_fetcher = ReadmeFetcher(token=config.github_token)
    hype_curator = Curator(config)
    weird_curator = WeirdCurator(config)

    shown = 0
    try:
        for full_name in SAMPLE_REPOS:
            repo = github.fetch_repo(full_name)
            if not repo:
                print(f"\n=== SKIP {full_name}: not found ===")
                continue
            readme = readme_fetcher.fetch(repo)
            if not readme_sufficient(readme):
                print(f"\n=== SKIP {full_name}: README too short ({len(readme)} chars) ===")
                continue

            print(f"\n{'=' * 72}")
            print(f"REPO: {full_name}")
            print(f"GitHub description: {repo.description}")
            print(f"\n--- README (first 600 chars) ---")
            print(readme[:600].strip())
            if len(readme) > 600:
                print("…")

            cand = _candidate(config, repo, readme)
            draft = hype_curator.generate_post(cand)
            if draft:
                shown += 1
                print(f"\n--- HYPE POST (grounded) ---")
                print(f"Headline: {draft.slide_headline}")
                print(f"Body: {draft.slide_body}")
                print(f"\nText:\n{draft.text_ru[:500]}")
            else:
                print("\n--- HYPE: skipped (unclear / insufficient) ---")

            image_url = pick_weird_screenshot(
                readme, repo, http_client=readme_fetcher.http_client
            )
            if image_url:
                weird_payload = weird_curator.generate_copy(repo, readme, image_url)
                if weird_payload:
                    print(f"\n--- WEIRD COPY (grounded) ---")
                    print(f"Headline: {weird_payload['slide_headline']}")
                    print(f"Body: {weird_payload['slide_body']}")

            if shown >= 3:
                break

        print(f"\n\nShown {shown} grounded hype post(s).")
        return 0 if shown else 1
    finally:
        readme_fetcher.close()
        github.close()


if __name__ == "__main__":
    raise SystemExit(main())
