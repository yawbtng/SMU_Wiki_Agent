"""Pi agent JSON event stream helpers (pi --mode json)."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any


def pi_events_filename(prefix: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in prefix.strip())
    return f"{safe or 'pi'}-pi-events.jsonl"


def read_pi_events_after(path: Path, offset: int, *, limit: int = 200) -> tuple[list[dict[str, Any]], int]:
    if not path.exists() or offset < 0:
        return [], offset
    events: list[dict[str, Any]] = []
    new_offset = offset
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        while len(events) < limit:
            line = handle.readline()
            if not line:
                break
            new_offset = handle.tell()
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
    return events, new_offset


def active_pi_events_for_site(site_root: Path) -> tuple[Path | None, str]:
    from ..core.site_layout import ensure_layout_for_site_root
    from ..core.storage import read_json
    from ..wiki.stepper_status import tmux_session_alive

    layout = ensure_layout_for_site_root(Path(site_root))

    from ..infra.tmux_session_shell import sanitize_tmux_session_name

    def _live_pi_stream(report: dict[str, Any]) -> bool:
        events = report.get("pi_events_path")
        session = sanitize_tmux_session_name(str(report.get("tmux_session") or ""))
        if not events or not session:
            return False
        return Path(events).exists() and tmux_session_alive(session)

    wiki_report_path = layout.wiki_dir / "reports" / "wiki-build-latest.json"
    wiki_report = read_json(wiki_report_path, {})
    wiki_events = wiki_report.get("pi_events_path")
    if wiki_events and _live_pi_stream(wiki_report):
        return Path(wiki_events), "llm-wiki-noninteractive"

    jobs_dir = layout.site_root / "jobs" / "reports"
    if jobs_dir.is_dir():
        for report_path in sorted(jobs_dir.glob("*-latest.json")):
            report = read_json(report_path, {})
            events = report.get("pi_events_path")
            if events and _live_pi_stream(report):
                return Path(events), str(report.get("skill") or report_path.stem.replace("-latest", ""))
    return None, ""


def summarize_pi_event(event: dict[str, Any]) -> str:
    event_type = str(event.get("type") or "")
    if event_type == "message_update":
        nested = event.get("assistantMessageEvent")
        if isinstance(nested, dict) and nested.get("type") == "text_delta":
            return str(nested.get("delta") or "")
    if event_type == "tool_execution_start":
        return f"[tool start] {event.get('toolName')}"
    if event_type == "tool_execution_end":
        name = event.get("toolName")
        err = event.get("isError")
        return f"[tool end] {name}" + (" (error)" if err else "")
    if event_type in {"agent_start", "turn_start", "message_start"}:
        return f"[{event_type}]"
    if event_type in {"agent_end", "turn_end", "message_end"}:
        return f"[{event_type}]"
    if event_type == "auto_retry_start":
        return f"[retry {event.get('attempt')}/{event.get('maxAttempts')}] {event.get('errorMessage', '')}"
    if event_type == "compaction_start":
        return f"[compaction {event.get('reason')}]"
    return ""


def build_pi_json_command(
    *,
    pi_bin: str,
    prompt: str,
    events_path: Path,
    stderr_path: Path | None = None,
    skill_paths: list[Path] | None = None,
    thinking: str | None = None,
    model: str | None = None,
    extra_pi_args: list[str] | None = None,
) -> str:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    stderr = stderr_path or events_path.with_suffix(".stderr.log")
    stderr.parent.mkdir(parents=True, exist_ok=True)

    pi_args = [pi_bin, "--mode", "json", "--no-skills"]
    if thinking:
        pi_args.extend(["--thinking", thinking])
    if model:
        pi_args.extend(["--model", model])
    for skill_path in skill_paths or []:
        pi_args.extend(["--skill", str(skill_path)])
    if extra_pi_args:
        pi_args.extend(extra_pi_args)
    pi_args.append(prompt)

    pi_invocation = " ".join(shlex.quote(part) for part in pi_args)
    events_q = shlex.quote(str(events_path))
    stderr_q = shlex.quote(str(stderr))
    return (
        f": > {events_q} && "
        f"set -o pipefail; "
        f"{pi_invocation} 2>{stderr_q} | tee -a {events_q}"
    )
