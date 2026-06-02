from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .tmux_runner import TmuxRunner
from .tmux_session_shell import DEFAULT_GRACE_SECONDS, grace_seconds

TERMINAL_JOB_STATUSES = frozenset({"complete", "completed", "success", "failed", "error", "cancelled", "canceled"})

__all__ = ["DEFAULT_GRACE_SECONDS", "TERMINAL_JOB_STATUSES", "grace_seconds", "reconcile_expired_tmux_sessions"]


def _parse_iso(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _seconds_since(value: str, *, now: datetime) -> float | None:
    parsed = _parse_iso(value)
    if not parsed:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (now - parsed.astimezone(timezone.utc)).total_seconds()


def reconcile_expired_tmux_sessions(
    reports_dir: Path,
    *,
    runner: TmuxRunner | None = None,
    grace: int | None = None,
    session_prefixes: tuple[str, ...] = ("wiki-",),
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Kill tmux sessions whose job finished longer ago than the grace window."""
    tmux = runner or TmuxRunner()
    if not tmux.available() or not reports_dir.exists():
        return []
    grace_value = grace_seconds(grace)
    current = now or datetime.now(timezone.utc)
    actions: list[dict[str, Any]] = []
    seen_sessions: set[str] = set()

    for report_path in sorted(reports_dir.glob("wiki-build-*.json"), key=lambda path: path.stat().st_mtime, reverse=True):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(report, dict):
            continue
        session = str(report.get("tmux_session") or "").strip()
        if not session or session in seen_sessions:
            continue
        if not any(session.startswith(prefix) for prefix in session_prefixes):
            continue
        seen_sessions.add(session)
        status = str(report.get("status") or report.get("job_status") or "").lower()
        if status in {"running", "initializing", "starting", "queued"}:
            continue
        if status not in TERMINAL_JOB_STATUSES:
            continue
        finished_at = str(report.get("job_finished_at") or report.get("updated_at") or report.get("generated_at") or "")
        elapsed = _seconds_since(finished_at, now=current)
        if elapsed is None or elapsed < grace_value:
            continue
        if not tmux.session_exists(session):
            continue
        archive_path = report.get("tmux_archive_path")
        if not archive_path:
            archive_path = str(reports_dir / "tmux-archives" / f"{session}.log")
        archive = Path(str(archive_path))
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.exists():
            archive.write_text(tmux.capture(session, lines=5000), encoding="utf-8")
        kill = tmux.kill(session)
        actions.append(
            {
                "session": session,
                "report_path": str(report_path),
                "archive_path": str(archive),
                "killed": bool(kill.get("ok")),
                "reason": "grace_elapsed",
                "elapsed_seconds": elapsed,
            }
        )
    return actions
