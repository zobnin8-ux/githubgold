"""Cycle progress file for Telegram live updates."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("github_radar.progress")

PHASES = ("trending", "search", "readme", "curator", "publish", "slides")

CARD_PHASES = (
    "trending",
    "search",
    "readme",
    "curator",
    "card_render",
    "card_publish",
    "card_reel",
)

PHASE_LABELS = {
    "trending": "Trending",
    "search": "Сбор GitHub",
    "readme": "README",
    "curator": "Куратор (Claude)",
    "publish": "Публикация",
    "slides": "Карточки",
    "card_render": "Carousel + QA",
    "card_publish": "Telegram (карточка)",
    "card_reel": "Reel (Instagram)",
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
                "telegram_card_mode": True,
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
        telegram_card_mode: bool | None = None,
    ) -> None:
        data = read(self.path) or {}
        if data.get("status") not in ("running", None):
            return
        payload: dict[str, Any] = {
            "status": "running",
            "dry_run": data.get("dry_run", False),
            "phase": phase,
            "current": current,
            "total": total,
            "detail": detail[:120],
            "telegram_card_mode": data.get("telegram_card_mode", True),
            "started_at": data.get("started_at"),
        }
        if telegram_card_mode is not None:
            payload["telegram_card_mode"] = telegram_card_mode
        self._write(payload)

    def done(self, *, published: int = 0, detail: str = "") -> None:
        prev = read(self.path) if self.path.exists() else {}
        self._write(
            {
                "status": "done",
                "dry_run": prev.get("dry_run", False),
                "phase": "done",
                "current": published,
                "total": published,
                "detail": detail,
                "telegram_card_mode": prev.get("telegram_card_mode", True),
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
                "telegram_card_mode": True,
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
    telegram_card_mode: bool | None = None,
) -> None:
    if _active is not None:
        _active.update(
            phase,
            current=current,
            total=total,
            detail=detail,
            telegram_card_mode=telegram_card_mode,
        )


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
    phase_order: tuple[str, ...],
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
    if key in phase_order and active_phase in phase_order:
        if phase_order.index(key) < phase_order.index(active_phase):
            return f"✅ {label}"
    return f"░░░░░░░░░░  {label}  —"


def format_telegram(data: dict[str, Any], *, title: str | None = None) -> str:
    status = data.get("status", "idle")
    phase = data.get("phase", "idle")
    current = int(data.get("current") or 0)
    total = int(data.get("total") or 0)
    detail = str(data.get("detail") or "")
    dry = data.get("dry_run", False)
    card_mode = bool(data.get("telegram_card_mode", True))
    phase_order = CARD_PHASES if card_mode else PHASES

    if status == "idle" or not data:
        return "🟢 Радар свободен"

    if title is None:
        if status == "done":
            title = "✅ Цикл завершён"
        elif status == "error":
            title = "❌ Ошибка цикла"
        elif dry:
            title = "🔄 Dry-run"
        elif card_mode:
            title = "🔄 Боевой цикл · карточки"
        else:
            title = "🔄 Боевой цикл"

    lines = [title, ""]
    if status == "running":
        for key in phase_order:
            lines.append(
                _phase_line(
                    key,
                    phase,
                    current,
                    total,
                    detail if key == phase else "",
                    phase_order,
                )
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
