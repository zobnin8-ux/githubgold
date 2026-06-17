"""Instagram collectible card renderer (Playwright)."""

from __future__ import annotations

import base64
import html
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from github_radar.config import Config
from github_radar.curator import BODY_MAX, HEADLINE_MAX
from github_radar.http_ssl import ssl_verify
from github_radar.models import PostDraft, RarityInfo
from github_radar.timeutil import slide_folder_parts

logger = logging.getLogger("github_radar.slides")

FORMAT_SIZES = {
    "carousel": (1080, 1350),
    "reel": (1080, 1920),
}

FORMAT_ALIASES = {"reels": "reel"}

FORMAT_FOLDERS = {
    "carousel": "carousel",
    "reel": "reels",
}

SAMPLES_DIR = "_samples"

_RARITY_CSS = {
    "обычная": "rarity-common",
    "необычная": "rarity-uncommon",
    "редкая": "rarity-rare",
    "эпическая": "rarity-epic",
    "легендарная": "legendary",
}

_INVALID_LICENSES = frozenset({"", "NOASSERTION", "NONE", "NULL"})


def format_license(spdx: str | None) -> str:
    if not spdx:
        return "—"
    if spdx.strip().upper() in _INVALID_LICENSES:
        return "—"
    return spdx.strip()


def _split_legacy_hook(text: str) -> tuple[str, str]:
    text = text.strip()
    if not text:
        return "", ""
    for sep in ("\n", ". ", "! ", "? "):
        if sep in text:
            first, rest = text.split(sep, 1)
            return first.strip()[:HEADLINE_MAX], rest.strip()[:BODY_MAX]
    if len(text) <= HEADLINE_MAX:
        return text, ""
    return text[:HEADLINE_MAX].rstrip(), text[HEADLINE_MAX:].strip()[:BODY_MAX]


def _resolve_card_text(draft: PostDraft) -> tuple[str, str]:
    headline = (draft.slide_headline or "").strip()
    body = (draft.slide_body or "").strip()
    if headline:
        return headline, body
    desc = (draft.repo.description or draft.repo.name).strip()
    if desc:
        h, b = _split_legacy_hook(desc)
        return h or draft.repo.name[:HEADLINE_MAX], b or desc[:BODY_MAX]
    return draft.repo.name[:HEADLINE_MAX], ""


def _meta_line(category: str, license_str: str, language: str) -> str:
    parts = [
        (category or "Репозиторий").strip(),
        license_str.strip() or "—",
        (language or "—").strip(),
    ]
    return " • ".join(parts)


def normalize_slide_format(fmt: str) -> str:
    key = fmt.strip().lower()
    return FORMAT_ALIASES.get(key, key)


def _rarity_card_classes(rarity: RarityInfo) -> str:
    css = _RARITY_CSS.get(rarity.rarity, "")
    return css


def _fmt_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 10_000:
        return f"{n / 1_000:.1f}k".replace(".0k", "k")
    if n >= 1_000:
        return f"{n / 1_000:.1f}k".replace(".0k", "k")
    return str(n)


def _stars_html(count: int, max_stars: int = 5) -> str:
    parts = []
    for i in range(1, max_stars + 1):
        cls = "" if i <= count else " dim"
        parts.append(f'<span class="{cls.strip()}">★</span>')
    return "".join(parts)


def _bullets_html(bullets: list[str]) -> str:
    items = []
    for text in bullets[:3]:
        safe = html.escape(text)
        items.append(
            f'<li><span class="bullet-dot"></span><span>{safe}</span></li>'
        )
    while len(items) < 3:
        items.append(
            '<li><span class="bullet-dot"></span><span>Открытый проект</span></li>'
        )
    return "\n".join(items)


def _replace_placeholders(template: str, mapping: dict[str, str]) -> str:
    out = template
    for key, value in mapping.items():
        out = out.replace("{{" + key + "}}", value)
    return out


def _verify_png_size(path: Path, width: int, height: int) -> None:
    from PIL import Image

    with Image.open(path) as img:
        if img.size != (width, height):
            raise ValueError(
                f"Rendered PNG {path.name} is {img.size[0]}x{img.size[1]}, "
                f"expected {width}x{height}"
            )


