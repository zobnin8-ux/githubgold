"""Tidy data/instagram: latin folders, drop stale renders, hide dev samples."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from github_radar.config import load_config
from github_radar.slides import SAMPLES_DIR

CYRILLIC_FOLDERS = ("\u043a\u0430\u0440\u0443\u0441\u0435\u043b\u044c", "\u0440\u0438\u043b\u0441")
STALE_BATCH_DIRS = ("2026-06-17",)
STALE_TIME_DIRS = ("17-04",)
STALE_REPOS = (
    "microsoft_intelligent-terminal",
    "yvgude_lean-ctx",
    "superset-sh_superset",
)


def _remove_tree(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        shutil.rmtree(path)
        return True
    except OSError as exc:
        print(f"  skip {path}: {exc}")
        return False


def cleanup(slide_dir: Path, *, remove_cyrillic: bool) -> int:
    removed = 0

    for fmt, suffix in (("carousel", "_carousel.png"), ("reels", "_reel.png")):
        base = slide_dir / fmt
        if not base.is_dir():
            continue
        for batch in STALE_BATCH_DIRS:
            if _remove_tree(base / batch):
                print(f"removed {base / batch}")
                removed += 1
        stale_time = base / "2026-06-16"
        for time_dir in STALE_TIME_DIRS:
            if _remove_tree(stale_time / time_dir):
                print(f"removed {stale_time / time_dir}")
                removed += 1
        if stale_time.is_dir():
            for repo in STALE_REPOS:
                stale_file = stale_time / f"{repo}{suffix}"
                if stale_file.is_file():
                    stale_file.unlink()
                    print(f"removed duplicate {stale_file}")
                    removed += 1

    if remove_cyrillic:
        for name in CYRILLIC_FOLDERS:
            path = slide_dir / name
            if path.is_dir() and _remove_tree(path):
                print(f"removed legacy folder {name}")
                removed += 1

    junk = slide_dir / "carousel" / ".tmp.driveupload"
    if junk.is_dir() and _remove_tree(junk):
        removed += 1

    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean slide output folders")
    parser.add_argument(
        "--remove-cyrillic",
        action="store_true",
        help="Delete legacy карусель/рилс folders (after closing file previews)",
    )
    args = parser.parse_args()

    config = load_config()
    slide_dir = config.slide_dir
    print(f"SLIDE_DIR={slide_dir}")
    print(f"dev samples -> {SAMPLES_DIR}/")
    n = cleanup(slide_dir, remove_cyrillic=args.remove_cyrillic)
    print(f"Done ({n} item(s) removed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
