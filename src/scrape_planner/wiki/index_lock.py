from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path

from ..core.site_layout import ensure_layout_for_site_root


@contextmanager
def site_index_write_lock(site_root: Path):
    """Serialize per-site index mutations (build, ingest pipeline index step)."""
    layout = ensure_layout_for_site_root(Path(site_root))
    lock_path = layout.indexes_dir / ".index_write.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield lock_path
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
