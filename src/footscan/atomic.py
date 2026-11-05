"""Swap a finished file into place, also on Windows while someone is reading it.

Every JSON file the studio rewrites (capture.json, a build's status.json) is written whole to a temporary file
first, then renamed over the old one, so a reader sees the old file or the new one, never half of it. On Windows
that rename fails with PermissionError ("Access is denied") while another thread or process has the old file
open: Python's open() there doesn't let anyone delete or replace a file it has open. The readers here only hold
a file for the moment it takes to read it (the model page asks for a build's status every 2 s), so the rename
is tried again for a little while before giving up.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

RETRY_FOR_S = 2.0   # how long to keep trying: far longer than any read of these small files takes
RETRY_EVERY_S = 0.02


def replace(tmp: Path, path: Path, retry_for_s: float | None = None) -> None:
    """``os.replace(tmp, path)``, tried again while it fails with PermissionError (a reader has ``path`` open,
    on Windows), for up to ``retry_for_s`` seconds (default RETRY_FOR_S); then the last error is raised."""
    deadline = time.monotonic() + (RETRY_FOR_S if retry_for_s is None else retry_for_s)
    while True:
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(RETRY_EVERY_S)
