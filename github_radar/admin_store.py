"""Persist admin chat id for startup notifications."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_DEFAULT = Path("./data/admin.json")


def _path() -> Path:
    return _DEFAULT


def load_admin() -> dict:
    p = _path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_admin(chat_id: int, user_id: int) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"chat_id": chat_id, "user_id": user_id}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_admin_chat_id(config_admin_user_id: int | None = None) -> Optional[int]:
    data = load_admin()
    cid = data.get("chat_id")
    if cid is not None:
        return int(cid)
    # В личке chat_id совпадает с user_id
    if config_admin_user_id is not None:
        return config_admin_user_id
    return None
