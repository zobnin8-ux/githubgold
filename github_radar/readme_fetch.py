"""Download README via GitHub API JSON (no redirect to raw.githubusercontent.com)."""

from __future__ import annotations

import base64
import binascii
import logging
import time

import httpx

from github_radar.http_ssl import ssl_verify
from github_radar.models import Repo

logger = logging.getLogger("github_radar.readme_fetch")

GITHUB_API = "https://api.github.com"
README_MAX_LEN = 8000


class ReadmeFetcher:
    def __init__(self, token: str) -> None:
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "zoloto-github-radar/0.1",
            },
            timeout=20.0,
            follow_redirects=False,
            verify=ssl_verify(),
        )
        self._cache: dict[str, str] = {}

    def close(self) -> None:
        self._client.close()

    @property
    def http_client(self) -> httpx.Client:
        return self._client

    def _decode_readme_payload(self, data: dict) -> str:
        content = data.get("content")
        if not content or not isinstance(content, str):
            return ""
        encoding = (data.get("encoding") or "base64").lower()
        if encoding != "base64":
            return ""
        try:
            raw = base64.b64decode(content, validate=False)
            return raw.decode("utf-8", errors="replace")
        except (binascii.Error, UnicodeDecodeError) as exc:
            logger.debug("README decode failed: %s", exc)
            return ""

    def fetch(self, repo: Repo) -> str:
        if repo.full_name in self._cache:
            return self._cache[repo.full_name]

        owner, name = repo.owner, repo.name
        url = f"{GITHUB_API}/repos/{owner}/{name}/readme"

        try:
            response = self._client.get(url)
            if response.status_code == 200:
                text = self._decode_readme_payload(response.json())[:README_MAX_LEN]
                self._cache[repo.full_name] = text
                time.sleep(0.2)
                return text
            if response.status_code == 404:
                logger.debug("No README for %s", repo.full_name)
            else:
                logger.debug(
                    "README API failed for %s: %s %s",
                    repo.full_name,
                    response.status_code,
                    response.text[:120],
                )
        except Exception as exc:
            logger.debug("README fetch failed for %s: %s", repo.full_name, exc)

        self._cache[repo.full_name] = ""
        return ""