class SlideRenderer:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._templates_dir = config.templates_dir
        self._card_template = (self._templates_dir / "card.html").read_text(
            encoding="utf-8"
        )
        self._http = httpx.Client(timeout=30.0, verify=ssl_verify(), follow_redirects=True)
        self._cache_dir = config.slide_dir / "_cache" / "images"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        self._http.close()

    def _download_image(self, url: str, slug: str) -> Optional[Path]:
        if not url:
            return None
        import hashlib

        safe = re.sub(r"[^\w.-]", "_", slug)[:80]
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
        dest = self._cache_dir / f"{safe}_{url_hash}.img"
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        try:
            response = self._http.get(url)
            if response.status_code != 200:
                return None
            content_type = response.headers.get("content-type", "")
            if "image" not in content_type and not url.lower().endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".webp")
            ):
                return None
            dest.write_bytes(response.content)
            return dest
        except Exception as exc:
            logger.warning("Image download failed %s: %s", url, exc)
            return None

    def _resolve_screenshot(self, draft: PostDraft) -> Optional[Path]:
        """Return local path to README screenshot, or None for brand plaque."""
        from github_radar.image_pick import is_good_card_art, pick_readme_image

        repo = draft.repo
        slug = repo.full_name.replace("/", "_")

        candidates: list[tuple[str, str]] = []
        seen_urls: set[str] = set()

        def _add(url: str | None, cache_name: str) -> None:
            if not url or url in seen_urls:
                return
            seen_urls.add(url)
            candidates.append((url, cache_name))

        _add(draft.image_url, slug)
        if draft.readme:
            _add(pick_readme_image(draft.readme, repo, http_client=self._http), slug)

        for url, cache_name in candidates:
            path = self._download_image(url, cache_name)
            if not path or not path.exists():
                continue
            if is_good_card_art(path.read_bytes()):
                return path
            logger.info("Rejected card art for %s: %s", repo.full_name, url[:96])

        return None

    def _brand_plaque_html(self, draft: PostDraft) -> str:
        repo = draft.repo
        lang = html.escape(repo.language or "Open Source")
        name = html.escape(repo.name)
        return (
            f'<div class="art-brand-plaque">'
            f'<img class="plaque-nugget" src="assets/logo.png" alt="" />'
            f'<div class="plaque-name">{name}</div>'
            f'<div class="plaque-lang">{lang}</div>'
            f"</div>"
        )

    def _art_html(self, image_path: Optional[Path], draft: PostDraft) -> str:
        if image_path and image_path.exists():
            data = base64.b64encode(image_path.read_bytes()).decode("ascii")
            ext = image_path.suffix.lower().lstrip(".")
            mime = {
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "gif": "image/gif",
                "webp": "image/webp",
            }.get(ext, "image/png")
            return f'<img src="data:{mime};base64,{data}" alt="" />'
        return self._brand_plaque_html(draft)

    def _build_html(self, draft: PostDraft, fmt: str) -> str:
        fmt = normalize_slide_format(fmt)
        width, height = FORMAT_SIZES.get(fmt, FORMAT_SIZES["carousel"])
        repo = draft.repo
        rarity: RarityInfo = draft.rarity_info or RarityInfo(
            rarity="обычная",
            rarity_label="ОБЫЧНАЯ",
            rarity_stars=1,
            accent_color="#6B7280",
            is_legendary=False,
        )
        screenshot = self._resolve_screenshot(draft)
        bullets = draft.slide_bullets or ["", "", ""]
        license_str = format_license(repo.license)
        headline, body = _resolve_card_text(draft)

        mapping = {
            "width": str(width),
            "height": str(height),
            "paper_bg": self._config.paper_bg,
            "frame_gold": self._config.frame_gold,
            "accent_color": rarity.accent_color,
            "card_rarity_classes": _rarity_card_classes(rarity),
            "format_class": "format-reel" if fmt == "reel" else "format-carousel",
            "brand_name": html.escape(self._config.brand_name),
            "brand_handle": html.escape(self._config.brand_handle),
            "brand_tagline": html.escape(self._config.brand_tagline),
            "card_number": str(draft.card_number or 0),
            "repo_full_name": html.escape(repo.full_name),
            "repo_name": html.escape(repo.name),
            "meta_line": html.escape(
                _meta_line(draft.category or "Репозиторий", license_str, repo.language or "—")
            ),
            "slide_headline": html.escape(headline),
            "slide_body": html.escape(body),
            "stars_fmt": _fmt_count(repo.stars),
            "forks_fmt": _fmt_count(repo.forks),
            "issues_fmt": _fmt_count(repo.open_issues),
            "rarity_label": html.escape(rarity.rarity_label),
            "rarity_stars_html": _stars_html(rarity.rarity_stars),
            "bullets_html": _bullets_html(bullets),
            "screenshot_html": self._art_html(screenshot, draft),
        }
        return _replace_placeholders(self._card_template, mapping)

    def render_one(
        self,
        draft: PostDraft,
        fmt: str = "carousel",
        output_path: Optional[Path] = None,
        *,
        browser: Any = None,
        folder_when: datetime | None = None,
    ) -> Path:
        from playwright.sync_api import sync_playwright

        fmt = normalize_slide_format(fmt)
        width, height = FORMAT_SIZES.get(fmt, FORMAT_SIZES["carousel"])
        html_content = self._build_html(draft, fmt)

        if output_path is None:
            when = folder_when or draft.published_at
            date_dir, time_dir = slide_folder_parts(when, self._config.timezone)
            folder_name = FORMAT_FOLDERS.get(fmt, "carousel")
            folder = self._config.slide_dir / folder_name / date_dir / time_dir
            folder.mkdir(parents=True, exist_ok=True)
            slug = draft.repo.full_name.replace("/", "_")
            output_path = folder / f"{slug}_{fmt}.png"

        work_html = self._templates_dir / "_render_work.html"
        work_html.write_text(html_content, encoding="utf-8")

        owns_browser = browser is None
        if owns_browser:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch()
        else:
            playwright = None

        try:
            page = browser.new_page(
                viewport={"width": width, "height": height},
                device_scale_factor=1,
            )
            page.goto(work_html.resolve().as_uri(), wait_until="load", timeout=60_000)
            card = page.locator(".card")
            card.screenshot(
                path=str(output_path),
                type="png",
            )
            page.close()
            _verify_png_size(output_path, width, height)
        finally:
            if owns_browser:
                browser.close()
                if playwright is not None:
                    playwright.stop()

        logger.info("Rendered %s -> %s", draft.repo.full_name, output_path)
        return output_path

    def render_batch(self, drafts: list[PostDraft]) -> list[Path]:
        if not self._config.make_slides:
            return []
        paths: list[Path] = []
        formats = [normalize_slide_format(f) for f in (self._config.slide_formats or ["carousel"])]
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                batch_times = [d.published_at for d in drafts if d.published_at]
                batch_when = min(batch_times) if batch_times else None
                for draft in drafts:
                    for fmt in formats:
                        if fmt not in FORMAT_SIZES:
                            logger.warning("Unknown slide format: %s", fmt)
                            continue
                        try:
                            paths.append(
                                self.render_one(
                                    draft,
                                    fmt=fmt,
                                    browser=browser,
                                    folder_when=batch_when,
                                )
                            )
                        except Exception:
                            logger.exception(
                                "Slide render failed for %s (%s)",
                                draft.repo.full_name,
                                fmt,
                            )
            finally:
                browser.close()
        return paths


