"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

DEFAULT_OWNER_BOOSTLIST = [
    "apple",
    "google",
    "microsoft",
    "nvidia",
    "openai",
    "anthropic",
    "meta",
    "facebook",
    "vercel",
    "cloudflare",
    "huggingface",
    "mozilla",
    "collabora",
]

DEFAULT_HOT_TRENDS = [
    "ai",
    "agent",
    "agents",
    "llm",
    "claude",
    "gpt",
    "mcp",
    "rag",
    "diffusion",
    "vibe",
    "coding-agent",
    "local-llm",
    "assistant",
    "copilot",
    "voice",
]

DEFAULT_MASS_APPEAL = [
    "windows",
    "macos",
    "mac",
    "ios",
    "android",
    "iphone",
    "browser",
    "chrome",
    "firefox",
    "clipboard",
    "screenshot",
    "wallpaper",
    "phone",
    "desktop",
    "notes",
    "music",
    "photo",
    "video",
]

DEFAULT_NICHE_PENALTY = [
    "kubernetes",
    "helm",
    "terraform",
    "ansible",
    "prometheus",
    "grafana",
    "observability",
    "sysadmin",
    "cron",
    "traceroute",
    "k8s",
]

DEFAULT_TOPICS = [
    "ai",
    "llm",
    "agent",
    "productivity",
    "macos",
    "windows",
    "android",
    "browser",
    "desktop",
    "app",
    "self-hosted",
]


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _parse_list(raw: str) -> frozenset[str]:
    return frozenset(item.strip().lower() for item in raw.split(",") if item.strip())


def _normalize_slide_format(fmt: str) -> str:
    key = fmt.strip().lower()
    return "reel" if key == "reels" else key


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    telegram_channel_id: str
    telegram_admin_user_id: int | None
    github_token: str
    anthropic_api_key: str
    anthropic_model: str
    posts_per_run: int
    hype_utility_ratio: int
    min_stars: int
    strict_no_libs: bool
    prefilter_limit: int
    owner_boostlist: frozenset[str]
    hot_trends: frozenset[str]
    mass_appeal_keywords: frozenset[str]
    niche_penalty_keywords: frozenset[str]
    topics: list[str]
    db_path: Path
    log_path: Path
    readme_scan_limit: int
    make_slides: bool
    slide_formats: list[str]
    slide_dir: Path
    brand_name: str
    brand_handle: str
    brand_tagline: str
    frame_gold: str
    paper_bg: str
    rarity_thresholds: tuple[int, int, int, int]
    templates_dir: Path
    timezone_name: str

    @property
    def timezone(self) -> ZoneInfo:
        from github_radar.timeutil import resolve_timezone

        return resolve_timezone(self.timezone_name)


