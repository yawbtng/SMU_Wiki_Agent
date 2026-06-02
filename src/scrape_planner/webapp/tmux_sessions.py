"""Site-scoped tmux session listing and manual archive/kill."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..core.storage import read_json, write_json
from ..core.site_layout import ensure_layout_for_site_root
from ..infra.tmux_runner import TmuxRunner
from ..infra.tmux_session_shell import sanitize_tmux_session_name
from ..sources.source_registry import utc_now_iso as utc_now
from ..wiki.stepper_status import tmux_session_alive


def _site_session_prefix(site_id: str) -> str:
    return f"wiki-{sanitize_tmux_session_name(site_id)}"


def _session_belongs_to_site(session: str, site_id: str) -> bool:
    prefix = _site_session_prefix(site_id)
    return session.startswith(prefix) or session.startswith(f"wiki-{site_id}")


def list_site_tmux_sessions_payload(site_id: str, *, site_root_fn) -> dict[str, Any]:
    root = site_root_fn(site_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="site not found")
    layout = ensure_layout_for_site_root(root)
    reports_dir = layout.wiki_dir / "reports"
    tmux = TmuxRunner()
    live = tmux.list_sessions() if tmux.available() else []
    prefix = _site_session_prefix(site_id)
    sessions: list[dict[str, Any]] = []
    seen: set[str] = set()

    for name in sorted(live):
        if not name.startswith(prefix):
            continue
        seen.add(name)
        report_path = reports_dir / "wiki-build-latest.json"
        report = read_json(report_path, {}) if report_path.exists() else {}
        linked = sanitize_tmux_session_name(str(report.get("tmux_session") or "")) == name
        sessions.append(
            {
                "session": name,
                "alive": True,
                "linked_report": str(report_path) if linked else "",
                "job_status": report.get("job_status") if linked else "",
                "pi_events_path": report.get("pi_events_path") if linked else "",
                "tmux_archive_path": report.get("tmux_archive_path") if linked else "",
            }
        )

    wiki_report = read_json(reports_dir / "wiki-build-latest.json", {})
    recorded = sanitize_tmux_session_name(str(wiki_report.get("tmux_session") or ""))
    if recorded and recorded not in seen:
        sessions.append(
            {
                "session": recorded,
                "alive": tmux_session_alive(recorded, runner=tmux),
                "linked_report": str(reports_dir / "wiki-build-latest.json"),
                "job_status": wiki_report.get("job_status"),
                "pi_events_path": wiki_report.get("pi_events_path"),
                "tmux_archive_path": wiki_report.get("tmux_archive_path"),
                "stale_name": recorded != str(wiki_report.get("tmux_session") or "").strip(),
            }
        )

    return {"site_id": site_id, "sessions": sessions, "generated_at": utc_now()}


def archive_site_tmux_session_payload(site_id: str, session: str, *, site_root_fn) -> dict[str, Any]:
    root = site_root_fn(site_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="site not found")
    name = sanitize_tmux_session_name(session.strip())
    if not name or not _session_belongs_to_site(name, site_id):
        raise HTTPException(status_code=400, detail="session does not belong to this site")

    layout = ensure_layout_for_site_root(root)
    reports_dir = layout.wiki_dir / "reports"
    tmux = TmuxRunner()
    if not tmux.available():
        raise HTTPException(status_code=503, detail="tmux not available")

    archive_dir = reports_dir / "tmux-archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{name}.log"
    captured = ""
    if tmux.session_exists(name):
        captured = tmux.capture(name, lines=5000)
        if captured.strip():
            archive_path.write_text(captured, encoding="utf-8")
        kill = tmux.kill(name)
        if not kill.get("ok"):
            raise HTTPException(status_code=500, detail=kill.get("error") or "failed to kill session")
    elif not archive_path.exists():
        raise HTTPException(status_code=404, detail="session not found")

    report_path = reports_dir / "wiki-build-latest.json"
    if report_path.exists():
        report = read_json(report_path, {})
        if sanitize_tmux_session_name(str(report.get("tmux_session") or "")) == name:
            status = str(report.get("status") or report.get("job_status") or "").lower()
            if status in {"running", "initializing", "starting"}:
                report["status"] = "archived"
                report["job_status"] = "archived"
                report["updated_at"] = utc_now()
                report["job_finished_at"] = utc_now()
                report["tmux_archive_path"] = str(archive_path)
                write_json(report_path, report)

    return {
        "site_id": site_id,
        "session": name,
        "archive_path": str(archive_path),
        "killed": True,
        "generated_at": utc_now(),
    }
