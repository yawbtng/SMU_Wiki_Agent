"""Operator job API payloads (Pi skills via tmux)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ..app.job_launcher import job_status_payload, launch_operator_job
from ..app.operator_skills import get_operator_skill, list_operator_skills
from ..sources.source_registry import utc_now_iso as utc_now


def operator_skills_payload() -> dict[str, Any]:
    return {"skills": list_operator_skills(), "generated_at": utc_now()}


def start_site_job_payload(
    site_id: str,
    *,
    skill: str,
    prompt: str = "",
    allow_concurrent: bool = False,
    rebuild_wiki: bool = False,
    site_root_fn,
) -> dict[str, Any]:
    root = site_root_fn(site_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="site not found")
    try:
        get_operator_skill(skill)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = launch_operator_job(
        root,
        skill,
        prompt=prompt,
        allow_concurrent=allow_concurrent,
        rebuild_wiki=rebuild_wiki,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error") or "job launch failed")
    return {
        "site_id": site_id,
        "skill": skill,
        "prompt": prompt,
        "session_name": result.get("session_name") or result.get("tmux_session") or "",
        "report_path": result.get("report_path", ""),
        "pi_events_path": result.get("pi_events_path", ""),
        "builder_command": result.get("builder_command", ""),
        "generated_at": utc_now(),
    }


def site_job_status_payload(site_id: str, skill: str, *, site_root_fn) -> dict[str, Any]:
    root = site_root_fn(site_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="site not found")
    try:
        get_operator_skill(skill)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    status = job_status_payload(root, skill)
    return {"site_id": site_id, **status, "generated_at": utc_now()}
