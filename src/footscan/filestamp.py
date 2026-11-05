"""One fingerprint for "has this file been replaced since?", shared by everything that marks work stale.

An insole remembers the stamp of each file it was made from (the foot's model, a shoe's scan, a saved shoe);
when a stamp no longer matches, the insole is stale and has to be made again.
"""

from __future__ import annotations

from pathlib import Path


def file_stamp(path: Path | None) -> str | None:
    """Cheap fingerprint of a file (name, size and modification time): changes when it's replaced or rebuilt.
    None when there's no such file."""
    if path is None or not Path(path).is_file():
        return None
    path = Path(path)
    st = path.stat()
    return f"{path.name}:{st.st_size}:{st.st_mtime_ns}"
