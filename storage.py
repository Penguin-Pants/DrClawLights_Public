"""Atomic file writes for the files on the volume."""

import os
import tempfile
from pathlib import Path


def atomic_write(path, data: str | bytes) -> None:
    """Write ``data`` to ``path`` via a temp file and a rename.

    A reader never sees a half-written file, and a failed write leaves the
    old file in place. Each call gets its own temp name, so two writers of
    the same file cannot collide. Raises OSError on failure.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    raw = data.encode("utf-8") if isinstance(data, str) else data
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=p.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
