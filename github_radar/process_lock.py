"""Single-instance lock so only one radar cycle runs at a time."""

from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

logger = logging.getLogger("github_radar.lock")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_lock_pid(path: Path) -> int | None:
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0].strip()
        return int(first)
    except (OSError, ValueError, IndexError):
        return None


class ProcessLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: int | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            pid = _read_lock_pid(self.path)
            if pid is not None and _pid_alive(pid):
                logger.warning(
                    "Radar lock held by PID %s (%s)", pid, self.path
                )
                return False
            try:
                self.path.unlink()
            except OSError:
                logger.warning("Could not remove stale lock %s", self.path)
                return False

        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(self.path, flags)
        except FileExistsError:
            return False

        self._handle = fd
        started = datetime.now(timezone.utc).isoformat()
        payload = f"{os.getpid()}\n{started}\n"
        os.write(fd, payload.encode("utf-8"))
        return True

    def release(self) -> None:
        if self._handle is not None:
            try:
                os.close(self._handle)
            except OSError:
                pass
            self._handle = None
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove lock file %s", self.path)


@contextmanager
def process_lock(path: Path) -> Iterator[bool]:
    lock = ProcessLock(path)
    acquired = lock.acquire()
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()
