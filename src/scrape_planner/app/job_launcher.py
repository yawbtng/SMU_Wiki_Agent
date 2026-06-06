"""Launch operator Pi jobs in tmux with site-local status artifacts."""

from __future__ import annotations

import json
import shlex
import shutil
import time
from pathlib import Path
from typing import Any

from ..core.data_root import repo_root
from ..core.site_layout import ensure_layout_for_site_root
from ..core.storage import read_json, write_json
from ..core.wiki_common import session_timestamp_slug
from ..infra.tmux_runner import TmuxRunner
from ..infra.tmux_session_shell import sanitize_tmux_session_name
from ..sources.source_registry import utc_now_iso
from ..wiki.stepper_status import reconcile_tmux_job_status, tmux_session_alive
from .operator_skills import OperatorSkillSpec, get_operator_skill, skill_script_path
from .pi_agent import build_pi_json_command, pi_events_filename
from .tmux_settings import pi_cmd, tmux_archive_sessions, tmux_session_grace_seconds

WIKI_RUNNING_EVENT_STALL_SECONDS = 300


def _wiki_runtime_failure(events: list[dict[str, Any]]) -> str | None:
    needles = (
        "no models match pattern",
        "model not available",
        "authentication failed",
        "invalid api key",
    )
    for event in events:
        blob = json.dumps(event, ensure_ascii=True).lower()
        for needle in needles:
            if needle in blob:
                return f"Pi runtime unavailable: {needle}."
    return None


def _file_age_seconds(path_value: Any) -> int | None:
    path_text = str(path_value or "").strip()
    if not path_text:
        return None
    try:
        modified_at = Path(path_text).stat().st_mtime
    except OSError:
        return None
    return max(0, int(time.time() - modified_at))


def _wiki_running_stall(report: dict[str, Any], reconciled: dict[str, Any]) -> tuple[bool, int | None]:
    if str(reconciled.get("job_status") or "").lower() not in {"running", "starting", "initializing", "queued"}:
        return False, None
    if not bool(reconciled.get("tmux_session_alive")):
        return False, None
    age_seconds = _file_age_seconds(report.get("pi_events_path"))
    return (
        age_seconds is not None and age_seconds >= WIKI_RUNNING_EVENT_STALL_SECONDS,
        age_seconds,
    )


def _reconcile_wiki_build_report(report_path: Path, report: dict[str, Any], *, tmux: TmuxRunner, pi_events: list[dict[str, Any]]) -> dict[str, Any]:
    session = str(report.get("tmux_session") or "")
    reported_status = str(report.get("status") or report.get("job_status") or "")
    reconciled = reconcile_tmux_job_status(reported_status, session, runner=tmux)
    runtime_failure = _wiki_runtime_failure(pi_events) if reconciled.get("stale_running") else None
    if runtime_failure and report_path.exists():
        report = {
            **report,
            "status": "failed",
            "job_status": "failed",
            "last_error": runtime_failure,
            "updated_at": utc_now_iso(),
            "job_finished_at": utc_now_iso(),
        }
        write_json(report_path, report)
        reconciled = reconcile_tmux_job_status("failed", session, runner=tmux)
    stalled_running, last_event_age_seconds = _wiki_running_stall(report, reconciled)
    display_status = "stalled" if stalled_running else reconciled["job_status"]
    last_error = str(report.get("last_error") or runtime_failure or "")
    if stalled_running and not last_error:
        age_label = f"{last_event_age_seconds}s" if last_event_age_seconds is not None else "several minutes"
        last_error = f"Pi job is still alive but has not emitted build output for {age_label}."
    return {
        **report,
        "job_status": display_status,
        "reported_job_status": reconciled["reported_job_status"],
        "stale_running": reconciled["stale_running"],
        "stalled_running": stalled_running,
        "last_event_age_seconds": last_event_age_seconds,
        "tmux_session_alive": reconciled["tmux_session_alive"],
        "last_error": last_error,
    }


def site_jobs_report_dir(site_root: Path) -> Path:
    layout = ensure_layout_for_site_root(Path(site_root))
    directory = layout.site_root / "jobs" / "reports"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _active_job_session(report_path: Path, tmux: TmuxRunner) -> str | None:
    if not report_path.exists():
        return None
    report = read_json(report_path, {})
    status = str(report.get("status") or report.get("job_status") or "").lower()
    session = str(report.get("tmux_session") or "")
    if status in {"running", "initializing", "starting"} and session and tmux_session_alive(session, runner=tmux):
        return session
    return None


