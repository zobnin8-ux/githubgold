"""SQLite storage for published repos and star history."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo


class Storage:
    _EXTRA_COLUMNS: dict[str, str] = {
        "text_ru": "TEXT",
        "slide_hook": "TEXT",
        "slide_headline": "TEXT",
        "slide_body": "TEXT",
        "slide_bullets": "TEXT",
        "category": "TEXT",
        "image_url": "TEXT",
        "license": "TEXT",
        "rarity": "TEXT",
        "rarity_stars": "INTEGER",
        "card_number": "INTEGER",
        "hype": "REAL",
        "stars": "INTEGER",
        "forks": "INTEGER",
        "open_issues": "INTEGER",
    }

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS published (
                repo_id      INTEGER PRIMARY KEY,
                full_name    TEXT NOT NULL,
                published_at TEXT NOT NULL,
                message_id   INTEGER
            );

            CREATE TABLE IF NOT EXISTS star_history (
                repo_id INTEGER NOT NULL,
                stars   INTEGER NOT NULL,
                ts      TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_star_history_repo
                ON star_history(repo_id, ts);
            """
        )
        self._migrate_published_columns()
        self._conn.commit()

    def _migrate_published_columns(self) -> None:
        existing = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(published)").fetchall()
        }
        for name, col_type in self._EXTRA_COLUMNS.items():
            if name not in existing:
                self._conn.execute(
                    f"ALTER TABLE published ADD COLUMN {name} {col_type}"
                )

    def close(self) -> None:
        self._conn.close()

    def is_published(self, repo_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM published WHERE repo_id = ?", (repo_id,)
        ).fetchone()
        return row is not None

    def next_card_number(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(card_number), 0) FROM published"
        ).fetchone()
        return int(row[0]) + 1

    def mark_published(
        self,
        repo_id: int,
        full_name: str,
        *,
        published_at: datetime | None = None,
        message_id: Optional[int] = None,
        text_ru: str | None = None,
        slide_hook: str | None = None,
        slide_headline: str | None = None,
        slide_body: str | None = None,
        slide_bullets: list[str] | None = None,
        category: str | None = None,
        image_url: str | None = None,
        license: str | None = None,
        rarity: str | None = None,
        rarity_stars: int | None = None,
        card_number: int | None = None,
        hype: float | None = None,
        stars: int | None = None,
        forks: int | None = None,
        open_issues: int | None = None,
    ) -> None:
        ts = (published_at or datetime.now(timezone.utc)).isoformat()
        bullets_json = json.dumps(slide_bullets or [], ensure_ascii=False)
        self._conn.execute(
            """
            INSERT OR REPLACE INTO published (
                repo_id, full_name, published_at, message_id,
                text_ru, slide_hook, slide_headline, slide_body, slide_bullets,
                category, image_url, license, rarity, rarity_stars, card_number, hype,
                stars, forks, open_issues
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repo_id,
                full_name,
                ts,
                message_id,
                text_ru,
                slide_hook,
                slide_headline,
                slide_body,
                bullets_json,
                category,
                image_url,
                license,
                rarity,
                rarity_stars,
                card_number,
                hype,
                stars,
                forks,
                open_issues,
            ),
        )
        self._conn.commit()

    def record_stars(self, repo_id: int, stars: int, ts: datetime | None = None) -> None:
        timestamp = (ts or datetime.now(timezone.utc)).isoformat()
        self._conn.execute(
            "INSERT INTO star_history (repo_id, stars, ts) VALUES (?, ?, ?)",
            (repo_id, stars, timestamp),
        )
        self._conn.commit()

    def stars_n_days_ago(self, repo_id: int, days: int = 7) -> Optional[int]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        row = self._conn.execute(
            """
            SELECT stars FROM star_history
            WHERE repo_id = ? AND ts <= ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            (repo_id, cutoff),
        ).fetchone()
        if row:
            return int(row["stars"])

        row = self._conn.execute(
            """
            SELECT stars FROM star_history
            WHERE repo_id = ?
            ORDER BY ts ASC
            LIMIT 1
            """,
            (repo_id,),
        ).fetchone()
        return int(row["stars"]) if row else None

    def list_published(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT *
            FROM published
            ORDER BY published_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_published_for_slides(self, last_n: int = 10) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT *
            FROM published
            WHERE card_number IS NOT NULL
            ORDER BY card_number DESC
            LIMIT ?
            """,
            (last_n,),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def count_published(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM published").fetchone()
        return int(row[0]) if row else 0

    def published_today(self, tz: ZoneInfo | None = None) -> list[dict[str, Any]]:
        from github_radar.timeutil import day_bounds_utc, resolve_timezone

        tz = tz or resolve_timezone(None)
        start_utc, end_utc = day_bounds_utc(tz)
        rows = self._conn.execute(
            """
            SELECT full_name, published_at, message_id
            FROM published
            WHERE published_at >= ? AND published_at < ?
            ORDER BY published_at DESC
            """,
            (start_utc, end_utc),
        ).fetchall()
        return [dict(r) for r in rows]