def _parse_channel_id(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("@"):
        raise ValueError(
            "Use numeric TELEGRAM_CHANNEL_ID (e.g. -1001234567890), not @username. "
            "Forward a post from the channel to @getidsbot to get the ID."
        )
    try:
        channel_id = int(raw)
    except ValueError as exc:
        raise ValueError(f"TELEGRAM_CHANNEL_ID must be a number, got: {raw!r}") from exc
    if channel_id >= 0:
        raise ValueError(
            "Channel ID is usually negative (e.g. -1001234567890). "
            "Forward a post from the channel to @getidsbot to get the ID."
        )
    return str(channel_id)


ENV_KNOWN: frozenset[str] = frozenset(
    {
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHANNEL_ID",
        "TELEGRAM_CHANNEL",
        "TELEGRAM_ADMIN_USER_ID",
        "GITHUB_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL",
        "POSTS_PER_RUN",
        "HYPE_UTILITY_RATIO",
        "MIN_STARS",
        "STRICT_NO_LIBS",
        "PREFILTER_LIMIT",
        "OWNER_BOOSTLIST",
        "HOT_TRENDS",
        "MASS_APPEAL_KEYWORDS",
        "NICHE_PENALTY_KEYWORDS",
        "TOPICS",
        "DB_PATH",
        "LOG_PATH",
        "README_SCAN_LIMIT",
        "MAKE_SLIDES",
        "SLIDE_FORMATS",
        "SLIDE_DIR",
        "TIMEZONE",
        "TEMPLATES_DIR",
        "BRAND_NAME",
        "BRAND_HANDLE",
        "BRAND_TAGLINE",
        "FRAME_GOLD",
        "PAPER_BG",
        "RARITY_THRESHOLDS",
    }
)

ENV_DEPRECATED: dict[str, str] = {
    "EXCLUDE_LISTS": "removed in v5 — no effect",
    "STRICT_TOOLS_ONLY": "renamed to STRICT_NO_LIBS in v5",
    "TELEGRAM_CHANNEL": "use TELEGRAM_CHANNEL_ID",
}


def find_stale_env_vars(env_path: str | Path | None = None) -> list[tuple[str, str]]:
    """Return (key, reason) for keys in .env that load_config does not read."""
    from dotenv import dotenv_values

    path = Path(env_path) if env_path else Path(".env")
    if not path.is_file():
        return []

    stale: list[tuple[str, str]] = []
    for key, value in dotenv_values(path).items():
        if not key or value is None or not str(value).strip():
            continue
        if key in ENV_KNOWN:
            continue
        reason = ENV_DEPRECATED.get(key, "not used by github_radar v5")
        stale.append((key, reason))
    return sorted(stale, key=lambda x: x[0])


def load_config(env_path: str | Path | None = None) -> Config:
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()

    missing: list[str] = []
    for key in ("TELEGRAM_BOT_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY"):
        if not os.getenv(key, "").strip():
            missing.append(key)

    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Copy .env.example to .env and fill in the values."
        )

    channel_raw = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    if not channel_raw:
        channel_raw = os.getenv("TELEGRAM_CHANNEL", "").strip()
    if not channel_raw:
        raise ValueError(
            "Missing required environment variable: TELEGRAM_CHANNEL_ID. "
            "Copy .env.example to .env and fill in the values."
        )
    channel_id = _parse_channel_id(channel_raw)

    admin_raw = os.getenv("TELEGRAM_ADMIN_USER_ID", "").strip()
    admin_user_id: int | None = None
    if admin_raw:
        try:
            admin_user_id = int(admin_raw)
        except ValueError as exc:
            raise ValueError(f"TELEGRAM_ADMIN_USER_ID must be a number, got: {admin_raw!r}") from exc

    topics_raw = os.getenv("TOPICS", ",".join(DEFAULT_TOPICS))
    topics = [t.strip() for t in topics_raw.split(",") if t.strip()]

    return Config(
        telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"].strip(),
        telegram_channel_id=channel_id,
        telegram_admin_user_id=admin_user_id,
        github_token=os.environ["GITHUB_TOKEN"].strip(),
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"].strip(),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6").strip(),
        posts_per_run=int(os.getenv("POSTS_PER_RUN", "3")),
        hype_utility_ratio=int(os.getenv("HYPE_UTILITY_RATIO", "70")),
        min_stars=int(os.getenv("MIN_STARS", "100")),
        strict_no_libs=_bool(os.getenv("STRICT_NO_LIBS"), default=True),
        prefilter_limit=int(os.getenv("PREFILTER_LIMIT", "30")),
        owner_boostlist=_parse_list(
            os.getenv("OWNER_BOOSTLIST", ",".join(DEFAULT_OWNER_BOOSTLIST))
        ),
        hot_trends=_parse_list(os.getenv("HOT_TRENDS", ",".join(DEFAULT_HOT_TRENDS))),
        mass_appeal_keywords=_parse_list(
            os.getenv("MASS_APPEAL_KEYWORDS", ",".join(DEFAULT_MASS_APPEAL))
        ),
        niche_penalty_keywords=_parse_list(
            os.getenv("NICHE_PENALTY_KEYWORDS", ",".join(DEFAULT_NICHE_PENALTY))
        ),
        topics=topics,
        db_path=Path(os.getenv("DB_PATH", "./data/radar.sqlite")),
        log_path=Path(os.getenv("LOG_PATH", "./data/radar.log")),
        readme_scan_limit=int(os.getenv("README_SCAN_LIMIT", "100")),
        make_slides=_bool(os.getenv("MAKE_SLIDES"), default=True),
        slide_formats=[
            _normalize_slide_format(f)
            for f in os.getenv("SLIDE_FORMATS", "carousel").split(",")
            if f.strip()
        ],
        slide_dir=Path(os.getenv("SLIDE_DIR", "./data/instagram")),
        brand_name=os.getenv("BRAND_NAME", "Золото GitHub"),
        brand_handle=os.getenv("BRAND_HANDLE", "@github_gold"),
        brand_tagline=os.getenv("BRAND_TAGLINE", "Хороший код — как золото"),
        frame_gold=os.getenv("FRAME_GOLD", "#D9B65A"),
        paper_bg=os.getenv("PAPER_BG", "#F2EDE2"),
        rarity_thresholds=_parse_rarity_thresholds(
            os.getenv("RARITY_THRESHOLDS", "2,4,7,10")
        ),
        templates_dir=Path(os.getenv("TEMPLATES_DIR", "./templates")),
        timezone_name=os.getenv("TIMEZONE", "Europe/Moscow").strip(),
    )


def _parse_rarity_thresholds(raw: str) -> tuple[int, int, int, int]:
    parts = [int(x.strip()) for x in raw.split(",") if x.strip()]
    if len(parts) != 4:
        return (2, 4, 7, 10)
    return tuple(parts)  # type: ignore[return-value]
