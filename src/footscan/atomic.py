"""Swap a finished file into place, also on Windows while someone is reading it.

Every JSON file the studio rewrites (capture.json, a build's status.json) is written whole to a temporary file
first, then renamed over the old one, so a reader sees the old file or the new one, never half of it. On Windows
that rename fails with PermissionError ("Access is denied") while another thread or process has the old file
open: Python's open() there doesn't let anyone delete or replace a file it has open. The readers here only hold
a file for the moment it takes to read it (the model page asks for a build's status every 2 s), so the rename
is tried again for a little while before giving up. Elsewhere a PermissionError means the folder can't be
written, which waiting doesn't change, so it's raised at once.
"""

from __future__ import annotations

import os
import secrets
import time
from pathlib import Path

RETRY_FOR_S = 2.0   # how long to keep trying: far longer than any read of these small files takes
RETRY_EVERY_S = 0.02
RETRIES = os.name == "nt"  # only Windows refuses to replace a file that's open


def replace(tmp: Path, path: Path, retry_for_s: float | None = None) -> None:
    """``os.replace(tmp, path)``, tried again while it fails with PermissionError (a reader has ``path`` open,
    on Windows), for up to ``retry_for_s`` seconds (default RETRY_FOR_S); then the last error is raised."""
    deadline = time.monotonic() + (RETRY_FOR_S if retry_for_s is None else retry_for_s)
    while True:
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if not RETRIES or time.monotonic() >= deadline:
                raise
            time.sleep(RETRY_EVERY_S)


def temporary_name(path: Path) -> Path:
    """This write's own temporary file beside ``path``: ``.<name>.<random>.tmp``."""
    return path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")


LEFT_BEHIND_AFTER_S = 60.0  # far longer than writing any of these small files takes


def is_temporary(path: Path, left_behind: bool = False) -> bool:
    """One of ``write_utf8``'s temporary files, never a file anyone made. ``left_behind``: and older than
    LEFT_BEHIND_AFTER_S, so not one another request is writing right now (a killed write left it)."""
    path = Path(path)
    if not (path.name.startswith(".") and path.name.endswith(".tmp")):
        return False
    if not left_behind:
        return True
    try:
        return time.time() - path.stat().st_mtime > LEFT_BEHIND_AFTER_S
    except OSError:  # finished (swapped in) meanwhile
        return False


def read_utf8(path: Path, retry_for_s: float | None = None) -> str:
    """The file's text (UTF-8), tried again for a moment while it fails with PermissionError: on Windows,
    opening a file in the instant another thread swaps a new one in over it is refused (a sharing
    violation). Elsewhere, and after RETRY_FOR_S, the error is raised."""
    deadline = time.monotonic() + (RETRY_FOR_S if retry_for_s is None else retry_for_s)
    while True:
        try:
            return Path(path).read_text(encoding="utf-8")
        except PermissionError:
            if not RETRIES or time.monotonic() >= deadline:
                raise
            time.sleep(RETRY_EVERY_S)


def write_utf8(path: Path, text: str) -> None:
    """Write ``text`` (UTF-8) whole to this call's own temporary file beside ``path``, then swap it in
    (``replace``): two writers never share a temporary file, and a reader sees the old file or the new."""
    path = Path(path)
    tmp = temporary_name(path)
    try:
        tmp.write_text(text, encoding="utf-8")
        replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
