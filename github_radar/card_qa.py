"""Pre-save QA invariants for Instagram collectible cards."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from github_radar.curator import BODY_MAX
from github_radar.grounding import readme_sufficient
from github_radar.models import PostDraft, Repo

logger = logging.getLogger("github_radar.card_qa")

SLIDE_BODY_MAX = BODY_MAX  # 200

_FORMAT_SIZES = {
    "carousel": (1080, 1350),
    "reel": (1080, 1920),
}
_FORMAT_ALIASES = {"reels": "reel"}


def normalize_slide_format(fmt: str) -> str:
    key = fmt.strip().lower()
    return _FORMAT_ALIASES.get(key, key)


class CardQAError(Exception):
    """Card failed QA and must not be saved/published."""

    def __init__(self, repo: str, fmt: str, errors: list[str]) -> None:
        self.repo = repo
        self.fmt = fmt
        self.errors = errors
        super().__init__(f"{repo} [{fmt}]: " + "; ".join(errors))


@dataclass
class CardQAResult:
    repo: str
    fmt: str
    png_size: tuple[int, int] = (0, 0)
    png_size_ok: bool = False
    text_fits: bool = False
    body_font_px: float = 0.0
    text_truncated: bool = False
    art_type: str = "unknown"  # screenshot | plaque | missing
    stats_ok: bool = True
    stats_detail: str = ""
    passed: bool = False
    errors: list[str] = field(default_factory=list)

    def log_line(self) -> str:
        size_s = f"{self.png_size[0]}×{self.png_size[1]}" if self.png_size_ok else "—"
        text_s = "да" if self.text_fits else "нет"
        if self.text_truncated:
            text_s += " (…)"
        stats_s = "да" if self.stats_ok else f"нет ({self.stats_detail})"
        status = "OK" if self.passed else "FAIL"
        return (
            f"  QA [{status}] {self.repo} ({self.fmt}) | "
            f"PNG {size_s} | текст {text_s} @{int(self.body_font_px)}px | "
            f"арт {self.art_type} | статы {stats_s}"
        )


def check_png_size(path: Path, fmt: str) -> tuple[bool, tuple[int, int]]:
    from PIL import Image

    fmt = normalize_slide_format(fmt)
    expected = _FORMAT_SIZES.get(fmt, _FORMAT_SIZES["carousel"])
    with Image.open(path) as img:
        actual = img.size
    return actual == expected, actual


def stats_match(draft_repo: Repo, fresh: Optional[Repo]) -> tuple[bool, str]:
    if not fresh:
        return False, "API fetch failed"
    mismatches: list[str] = []
    if draft_repo.stars != fresh.stars:
        mismatches.append(f"stars {draft_repo.stars}!={fresh.stars}")
    if draft_repo.forks != fresh.forks:
        mismatches.append(f"forks {draft_repo.forks}!={fresh.forks}")
    if draft_repo.open_issues != fresh.open_issues:
        mismatches.append(
            f"issues {draft_repo.open_issues}!={fresh.open_issues}"
        )
    if mismatches:
        return False, ", ".join(mismatches)
    return True, ""


def validate_draft_metadata(
    draft: PostDraft,
    *,
    is_published: bool = False,
) -> list[str]:
    """Checks that do not require rendering."""
    errors: list[str] = []
    repo = draft.repo

    if is_published:
        errors.append("дедуп: уже опубликован")

    if not draft.slide_headline.strip():
        errors.append("пустой headline")
    if not draft.slide_body.strip():
        errors.append("пустой slide_body")
    elif len(draft.slide_body) > SLIDE_BODY_MAX:
        errors.append(f"slide_body>{SLIDE_BODY_MAX} символов")

    if not readme_sufficient(draft.readme):
        errors.append("README недостаточен")

    if draft.is_weird:
        if not draft.image_url:
            errors.append("дичь без скриншота")
    return errors


def classify_art_from_html(art: str) -> str:
    if art in ("screenshot", "plaque", "missing"):
        return art
    return "unknown"


def evaluate_dom_qa(page: Any) -> dict[str, Any]:
    """Run in-browser checks after fit-text script."""
    return page.evaluate(
        """() => {
        const block = document.querySelector('.description-block');
        const stats = document.querySelector('.stats-line');
        const body = document.querySelector('.slide-body');
        const artImg = document.querySelector('.art-window img');
        const plaque = document.querySelector('.art-brand-plaque');
        const missing = document.querySelector('.art-missing');
        if (!block || !stats || !body) {
            return { ok: false, reason: 'missing nodes' };
        }
        const br = block.getBoundingClientRect();
        const sr = stats.getBoundingClientRect();
        const gap = sr.top - br.bottom;
        const blockOverflow = block.scrollHeight > block.clientHeight + 2;
        const bodyOverflow = body.scrollHeight > body.clientHeight + 2;
        const textFits = gap >= 10 && !blockOverflow && !bodyOverflow;
        let art = 'missing';
        if (artImg) art = 'screenshot';
        else if (plaque) art = 'plaque';
        else if (missing) art = 'missing';
        return {
            ok: true,
            text_fits: textFits,
            gap_px: gap,
            body_font_px: parseFloat(getComputedStyle(body).fontSize) || 0,
            truncated: body.classList.contains('truncated'),
            art_type: art,
        };
    }"""
    )


def finalize_qa_result(
    result: CardQAResult,
    draft: PostDraft,
    *,
    fresh_repo: Optional[Repo] = None,
) -> CardQAResult:
    meta_errors = validate_draft_metadata(draft)
    result.errors.extend(meta_errors)

    if draft.is_weird and result.art_type != "screenshot":
        result.errors.append(f"дичь: арт={result.art_type}, нужен screenshot")
    if not draft.is_weird and result.art_type == "missing":
        result.errors.append("хайп: нет арта")

    if result.body_font_px > 0 and result.body_font_px < 36:
        result.errors.append(f"body font {result.body_font_px}px < 36")

    if fresh_repo is not None:
        ok, detail = stats_match(draft.repo, fresh_repo)
        result.stats_ok = ok
        result.stats_detail = detail
        if not ok:
            result.errors.append(f"статы: {detail}")

    if not result.png_size_ok:
        result.errors.append("неверный размер PNG")
    if not result.text_fits:
        result.errors.append("текст не влез / наезд на стат-бар")

    result.passed = not result.errors
    return result


def format_qa_report(result: CardQAResult) -> str:
    return result.log_line() + (
        ("\n    → " + "; ".join(result.errors)) if result.errors else ""
    )
