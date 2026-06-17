"""GitHub repository discovery: Trending (primary) + Search API."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from selectolax.parser import HTMLParser

from github_radar.http_ssl import ssl_verify
from github_radar.models import Repo

logger = logging.getLogger("github_radar.github_source")

GITHUB_API = "https://api.github.com"
TRENDING_URL = "https://github.com/trending"


class GitHubRateLimitError(Exception):
    def __init__(self, reset_at: Optional[int] = None) -> None:
        self.reset_at = reset_at
        super().__init__(f"GitHub rate limit exceeded (reset={reset_at})")


class GitHubSource:
    def __init__(
        self,
        token: str,
        topics: list[str] | None = None,
        hot_trends: frozenset[str] | None = None,
        min_stars: int = 100,
    ) -> None:
        self._token = token
        self._topics = topics or []
        self._hot_trends = list(hot_trends or [])
        self._min_stars = min_stars
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
            verify=ssl_verify(),
        )
        self._releases_cache: dict[str, bool] = {}

    def close(self) -> None:
        self._client.close()

    def _handle_rate_limit(self, response: httpx.Response) -> None:
        if response.status_code in (403, 429):
            reset = response.headers.get("X-RateLimit-Reset")
            reset_at = int(reset) if reset else None
            if reset_at:
                wait = max(reset_at - int(time.time()), 0) + 1
                logger.warning("Rate limited, waiting %s seconds", wait)
                if wait <= 120:
                    time.sleep(wait)
                    return
            raise GitHubRateLimitError(reset_at)

    def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        for attempt in range(2):
            response = self._client.get(url, params=params)
            if response.status_code in (403, 429):
                self._handle_rate_limit(response)
                if attempt == 0:
                    continue
            response.raise_for_status()
            time.sleep(0.3)
            return response
        raise GitHubRateLimitError()

    def _parse_datetime(self, value: str) -> datetime:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)

    def _repo_from_api(self, data: dict[str, Any], has_releases: bool | None = None) -> Repo:
        if has_releases is None:
            has_releases = self._check_releases(data["full_name"])
        license_data = data.get("license") or {}
        license_spdx = license_data.get("spdx_id") if license_data else None
        return Repo(
            id=data["id"],
            full_name=data["full_name"],
            html_url=data["html_url"],
            description=(data.get("description") or "").strip(),
            language=data.get("language"),
            stars=data.get("stargazers_count", 0),
            forks=data.get("forks_count", 0),
            open_issues=data.get("open_issues_count", 0),
            topics=data.get("topics") or [],
            created_at=self._parse_datetime(data["created_at"]),
            pushed_at=self._parse_datetime(data["pushed_at"]),
            owner_login=data["owner"]["login"],
            default_branch=data.get("default_branch") or "main",
            homepage=data.get("homepage") or None,
            has_releases=has_releases,
            is_fork=data.get("fork", False),
            is_archived=data.get("archived", False),
            license=license_spdx,
        )

    def _check_releases(self, full_name: str) -> bool:
        if full_name in self._releases_cache:
            return self._releases_cache[full_name]
        try:
            response = self._get(f"{GITHUB_API}/repos/{full_name}/releases", params={"per_page": 1})
            has = len(response.json()) > 0
        except Exception as exc:
            logger.debug("Releases check failed for %s: %s", full_name, exc)
            has = False
        self._releases_cache[full_name] = has
        return has

    def search_repositories(self, query: str, per_page: int = 50) -> list[Repo]:
        logger.info("Search: %s", query)
        response = self._get(
            f"{GITHUB_API}/search/repositories",
            params={"q": query, "sort": "stars", "order": "desc", "per_page": per_page},
        )
        items = response.json().get("items", [])
        return [self._repo_from_api(item, has_releases=False) for item in items]

    def fetch_repo(self, full_name: str) -> Optional[Repo]:
        try:
            response = self._get(f"{GITHUB_API}/repos/{full_name}")
            return self._repo_from_api(response.json())
        except httpx.HTTPStatusError as exc:
            logger.warning("Failed to fetch repo %s: %s", full_name, exc)
            return None

    def fetch_trending(self, since: str = "daily") -> list[str]:
        url = f"{TRENDING_URL}?since={since}"
        logger.info("Fetching trending: %s", url)
        response = httpx.get(
            url,
            headers={"User-Agent": "zoloto-github-radar/0.4"},
            timeout=30.0,
            follow_redirects=True,
            verify=ssl_verify(),
        )
        response.raise_for_status()
        tree = HTMLParser(response.text)
        names: list[str] = []
        for article in tree.css("article.Box-row"):
            link = article.css_first("h2 a")
            if not link:
                continue
            href = link.attributes.get("href", "").strip("/")
            if "/" in href:
                names.append(href)
        return names

    def collect_candidates(self) -> list[Repo]:
        now = datetime.now(timezone.utc)
        date_7d = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        date_14d = (now - timedelta(days=14)).strftime("%Y-%m-%d")
        date_60d = (now - timedelta(days=60)).strftime("%Y-%m-%d")
        min_s = self._min_stars

        seen_ids: dict[int, Repo] = {}

        for since in ("daily", "weekly"):
            try:
                for full_name in self.fetch_trending(since=since):
                    repo = self.fetch_repo(full_name)
                    if repo and repo.id not in seen_ids:
                        seen_ids[repo.id] = repo
            except Exception as exc:
                logger.error("Trending fetch failed (%s): %s", since, exc)

        queries = [
            f"stars:>{min_s} pushed:>{date_7d}",
            f"created:>{date_60d} stars:>{min_s}",
        ]
        trend_topics = list(dict.fromkeys(self._hot_trends + self._topics))
        for topic in trend_topics:
            queries.append(f"topic:{topic} pushed:>{date_14d} stars:>{min_s}")

        for query in queries:
            try:
                for repo in self.search_repositories(query):
                    if repo.id not in seen_ids:
                        seen_ids[repo.id] = repo
            except GitHubRateLimitError:
                logger.error("Rate limit during search, stopping collection")
                break
            except Exception as exc:
                logger.error("Search failed for query %r: %s", query, exc)

        repos = list(seen_ids.values())
        logger.info("Collected %d unique repositories", len(repos))
        return repos
