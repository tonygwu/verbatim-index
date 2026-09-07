#!/usr/bin/env python3
"""Write a file so a concurrent reader never sees it half-written.

Every clone shares one `data/` checkout, so `data/results.json` is written by
repo-0's grading loop and read at any moment by whichever clone is deploying.
`Path.write_text` truncates the file and then writes several megabytes, which
leaves a window where a reader gets a prefix. `json.load` raises on that, so it
fails loudly rather than publishing a wrong page, but an intermittently failing
deploy is a bad thing to debug months later.

Writing to a temporary file in the same directory and renaming over the target
closes the window. `os.replace` is atomic within a filesystem, so a reader sees
either the whole old file or the whole new one.

grade.py already did this by hand for every grade it writes. This is the same
pattern, named, so the outputs that cross clone boundaries share it.
"""

from __future__ import annotations

import os
from pathlib import Path


def write_atomic(path: str | Path, text: str, encoding: str = "utf-8") -> Path:
    """Replace `path` with `text` in one step, or leave it exactly as it was."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding=encoding) as fh:
            fh.write(text)
            fh.flush()
            # The rename is atomic, but only orders against data already handed
            # to the filesystem. Without this a crash can leave a renamed file
            # with no contents.
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path
