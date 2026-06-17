"""Single-instance lock so only one radar cycle runs at a time."""

from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

logger = logging.getLogger("github_radar.lock")

LOCK_FILES = ("radar.lock", "cycle.lock", "bot.launch.lock")


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


def _terminate_pid(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_TERMINATE = 0x0001
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if not handle:
            return False
        try:
            return bool(ctypes.windll.kernel32.TerminateProcess(handle, 1))
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 9)
        return True
    except OSError:
        return False


def _find_github_radar_pids(pattern: str) -> list[int]:
    own = os.getpid()
    if sys.platform == "win32":
        import subprocess

        script = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -match 'python(w)?\\.exe' -and "
            f"$_.CommandLine -match '{pattern}' }} | "
            "Select-Object -ExpandProperty ProcessId"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        pids: list[int] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line.isdigit():
                continue
            pid = int(line)
            if pid != own:
                pids.append(pid)
        return pids

    import subprocess

    try:
        result = subprocess.run(
            ["pgrep", "-f", pattern.replace("\\.", ".")],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    pids = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            pid = int(line)
            if pid != own:
                pids.append(pid)
    return pids


def find_radar_main_pids() -> list[int]:
    """PIDs of python processes running ``github_radar.main``."""
    return _find_github_radar_pids(r"github_radar\.main")


def find_radar_bot_pids() -> list[int]:
    """PIDs of other python processes running ``github_radar.bot``."""
    return _find_github_radar_pids(r"github_radar\.bot")


@dataclass
class StopEverythingResult:
    killed_main: list[int] = field(default_factory=list)
    killed_bots: list[int] = field(default_factory=list)
    locks_removed: list[str] = field(default_factory=list)
    remaining_main: list[int] = field(default_factory=list)
    remaining_bots: list[int] = field(default_factory=list)


def _remove_locks(data_dir: Path) -> list[str]:
    removed: list[str] = []
    for name in LOCK_FILES:
        lock = data_dir / name
        if not lock.exists():
            continue
        try:
            lock.unlink()
            removed.append(name)
            logger.info("Removed lock file %s", lock)
        except OSError:
            logger.warning("Could not remove lock file %s", lock)
    return removed


def _kill_pids(pids: list[int], label: str) -> list[int]:
    killed: list[int] = []
    for pid in pids:
        if _terminate_pid(pid):
            killed.append(pid)
            logger.info("Stopped %s PID %s", label, pid)
    return killed


def stop_everything(data_dir: Path) -> StopEverythingResult:
    """Stop all radar main/bot processes, remove locks, reset progress."""
    killed_main = _kill_pids(find_radar_main_pids(), "radar main")
    killed_bots = _kill_pids(find_radar_bot_pids(), "bot")
    locks_removed = _remove_locks(data_dir)

    from github_radar.progress import CycleProgress, progress_path

    CycleProgress(progress_path(data_dir)).reset()

    time.sleep(0.4)

    remaining_main = find_radar_main_pids()
    remaining_bots = find_radar_bot_pids()
    if remaining_main or remaining_bots:
        _kill_pids(remaining_main, "radar main")
        _kill_pids(remaining_bots, "bot")
        time.sleep(0.3)
        remaining_main = find_radar_main_pids()
        remaining_bots = find_radar_bot_pids()

    return StopEverythingResult(
        killed_main=killed_main,
        killed_bots=killed_bots,
        locks_removed=locks_removed,
        remaining_main=remaining_main,
        remaining_bots=remaining_bots,
    )


def stop_radar_cycles(data_dir: Path) -> list[int]:
    """Kill all ``github_radar.main`` processes and remove lock files."""
    result = stop_everything(data_dir)
    return result.killed_main
