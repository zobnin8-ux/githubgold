"""Full pipeline diagnostic — no secrets printed."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from github_radar.config import load_config
from github_radar.http_ssl import ssl_verify
from github_radar.image_pick import pick_readme_image

ssl_verify()


def ok(msg: str) -> None:
    print(f"  OK  {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")


def main() -> int:
    print("=== Zoloto GitHub diagnostic ===\n")
    errors = 0

    # 1. Config
    print("1. Config (.env)")
    try:
        cfg = load_config()
        ok(f"TELEGRAM_CHANNEL_ID set ({cfg.telegram_channel_id[:5]}...)")
        ok(f"GITHUB_TOKEN set (len={len(cfg.github_token)})")
        ok(f"ANTHROPIC_API_KEY set (len={len(cfg.anthropic_api_key)})")
        ok(f"ANTHROPIC_MODEL={cfg.anthropic_model}")
        ok(f"TELEGRAM_BOT_TOKEN set (len={len(cfg.telegram_bot_token)})")
        ok(f"POSTS_PER_RUN={cfg.posts_per_run}")
        ok(f"MIN_STARS={cfg.min_stars}")
        ok(f"STRICT_NO_LIBS={cfg.strict_no_libs}")
    except Exception as exc:
        fail(str(exc))
        return 1

    import httpx

    client = httpx.Client(timeout=30.0, verify=ssl_verify())

    # 2. GitHub Search
    print("\n2. GitHub Search API")
    try:
        r = client.get(
            "https://api.github.com/search/repositories",
            params={"q": "stars:>500", "per_page": 1},
            headers={
                "Authorization": f"Bearer {cfg.github_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        if r.status_code == 200:
            ok(f"search works, total={r.json().get('total_count')}")
        else:
            fail(f"HTTP {r.status_code}: {r.text[:200]}")
            errors += 1
    except Exception as exc:
        fail(str(exc))
        errors += 1

    # 3. README JSON (no raw redirect)
    print("\n3. README via api.github.com (JSON base64)")
    try:
        r = client.get(
            "https://api.github.com/repos/cli/cli/readme",
            headers={
                "Authorization": f"Bearer {cfg.github_token}",
                "Accept": "application/vnd.github+json",
            },
            follow_redirects=False,
        )
        if r.status_code == 200 and r.json().get("encoding") == "base64":
            ok("readme JSON, no redirect to raw.githubusercontent.com")
            data = r.json()
            content = data.get("content") or ""
            if content:
                import base64

                readme = base64.b64decode(content).decode("utf-8", errors="replace")
                from github_radar.models import Repo
                from datetime import datetime, timezone

                # Minimal stub for image picker test
                repo = Repo(
                    id=0,
                    full_name="cli/cli",
                    html_url="https://github.com/cli/cli",
                    description="",
                    language=None,
                    stars=0,
                    forks=0,
                    open_issues=0,
                    topics=[],
                    created_at=datetime.now(timezone.utc),
                    pushed_at=datetime.now(timezone.utc),
                    owner_login="cli",
                    default_branch="trunk",
                    homepage=None,
                    has_releases=False,
                    is_fork=False,
                    is_archived=False,
                )
                img = pick_readme_image(readme, repo)
                ok(f"image_pick sample: {img or 'none'}")
        else:
            fail(f"HTTP {r.status_code}, redirect={r.headers.get('location', 'none')}")
            errors += 1
    except Exception as exc:
        fail(str(exc))
        errors += 1

    # 4. Anthropic
    print("\n4. Anthropic API")
    try:
        import anthropic

        ac = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        msg = ac.messages.create(
            model=cfg.anthropic_model,
            max_tokens=20,
            messages=[{"role": "user", "content": "Say OK"}],
        )
        text = msg.content[0].text if msg.content else ""
        ok(f"model responded: {text[:40]!r}")
    except Exception as exc:
        fail(str(exc))
        errors += 1

    # 5. Telegram bot + channel
    print("\n5. Telegram Bot API")
    try:
        r = client.get(
            f"https://api.telegram.org/bot{cfg.telegram_bot_token}/getChat",
            params={"chat_id": cfg.telegram_channel_id},
        )
        data = r.json()
        if data.get("ok"):
            title = data["result"].get("title", data["result"].get("username", "?"))
            ok(f"channel accessible: {title}")
        else:
            fail(f"{data.get('description', data)}")
            errors += 1
    except Exception as exc:
        fail(str(exc))
        errors += 1

    try:
        r = client.get(
            f"https://api.telegram.org/bot{cfg.telegram_bot_token}/getMe",
        )
        data = r.json()
        if data.get("ok"):
            ok(f"bot: @{data['result'].get('username')}")
        else:
            fail(str(data))
            errors += 1
    except Exception as exc:
        fail(str(exc))
        errors += 1

    # 6. DB
    print("\n6. Database")
    try:
        import sqlite3

        if cfg.db_path.exists():
            c = sqlite3.connect(cfg.db_path)
            n = c.execute("SELECT COUNT(*) FROM published").fetchone()[0]
            ok(f"published count = {n}")
            c.close()
        else:
            ok("db not created yet (first run)")
    except Exception as exc:
        fail(str(exc))
        errors += 1

    client.close()

    # 7. Card assets + Playwright
    print("\n7. Instagram cards")
    try:
        assets = cfg.templates_dir / "assets"
        logo = assets / "logo.png"
        fonts = assets / "fonts" / "Inter-Regular.woff"
        if logo.exists():
            ok(f"logo.png ({logo.stat().st_size} bytes)")
        else:
            fail("logo.png missing — run: python scripts/setup_card_assets.py")
            errors += 1
        if fonts.exists():
            ok("fonts installed")
        else:
            fail("fonts missing — run: python scripts/setup_card_assets.py")
            errors += 1
        ok(f"MAKE_SLIDES={cfg.make_slides}, SLIDE_FORMATS={cfg.slide_formats}")
        ok(f"TIMEZONE={cfg.timezone_name} -> {cfg.timezone}")
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                p.chromium.launch()
            ok("playwright chromium available")
        except Exception as exc:
            fail(f"playwright: {exc} — run: playwright install chromium")
            errors += 1
    except Exception as exc:
        fail(str(exc))
        errors += 1

    print(f"\n=== Result: {errors} failure(s) ===")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
