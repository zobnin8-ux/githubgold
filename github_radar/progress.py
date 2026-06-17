"""Cycle progress file for Telegram live updates."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("github_radar.progress")

PHASES = ("trending", "search", "readme", "curator", "publish", "slides")

PHASE_LABELS = {
    "trending": "Trending",
    "search": "Сбор GitHub",
    "readme": "README",
    "curator": "Куратор (Claude)",
    "publish": "Публикация",
    "slides": "Карточки",
    "done": "Готово",
    "error": "Ошибка",
    "idle": "Ожидание",
}

_active: Optional["CycleProgress"] = None


def progress_path(data_dir: Path) -> Path:
    return data_dir / "progress.json"


class CycleProgress:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _write(self, payload: dict[str, Any]) -> None:
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=0),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.debug("Progress write failed: %s", exc)

    def start(self, *, dry_run: bool = False) -> None:
        self._write(
            {
                "status": "running",
                "dry_run": dry_run,
                "phase": "trending",
                "current": 0,
                "total": 0,
                "detail": "",
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def update(
        self,
        phase: str,
        *,
        current: int = 0,
        total: int = 0,
        detail: str = "",
    ) -> None:
        data = read(self.path) or {}
        if data.get("status") not in ("running", None):
            return
        self._write(
            {
                "status": "running",
                "dry_run": data.get("dry_run", False),
                "phase": phase,
                "current": current,
                "total": total,
                "detail": detail[:120],
                "started_at": data.get("started_at"),
            }
        )

    def done(self, *, published: int = 0, detail: str = "") -> None:
        self._write(
            {
                "status": "done",
                "dry_run": read(self.path).get("dry_run", False) if self.path.exists() else False,
                "phase": "done",
                "current": published,
                "total": published,
                "detail": detail,
            }
        )

    def error(self, detail: str) -> None:
        self._write(
            {
                "status": "error",
                "phase": "error",
                "current": 0,
                "total": 0,
                "detail": detail[:200],
            }
        )

    def reset(self) -> None:
        self._write(
            {
                "status": "idle",
                "phase": "idle",
                "current": 0,
                "total": 0,
                "detail": "",
            }
        )


def bind(path: Path) -> CycleProgress:
    global _active
    _active = CycleProgress(path)
    return _active


def get_active() -> Optional[CycleProgress]:
    return _active


def update(
    phase: str,
    *,
    current: int = 0,
    total: int = 0,
    detail: str = "",
) -> None:
    if _active is not None:
        _active.update(phase, current=current, total=total, detail=detail)


def read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def is_running(path: Path) -> bool:
    return read(path).get("status") == "running"


def _bar(current: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "░" * width
    ratio = max(0.0, min(1.0, current / total))
    filled = int(ratio * width)
    if filled == 0 and current > 0:
        filled = 1
    return "█" * filled + "░" * (width - filled)


def _phase_line(
    key: str,
    active_phase: str,
    current: int,
    total: int,
    detail: str,
) -> str:
    label = PHASE_LABELS.get(key, key)
    if key == active_phase:
        if total > 0:
            suffix = f" {current}/{total}"
        elif detail:
            suffix = f" — {detail}"
        else:
            suffix = ""
        return f"▶️ {_bar(current, total)}  {label}{suffix}"
    order = list(PHASES)
    if key in order and active_phase in order:
        if order.index(key) < order.index(active_phase):
            return f"✅ {label}"
    return f"░░░░░░░░░░  {label}  —"


def format_telegram(data: dict[str, Any], *, title: str | None = None) -> str:
    status = data.get("status", "idle")
    phase = data.get("phase", "idle")
    current = int(data.get("current") or 0)
    total = int(data.get("total") or 0)
    detail = str(data.get("detail") or "")
    dry = data.get("dry_run", False)

    if status == "idle" or not data:
        return "🟢 Радар свободен"

    if title is None:
        if status == "done":
            title = "✅ Цикл завершён"
        elif status == "error":
            title = "❌ Ошибка цикла"
        elif dry:
            title = "🔄 Dry-run"
        else:
            title = "🔄 Боевой цикл"

    lines = [title, ""]
    if status == "running":
        for key in PHASES:
            lines.append(
                _phase_line(key, phase, current, total, detail if key == phase else "")
            )
        if detail and phase not in ("search", "readme"):
            lines.append("")
            lines.append(detail[:200])
    elif status == "done":
        if current:
            lines.append(f"Опубликовано: {current}")
        if detail:
            lines.append(detail)
    elif status == "error":
        lines.append(detail or "См. data/radar.log")

    return "\n".join(lines)
