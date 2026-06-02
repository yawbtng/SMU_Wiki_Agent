"""Tmux launcher for the Pi LLM wiki pipeline."""

from __future__ import annotations

import shlex
import shutil
from pathlib import Path
from typing import Any

from ..core.data_root import repo_root
from ..core.site_layout import ensure_layout_for_site_root
from ..core.storage import write_json
from ..core.wiki_common import session_timestamp_slug
from ..app.pi_agent import build_pi_json_command, pi_events_filename
from ..app.tmux_settings import (
    pi_cmd,
    tmux_archive_sessions,
    tmux_session_grace_seconds,
    wiki_builder_runtime,
    wiki_skip_pi,
)
from ..infra.tmux_runner import TmuxRunner
from ..infra.tmux_session_shell import sanitize_tmux_session_name
from ..sources.source_registry import utc_now_iso
from .stepper_status import latest_json_report, tmux_session_alive


def assert_no_concurrent_wiki_build(site_root: Path, *, runner: TmuxRunner | None = None) -> None:
    layout = ensure_layout_for_site_root(Path(site_root))
    report_path = layout.wiki_dir / "reports" / "wiki-build-latest.json"
    if active := _active_session(report_path, runner or TmuxRunner()):
        raise RuntimeError(f"Wiki build already running in tmux session `{active}`.")


def launch_wiki_builder(
    site_root: Path,
    *,
    session_name: str | None = None,
    runner: TmuxRunner | None = None,
    python_executable: str | None = None,
    resume: bool = True,
    rebuild: bool = False,
    runtime: str | None = None,
) -> dict[str, Any]:
    del python_executable
    layout = ensure_layout_for_site_root(Path(site_root))
    report_path = layout.wiki_dir / "reports" / "wiki-build-latest.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    tmux = runner or TmuxRunner()
    name = session_name or _session_name(layout.site_root.name, tmux)
    mode = _normalize_runtime(runtime or wiki_builder_runtime())
    if mode not in {"pi", "python"}:
        return {"ok": False, "error": f"Unsupported wiki builder runtime: {runtime}", "runtime": str(runtime)}
    if active := _active_session(report_path, tmux):
        return {"ok": False, "error": f"Wiki build already running in tmux session `{active}`.", "session_name": active, "runtime": mode}
    events_path = report_path.parent / pi_events_filename("wiki-build")
    command, effective = _pipeline_command(
        layout.site_root,
        resume=resume,
        rebuild=rebuild,
        runtime=mode,
        events_path=events_path,
    )
    archive_path: Path | None = None
    if tmux_archive_sessions():
        archive_dir = layout.wiki_dir / "reports" / "tmux-archives"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / f"{name}.log"
    grace = tmux_session_grace_seconds()
    result = tmux.start(name, command, str(repo_root()), archive_path=archive_path, grace_seconds=grace)
    if result.get("ok"):
        write_json(
            report_path,
            {
                "status": "running",
                "job_status": "running",
                "runtime": effective,
                "site_root": str(layout.site_root),
                "wiki_dir": str(layout.wiki_dir),
                "report_path": str(report_path),
                "tmux_session": name,
                "tmux_archive_path": str(archive_path) if archive_path else "",
                "tmux_grace_seconds": result.get("tmux_grace_seconds", grace),
                "builder_command": command,
                "pi_events_path": str(events_path),
                "resume": resume,
                "rebuild": rebuild,
                "generated_at": utc_now_iso(),
                "updated_at": utc_now_iso(),
            },
        )
    return {**result, "session_name": name, "site_root": str(layout.site_root), "wiki_dir": str(layout.wiki_dir), "report_path": str(report_path), "builder_command": command, "runtime": effective}


def _normalize_runtime(runtime: str) -> str:
    value = str(runtime or "pi").strip().lower().replace("_", "-")
    return "python" if value in {"python", "deterministic"} else "pi" if value in {"pi", "ralph-pi", ""} else value


def _pipeline_command(
    site_root: Path,
    *,
    resume: bool,
    rebuild: bool,
    runtime: str,
    events_path: Path,
) -> tuple[str, str]:
    script = repo_root() / ".pi/skills/llm-wiki-noninteractive/scripts/build_wiki.sh"
    skip_flags: list[str] = []
    if runtime != "pi" or wiki_skip_pi():
        skip_flags.append("--skip-pi")
    shell = "bash " + " ".join(
        shlex.quote(p)
        for p in [
            str(script),
            "--site-root",
            str(site_root),
            "--mode",
            "rebuild" if rebuild else "resume",
            "--skip-smoke",
            *skip_flags,
        ]
    )
    if runtime == "pi" and not wiki_skip_pi() and (pi_bin := shutil.which(pi_cmd())):
        skill = repo_root() / ".pi/skills/llm-wiki-noninteractive"
        command = build_pi_json_command(
            pi_bin=pi_bin,
            prompt=f"Execute: {shell}",
            events_path=events_path,
            skill_paths=[skill],
        )
        return command, "pi"
    return shell, "python"


def _session_name(site_name: str, tmux: TmuxRunner) -> str:
    base = sanitize_tmux_session_name(f"wiki-{site_name}-{session_timestamp_slug(utc_now_iso())}")
    name, suffix, exists = base, 2, getattr(tmux, "session_exists", None)
    while callable(exists) and exists(name):
        name, suffix = f"{base}-{suffix}", suffix + 1
    return name


def _active_session(report_path: Path, tmux: TmuxRunner) -> str | None:
    _, report = latest_json_report(report_path.parent, "wiki-build-*.json")
    if not report:
        return None
    status = str(report.get("status") or report.get("job_status") or "").lower()
    session = str(report.get("tmux_session") or "")
    return session if status in {"running", "initializing", "starting"} and session and tmux_session_alive(session, runner=tmux) else None