def launch_operator_job(
    site_root: Path,
    skill_id: str,
    *,
    prompt: str = "",
    extra_args: list[str] | None = None,
    session_name: str | None = None,
    runner: TmuxRunner | None = None,
    allow_concurrent: bool = False,
    rebuild_wiki: bool = False,
) -> dict[str, Any]:
    if skill_id == "llm-wiki-noninteractive":
        from ..wiki.wiki_launcher import launch_wiki_builder

        return launch_wiki_builder(
            site_root,
            session_name=session_name,
            runner=runner,
            rebuild=rebuild_wiki,
        )

    spec = get_operator_skill(skill_id)
    script = skill_script_path(spec)
    if not script.is_file():
        return {
            "ok": False,
            "error": f"Skill script missing: {script}",
            "skill": skill_id,
        }

    layout = ensure_layout_for_site_root(Path(site_root))
    report_dir = site_jobs_report_dir(layout.site_root)
    report_path = report_dir / f"{spec.skill_id}-latest.json"
    tmux = runner or TmuxRunner()
    if not allow_concurrent and (active := _active_job_session(report_path, tmux)):
        return {
            "ok": False,
            "error": f"Job already running in tmux session `{active}`.",
            "skill": skill_id,
            "tmux_session": active,
            "report_path": str(report_path),
        }

    name = session_name or _session_name(spec, layout.site_root.name, tmux)
    events_path = report_dir / pi_events_filename(spec.skill_id)
    shell = _pipeline_command(
        spec,
        layout.site_root,
        script,
        prompt=prompt,
        extra_args=extra_args or [],
        events_path=events_path,
    )
    archive_path: Path | None = None
    if tmux_archive_sessions():
        archive_dir = report_dir / "tmux-archives"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / f"{name}.log"
    grace = tmux_session_grace_seconds()
    result = tmux.start(name, shell, str(repo_root()), archive_path=archive_path, grace_seconds=grace)
    payload = {
        "status": "running" if result.get("ok") else "failed",
        "job_status": "running" if result.get("ok") else "failed",
        "skill": skill_id,
        "prompt": prompt,
        "site_root": str(layout.site_root),
        "report_path": str(report_path),
        "tmux_session": name if result.get("ok") else "",
        "tmux_archive_path": str(archive_path) if archive_path else "",
        "builder_command": shell,
        "pi_events_path": str(events_path),
        "generated_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "error": result.get("error", ""),
    }
    write_json(report_path, payload)
    return {
        **result,
        "skill": skill_id,
        "session_name": name,
        "site_root": str(layout.site_root),
        "report_path": str(report_path),
        "builder_command": shell,
    }


def job_status_payload(site_root: Path, skill_id: str) -> dict[str, Any]:
    if skill_id == "llm-wiki-noninteractive":
        from ..wiki.wiki_launcher import _active_session
        from ..core.site_layout import ensure_layout_for_site_root as layout_for

        layout = layout_for(Path(site_root))
        report_path = layout.wiki_dir / "reports" / "wiki-build-latest.json"
        tmux = TmuxRunner()
        active = _active_session(report_path, tmux)
        report = read_json(report_path, {})
        events_path = report.get("pi_events_path")
        pi_events: list[dict[str, Any]] = []
        if events_path:
            from .pi_agent import read_pi_events_after

            pi_events, _ = read_pi_events_after(Path(events_path), 0, limit=200)
        report = _reconcile_wiki_build_report(report_path, report, tmux=tmux, pi_events=pi_events)
        return {
            "skill": skill_id,
            "report_path": str(report_path),
            "report": report,
            "tmux_session": active or str(report.get("tmux_session") or ""),
            "stale_running": bool(report.get("stale_running")),
            "stalled_running": bool(report.get("stalled_running")),
            "pi_events_path": events_path or "",
            "pi_events": pi_events,
            "generated_at": utc_now_iso(),
        }

    spec = get_operator_skill(skill_id)
    report_path = site_jobs_report_dir(site_root) / f"{spec.skill_id}-latest.json"
    report = read_json(report_path, {})
    tmux = TmuxRunner()
    active = _active_job_session(report_path, tmux)
    stale_running = bool(
        report
        and str(report.get("status") or report.get("job_status") or "").lower()
        in {"running", "starting", "initializing"}
        and not active
    )
    events_path = report.get("pi_events_path")
    pi_events: list[dict[str, Any]] = []
    if events_path:
        from .pi_agent import read_pi_events_after

        pi_events, _ = read_pi_events_after(Path(events_path), 0, limit=200)
    return {
        "skill": skill_id,
        "report_path": str(report_path),
        "report": report,
        "tmux_session": active or str(report.get("tmux_session") or ""),
        "stale_running": stale_running,
        "pi_events_path": events_path or "",
        "pi_events": pi_events,
        "generated_at": utc_now_iso(),
    }


def _session_name(spec: OperatorSkillSpec, site_name: str, tmux: TmuxRunner) -> str:
    base = sanitize_tmux_session_name(f"{spec.session_prefix}-{site_name}-{session_timestamp_slug(utc_now_iso())}")
    name, suffix, exists = base, 2, getattr(tmux, "session_exists", None)
    while callable(exists) and exists(name):
        name, suffix = f"{base}-{suffix}", suffix + 1
    return name


def _pipeline_command(
    spec: OperatorSkillSpec,
    site_root: Path,
    script: Path,
    *,
    prompt: str,
    extra_args: list[str],
    events_path: Path,
) -> str:
    args = [
        str(script),
        "--site-root",
        str(site_root),
        *extra_args,
    ]
    if prompt.strip():
        args.extend(["--prompt", prompt.strip()])
    shell = "bash " + " ".join(shlex.quote(part) for part in args)
    skill_path = repo_root() / ".pi" / "skills" / spec.skill_dir
    pi_prompt = prompt.strip() or f"Execute: {shell}"
    if pi_bin := shutil.which(pi_cmd()):
        return build_pi_json_command(
            pi_bin=pi_bin,
            prompt=pi_prompt,
            events_path=events_path,
            skill_paths=[skill_path],
        )
    return shell
