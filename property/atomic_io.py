"""Crash-safe writes for the snapshots and price history under ``data/exported/``.

Same pattern as book-ecommerce-scraping / book-restaurant-scraping ``atomic_io.py``.

``open(path, "w")`` truncates the target before new content is written, so a
cron run killed mid-write (timeout, OOM, power loss) leaves an empty or
half-written snapshot. ``write_text_atomic`` writes a temporary file in the
same directory, flushes and fsyncs it, then ``os.replace``-s it over the
target, which is atomic on POSIX and Windows (same volume). Readers see the
old file or the new one, never a partial one.
"""

from __future__ import annotations

import csv
import io
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence


def write_text_atomic(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    """Atomically replace ``path`` with ``text``."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def render_csv(rows: Iterable[dict[str, Any]], fieldnames: Sequence[str], *, header: bool = True) -> str:
    """Render ``rows`` as CSV text in memory (extra keys are ignored)."""

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fieldnames), extrasaction="ignore")
    if header:
        writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def append_csv_atomic(path: str | Path, rows: Iterable[dict[str, Any]], fieldnames: Sequence[str]) -> None:
    """Append ``rows`` by atomically rewriting ``path`` with old + new content.

    History files are small (at most a few hundred rows per run), so a full
    rewrite is cheap and a crash can never leave a torn final row.
    """

    target = Path(path)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\r\n"
    write_text_atomic(target, existing + render_csv(rows, fieldnames, header=not existing))
