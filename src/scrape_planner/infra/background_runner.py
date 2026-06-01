from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def start_detached(command: str, workdir: str, *, log_path: Path | None = None) -> dict[str, Any]:
    """Portable background runner when tmux is unavailable."""
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    stdout_target: int | object = subprocess.DEVNULL
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_target = open(log_path, "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            ["/bin/sh", "-c", command],
            cwd=str(work),
            stdout=stdout_target,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "pid": proc.pid, "log_path": str(log_path) if log_path else ""}