def render_test_card(
    config: Config,
    output: Optional[Path] = None,
    *,
    full_name: str = "Stirling-Tools/Stirling-PDF",
    fmt: str = "carousel",
    hype: float = 7.5,
    rarity_override: Optional[RarityInfo] = None,
    card_number: int = 1,
) -> Path:
    """Render a single demo card without publishing."""
    draft = build_demo_draft(
        config,
        full_name,
        hype=hype,
        rarity_override=rarity_override,
        card_number=card_number,
    )
    renderer = SlideRenderer(config)
    try:
        out = output or (
            config.slide_dir / SAMPLES_DIR / f"test_card_{normalize_slide_format(fmt)}.png"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        return renderer.render_one(draft, fmt=fmt, output_path=out)
    finally:
        renderer.close()


def build_demo_draft(
    config: Config,
    full_name: str,
    *,
    hype: float = 7.5,
    rarity_override: Optional[RarityInfo] = None,
    card_number: int = 1,
) -> PostDraft:
    import base64
    from datetime import datetime, timezone

    import httpx

    from github_radar.hype import compute_rarity
    from github_radar.image_pick import og_image_url, pick_readme_image
    from github_radar.models import Repo

    client = httpx.Client(
        timeout=30.0,
        verify=ssl_verify(),
        headers={
            "Authorization": f"Bearer {config.github_token}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        data = client.get(f"https://api.github.com/repos/{full_name}").json()
        if "id" not in data:
            raise RuntimeError(f"Repo not found: {full_name} ({data.get('message', data)})")
        license_data = data.get("license") or {}
        demo_repo = Repo(
            id=data["id"],
            full_name=data["full_name"],
            html_url=data["html_url"],
            description=(data.get("description") or "").strip(),
            language=data.get("language"),
            stars=data.get("stargazers_count", 0),
            forks=data.get("forks_count", 0),
            open_issues=data.get("open_issues_count", 0),
            topics=data.get("topics") or [],
            created_at=datetime.now(timezone.utc),
            pushed_at=datetime.now(timezone.utc),
            owner_login=data["owner"]["login"],
            default_branch=data.get("default_branch") or "main",
            homepage=data.get("homepage"),
            has_releases=True,
            is_fork=data.get("fork", False),
            is_archived=data.get("archived", False),
            license=license_data.get("spdx_id"),
        )
        readme_resp = client.get(f"https://api.github.com/repos/{full_name}/readme")
        readme = ""
        if readme_resp.status_code == 200:
            payload = readme_resp.json()
            if payload.get("encoding") == "base64":
                readme = base64.b64decode(payload["content"]).decode("utf-8", errors="replace")
        image_url = pick_readme_image(readme, demo_repo, http_client=client)
        if not image_url:
            image_url = og_image_url(demo_repo)
    finally:
        client.close()

    rarity = rarity_override or compute_rarity(hype, config)
    return PostDraft(
        repo=demo_repo,
        text_ru="",
        slide_headline="Личный ChatGPT без облака",
        slide_body=(
            "Свой ChatGPT, который живёт у тебя на компе. Кидаешь PDF, Notion "
            "или целую папку — и просто спрашиваешь. Агенты сами крутят задачи "
            "по расписанию, а документы не улетают в чужое облако."
        ),
        slide_bullets=[
            "Чат с документами локально",
            "Агенты и автозадачи",
            "Работает с любым LLM",
        ],
        category="Локальный AI-ассистент",
        image_url=image_url,
        readme=readme,
        hype=hype,
        rarity_info=rarity,
        card_number=card_number,
    )


def draft_from_published(row: dict[str, Any], config: Config) -> PostDraft:
    """Rebuild PostDraft from a published DB row (for slide backfill)."""
    from dataclasses import replace

    from github_radar.hype import compute_rarity

    full_name = row["full_name"]
    hype = float(row["hype"] or 0) or 7.5
    card_number = int(row["card_number"] or 0)
    base = build_demo_draft(config, full_name, hype=hype, card_number=card_number)

    bullets = base.slide_bullets
    if row.get("slide_bullets"):
        try:
            bullets = json.loads(row["slide_bullets"])
        except json.JSONDecodeError:
            pass

    headline = (row.get("slide_headline") or "").strip()
    body = (row.get("slide_body") or "").strip()
    if not headline and row.get("slide_hook"):
        headline, body = _split_legacy_hook(str(row["slide_hook"]))

    published_at: datetime | None = None
    if row.get("published_at"):
        published_at = datetime.fromisoformat(str(row["published_at"]))

    return replace(
        base,
        text_ru=row.get("text_ru") or base.text_ru,
        slide_headline=headline or base.slide_headline,
        slide_body=body or base.slide_body,
        slide_bullets=bullets,
        category=row.get("category") or base.category,
        image_url=row.get("image_url") or base.image_url,
        hype=hype,
        rarity_info=compute_rarity(hype, config),
        card_number=card_number,
        published_at=published_at,
    )
