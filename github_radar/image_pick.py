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
HTML_PICTURE = re.compile(r"<picture\b[^>]*>.*?</picture>", re.IGNORECASE | re.DOTALL)
HTML_SRC = re.compile(r'\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)
HTML_SRCSET = re.compile(r'\bsrcset=["\']([^"\']+)["\']', re.IGNORECASE)
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


def _srcset_best_url(srcset: str) -> str:
    best_url = ""
    best_w = 0
    for part in srcset.split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split()
        url = bits[0]
        width = 0
        if len(bits) > 1 and bits[1].endswith("w"):
            try:
                width = int(bits[1][:-1])
            except ValueError:
                width = 0
        if width >= best_w:
            best_w = width
            best_url = url
    if best_url:
        return best_url
    first = srcset.split(",")[0].strip().split()
    return first[0] if first else ""


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

    for block in HTML_PICTURE.finditer(readme):
        tag = block.group(0)
        pos = block.start()
        alt_m = HTML_ALT.search(tag)
        alt = alt_m.group(1) if alt_m else ""
        for srcset_m in HTML_SRCSET.finditer(tag):
            url = _srcset_best_url(srcset_m.group(1))
            if url:
                add(url, alt, pos)
        src_m = HTML_SRC.search(tag)
        if src_m:
            add(src_m.group(1), alt, pos)

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


def _image_dimensions(data: bytes) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            return img.size
    except Exception:
        return 0, 0


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


def _row_content_ratio(lums: list[float], width: int, height: int) -> float:
    """Share of rows that contain visible UI/text (not flat background)."""
    active_rows = 0
    for y in range(height):
        row = [lums[y * width + x] for x in range(width)]
        if sum(1 for lum in row if lum > 30) / width > 0.05:
            active_rows += 1
    return active_rows / height if height else 0.0


def _content_fill_ratio(small) -> float:
    """Share of pixels that differ from the dominant corner background."""
    from collections import Counter

    pixels = list(small.getdata())
    if not pixels:
        return 0.0

    w, h = small.size
    corner: list[tuple[int, int, int]] = []
    for x0, y0 in ((0, 0), (max(w - 6, 0), 0), (0, max(h - 6, 0)), (max(w - 6, 0), max(h - 6, 0))):
        for y in range(y0, min(y0 + 6, h)):
            for x in range(x0, min(x0 + 6, w)):
                corner.append(pixels[y * w + x])

    if not corner:
        return 0.0

    bg = Counter(corner).most_common(1)[0][0]

    def _dist(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
        return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])

    active = sum(1 for pixel in pixels if _dist(pixel, bg) > 36)
    return active / len(pixels)


def has_rich_visual_content(data: bytes) -> bool:
    """Reject flat / empty terminal / near-monochrome README images."""
    try:
        from PIL import Image, ImageFilter

        with Image.open(io.BytesIO(data)) as img:
            rgb = img.convert("RGB")
            small = rgb.resize((180, 135), Image.Resampling.LANCZOS)
            pixels = list(small.getdata())
            if not pixels:
                return False

            lums = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in pixels]
            n = len(lums)
            mean = sum(lums) / n
            var = sum((x - mean) ** 2 for x in lums) / n
            std = var**0.5

            buckets = {(r // 24, g // 24, b // 24) for r, g, b in pixels}
            color_bins = len(buckets)
            dark_ratio = sum(1 for x in lums if x < 40) / n

            edges = small.convert("L").filter(ImageFilter.FIND_EDGES)
            edge_energy = sum(edges.getdata()) / (255 * n)
            fill = _content_fill_ratio(small)
            row_content = _row_content_ratio(lums, small.size[0], small.size[1])

            if std < 12:
                return False
            if color_bins < 8:
                return False
            if edge_energy < 0.012:
                return False
            if std < 18 and edge_energy < 0.022:
                return False
            if dark_ratio > 0.92 and edge_energy < 0.025:
                return False
            if fill < 0.10:
                return False
            if row_content < 0.45:
                return False
            return True
    except Exception as exc:
        logger.debug("visual content check failed: %s", exc)
        return False


def is_good_card_art(data: bytes) -> bool:
    """README/OG image suitable for the fixed 16:10 art window."""
    if not data or len(data) < 500:
        return False

    aspect = _image_aspect_ratio(data)
    if aspect is not None and (aspect < 0.75 or aspect >= WIDE_BANNER_RATIO):
        return False

    return has_rich_visual_content(data)


def _fetch_image_bytes(url: str, client: httpx.Client | None) -> bytes | None:
    if client is None:
        return None
    try:
        response = client.get(url, follow_redirects=True)
        if response.status_code != 200:
            return None
        if "image" not in response.headers.get("content-type", ""):
            if _path_ext(url) not in RASTER_EXT:
                return None
        return response.content
    except Exception as exc:
        logger.debug("image fetch failed for %s: %s", url, exc)
        return None


def _probe_image(
    url: str, client: httpx.Client | None
) -> tuple[float | None, bool, int]:
    data = _fetch_image_bytes(url, client)
    if not data:
        return None, False, 0
    w, h = _image_dimensions(data)
    area = w * h
    aspect = (w / h) if h > 0 else None
    visual_ok = has_rich_visual_content(data)
    return aspect, visual_ok, area


def _probe_aspect(url: str, client: httpx.Client | None) -> float | None:
    aspect, _, _ = _probe_image(url, client)
    return aspect


def _score_candidate(
    candidate: _Candidate,
    aspect: float | None = None,
    *,
    visual_ok: bool = True,
    pixel_area: int = 0,
) -> int:
    url = candidate.url
    alt = candidate.alt
    if not url:
        return -1000

    low = url.lower()
    alt_low = (alt or "").lower()
    section_low = (candidate.section or "").lower()

    if not visual_ok:
        return -1000

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

    if pixel_area >= 800_000:
        score += 45
    elif pixel_area >= 400_000:
        score += 30
    elif pixel_area >= 150_000:
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
    ranked: list[tuple[int, int, int, str]] = []

    for idx, candidate in enumerate(candidates):
        resolved = _resolve_url(candidate.url, repo)
        aspect, visual_ok, area = _probe_image(resolved, http_client)
        score = _score_candidate(
            candidate, aspect, visual_ok=visual_ok, pixel_area=area
        )
        if score >= min_score:
            ranked.append((score, area, idx, resolved))

    if not ranked:
        return None

    ranked.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return ranked[0][3]


def og_image_url(repo: Repo) -> str:
    owner, name = repo.full_name.split("/", 1)
    return f"https://opengraph.githubassets.com/1/{owner}/{name}"
