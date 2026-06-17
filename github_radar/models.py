"""Dataclasses for the GitHub radar pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Repo:
    id: int
    full_name: str
    html_url: str
    description: str
    language: Optional[str]
    stars: int
    forks: int
    open_issues: int
    topics: list[str]
    created_at: datetime
    pushed_at: datetime
    owner_login: str
    default_branch: str
    homepage: Optional[str]
    has_releases: bool
    is_fork: bool
    is_archived: bool
    license: Optional[str] = None

    @property
    def owner(self) -> str:
        return self.full_name.split("/")[0]

    @property
    def name(self) -> str:
        return self.full_name.split("/")[1]


@dataclass
class Features:
    brand_boost: bool = False
    trend_riding: bool = False
    has_real_screenshot: bool = False
    has_gif: bool = False
    mass_appeal: bool = False
    niche_ops: bool = False
    looks_like_library: bool = False
    is_list_or_learning: bool = False

    def to_dict(self) -> dict:
        return {
            "brand_boost": self.brand_boost,
            "trend_riding": self.trend_riding,
            "has_real_screenshot": self.has_real_screenshot,
            "has_gif": self.has_gif,
            "mass_appeal": self.mass_appeal,
            "niche_ops": self.niche_ops,
            "looks_like_library": self.looks_like_library,
            "is_list_or_learning": self.is_list_or_learning,
        }


@dataclass(frozen=True)
class RarityInfo:
    rarity: str
    rarity_label: str
    rarity_stars: int
    accent_color: str
    is_legendary: bool


@dataclass
class Candidate:
    repo: Repo
    readme: str
    features: Features
    hype: float
    freshness: float
    velocity: float
    image_url: Optional[str] = None
    velocity_rank: float = 0.0
    final_score: float = 0.0
    rarity_info: Optional[RarityInfo] = None


@dataclass
class PostDraft:
    repo: Repo
    text_ru: str
    slide_headline: str = ""
    slide_body: str = ""
    slide_bullets: list[str] = field(default_factory=list)
    category: str = ""
    image_url: Optional[str] = None
    readme: str = ""
    hype: float = 0.0
    rarity_info: Optional[RarityInfo] = None
    card_number: Optional[int] = None
    message_id: Optional[int] = None
    published_at: Optional[datetime] = None
    is_weird: bool = False
