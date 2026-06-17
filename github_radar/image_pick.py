"""Pick the best screenshot URL from README."""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from github_radar.models import Repo

logger = logging.getLogger("github_radar.image_pick")

MARKDOWN_IMG = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
LINKED_MD_IMG = re.compile(r"\[![^\]]*\]\(([^)]+)\)\]\(([^)]+)\)", re.IGNORECASE)
HTML_IMG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
HTML_SRC = re.compile(r'\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)
HTML_ALT = re.compile(r'\balt=["\']([^"\']*)["\']', re.IGNORECASE)

JUNK_URL = re.compile(
    r"shields\.io|badge|travis|codecov|coveralls|workflow|status\.svg|dependabot|"
    r"img\.shields|circleci|appveyor|snapcraft|star-history\.com|"
    r"avatars\.githubusercontent\.com|contrib\.rocks|trendshift\.io",
    re.IGNORECASE,
)
VIDEO_URL = re.compile(
    r"youtube\.com|youtu\.be|ytimg\.com|vimeo\.com|/embed/|dailymotion|wistia",
    re.IGNORECASE,
)
VIDEO_FILE = re.compile(
    r"youtube|ytimg|vimeo|video-thumb|play-button|/video\.|watch-the-video",
    re.IGNORECASE,
)
BANNER_URL = re.compile(
    r"wordmark|/hero|banner|header|deploybtn|deploy-to-|sponsor|favicon|logo\.|/logo",
    re.IGNORECASE,
)
JUNK_ALT = re.compile(
    r"\b(logo|wordmark|icon|banner|favicon|avatar|badge|watch the video|play)\b",
    re.IGNORECASE,
)

RASTER_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")
SCREENSHOT_HINTS = (
    "screenshot",
    "preview",
    "demo",
    "screen",
    "ui",
    "home",
    "example",
    "showcase",
    "interface",
    "chat",
    "app",
    "desktop",
    "dashboard",
)
SECTION_BOOST = re.compile(
    r"^(screenshots?|demo|usage|product overview|preview|interface|features|walkthrough)",
    re.IGNORECASE,
)
WIDE_BANNER_RATIO = 2.5
CONTAIN_RATIO = 2.0


@dataclass
class _Candidate:
    url: str
    alt: str
    section: str
    link_target: str = ""


def _strip_md_url(raw: str) -> str:
    raw = raw.strip().strip("<>").split()[0].strip("\"'")
    return raw


def _path_ext(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in RASTER_EXT:
        if path.endswith(ext):
            return ext
    if path.endswith(".svg"):
        return ".svg"
    return ""


def _resolve_url(url: str, repo: Repo) -> str:
    url = _strip_md_url(url)
    if url.startswith("//"):
        return "https:" + url
    if url.startswith(("http://", "https://")):
        if "github.com/" in url and "/blob/" in url:
            return (
                url.replace("https://github.com/", "https://raw.githubusercontent.com/")
                .replace("/blob/", "/")
            )
        if "?raw=true" in url and "github.com/" in url and "/blob/" in url:
            return url.split("?")[0].replace(
                "https://github.com/", "https://raw.githubusercontent.com/"
            ).replace("/blob/", "/")
        return url

    path = url.lstrip("./")
    parts: list[str] = []
    for segment in path.split("/"):
        if segment == "..":
            if parts:
                parts.pop()
        elif segment and segment != ".":
            parts.append(segment)
    normalized = "/".join(parts)
    return (
        f"https://raw.githubusercontent.com/{repo.owner_login}/{repo.name}/"
        f"{repo.default_branch}/{normalized}"
    )


def _is_video_link(url: str) -> bool:
    return bool(VIDEO_URL.search(url.lower()))


def _parse_sections(readme: str) -> list[tuple[int, str]]:
    sections: list[tuple[int, str]] = [(0, "")]
    for match in re.finditer(r"^(#{1,4})\s+(.+)$", readme, re.MULTILINE):
        title = match.group(2).strip()
        sections.append((match.start(), title))
    return sections


def _section_at(pos: int, sections: list[tuple[int, str]]) -> str:
    current = ""
    for start, title in sections:
        if start <= pos:
            current = title
        else:
            break
    return current


def _collect_candidates(readme: str) -> list[_Candidate]:
    sections = _parse_sections(readme)
    found: list[_Candidate] = []
    seen: set[str] = set()
    video_linked: set[str] = set()

    for img_url, link_target in LINKED_MD_IMG.findall(readme):
        img_key = _strip_md_url(img_url)
        if _is_video_link(link_target):
            video_linked.add(img_key)

    def add(url: str, alt: str, pos: int) -> None:
        key = _strip_md_url(url)
        if not key or key in seen:
            return
        seen.add(key)
        found.append(
            _Candidate(
                url=key,
                alt=alt,
                section=_section_at(pos, sections),
                link_target="",
            )
        )

    for match in MARKDOWN_IMG.finditer(readme):
        add(match.group(2), match.group(1), match.start())

    for tag in HTML_IMG.finditer(readme):
        src_m = HTML_SRC.search(tag.group(0))
        if not src_m:
            continue
        alt_m = HTML_ALT.search(tag.group(0))
        add(
            src_m.group(1),
            alt_m.group(1) if alt_m else "",
            tag.start(),
        )

    return [c for c in found if c.url not in video_linked]


def _image_aspect_ratio(data: bytes) -> float | None:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            w, h = img.size
            if h <= 0:
                return None
            return w / h
    except Exception:
        return None


def _probe_aspect(url: str, client: httpx.Client | None) -> float | None:
    if client is None:
        return None
    try:
        response = client.get(url, follow_redirects=True)
        if response.status_code != 200:
            return None
        if "image" not in response.headers.get("content-type", ""):
            if _path_ext(url) not in RASTER_EXT:
                return None
        return _image_aspect_ratio(response.content)
    except Exception as exc:
        logger.debug("aspect probe failed for %s: %s", url, exc)
        return None


def _score_candidate(candidate: _Candidate, aspect: float | None = None) -> int:
    url = candidate.url
    alt = candidate.alt
    if not url:
        return -1000

    low = url.lower()
    alt_low = (alt or "").lower()
    section_low = (candidate.section or "").lower()

    if JUNK_URL.search(low):
        return -1000
    if VIDEO_URL.search(low) or VIDEO_FILE.search(low):
        return -1000
    if BANNER_URL.search(low):
        return -1000

    small = re.search(r"[?&]s=(\d+)", low)
    if small and int(small.group(1)) <= 64:
        return -1000

    if alt and JUNK_ALT.search(alt_low):
        return -1000

    ext = _path_ext(url)
    score = 0

    if ext in RASTER_EXT:
        score += 100
    elif ext == ".svg":
        if any(x in low for x in ("logo", "icon", "sponsor", "badge", "shield", "wordmark")):
            return -1000
        score += 10
    else:
        score -= 20

    if aspect is not None and aspect >= WIDE_BANNER_RATIO:
        return -1000

    if aspect is not None and 1.3 <= aspect <= 2.2:
        score += 15

    for hint in SCREENSHOT_HINTS:
        if hint in low or hint in alt_low:
            score += 25

    section_match = SECTION_BOOST.match(section_low.strip())
    if section_match:
        score += 40

    if "user-images.githubusercontent.com" in low:
        score += 40
    if "/images/" in low and "youtube" not in low and "wordmark" not in low:
        score += 15
    if "/assets/" in low or "/docs/" in low:
        score += 15
    if "static-docs" in low or "raw.githubusercontent.com" in low:
        score += 10
    if "/releases/download/" in low and ext == ".gif":
        score += 30

    if "deploy" in low or "button.svg" in low:
        score -= 50

    return score


def pick_readme_image(
    readme: str,
    repo: Repo,
    *,
    min_score: int = 50,
    http_client: httpx.Client | None = None,
) -> str | None:
    if not readme:
        return None

    candidates = _collect_candidates(readme)
    ranked: list[tuple[int, int, str]] = []

    for idx, candidate in enumerate(candidates):
        resolved = _resolve_url(candidate.url, repo)
        aspect = _probe_aspect(resolved, http_client)
        score = _score_candidate(candidate, aspect)
        if score >= min_score:
            ranked.append((score, idx, resolved))

    if not ranked:
        return None

    ranked.sort(key=lambda x: (-x[0], x[1]))
    return ranked[0][2]


def og_image_url(repo: Repo) -> str:
    owner, name = repo.full_name.split("/", 1)
    return f"https://opengraph.githubassets.com/1/{owner}/{name}"
