from __future__ import annotations

import importlib.util
import json
import math
import shlex
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from ..core.storage import read_json
from ..core.wiki_common import INTEGRATED_STATES
from ..infra.tmux_runner import TmuxRunner

FUTURE_MCP_MODULE = "mcp_servers.llm_wiki_mcp"
RUNNING_JOB_STATUSES = frozenset({"running", "initializing", "starting", "queued"})


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, float) and not math.isfinite(value):
            return default
        return int(value)
    except (OverflowError, TypeError, ValueError):
        return default


def read_jsonl_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _read_report_payload(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) and payload else {}


def latest_json_report(report_dir: Path, pattern: str) -> tuple[Path | None, dict]:
    if not report_dir.exists():
        return None, {}
    candidates = sorted(
        [p for p in report_dir.glob(pattern) if p.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        payload = _read_report_payload(path)
        if payload:
            return path, payload
    return None, {}


def count_markdown_items(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            count += 1
    return count


def raw_source_status(layout) -> dict:
    rows = read_jsonl_rows(layout.registry_path)
    by_kind = Counter(str(row.get("source_kind") or "unknown") for row in rows)
    by_status = Counter(str(row.get("status") or "unknown") for row in rows)
    by_change = Counter(str(row.get("change_state") or "unknown") for row in rows)
    by_quality_action = Counter(
        str((row.get("provenance") or {}).get("quality_action") or "unknown")
        for row in rows
        if isinstance(row.get("provenance"), dict) and (row.get("provenance") or {}).get("quality_action")
    )
    latest_report_path, latest_report = latest_json_report(layout.raw_reports_dir, "normalization-*.json")
    quality_summary = latest_report.get("quality_summary") if isinstance(latest_report.get("quality_summary"), dict) else {}
    quality_counts = quality_summary.get("counts") if isinstance(quality_summary.get("counts"), dict) else {}
    if quality_counts:
        by_quality_action = Counter({str(key): safe_int(value) for key, value in quality_counts.items()})
    return {
        "rows": rows,
        "by_kind": by_kind,
        "by_status": by_status,
        "by_change": by_change,
        "by_quality_action": by_quality_action,
        "quality_summary": quality_summary,
        "latest_report_path": latest_report_path,
        "latest_report": latest_report,
        "registry_exists": layout.registry_path.exists(),
        "ready_count": safe_int(by_status.get("ready", 0)),
    }


def raw_sources_ready(raw_status: dict) -> bool:
    return bool(raw_status.get("registry_exists")) and safe_int(raw_status.get("ready_count"), 0) > 0


def _fallback_report(path: Path) -> tuple[Path | None, dict]:
    payload = _read_report_payload(path)
    return (path, payload) if payload else (None, {})


def tmux_session_alive(session_name: str, *, runner: TmuxRunner | None = None) -> bool:
    name = str(session_name or "").strip()
    if not name:
        return False
    tmux = runner or TmuxRunner()
    if not tmux.available():
        return False
    return tmux.session_exists(name)


def reconcile_tmux_job_status(
    job_status: str,
    tmux_session: str,
    *,
    runner: TmuxRunner | None = None,
) -> dict[str, Any]:
    """Return display status plus stale_running when report says running but tmux is gone."""
    normalized = str(job_status or "").strip().lower() or "unknown"
    session = str(tmux_session or "").strip()
    stale_running = normalized in RUNNING_JOB_STATUSES and bool(session) and not tmux_session_alive(session, runner=runner)
    display_status = "stale" if stale_running else normalized
    return {
        "job_status": display_status,
        "reported_job_status": normalized,
        "stale_running": stale_running,
        "tmux_session_alive": tmux_session_alive(session, runner=runner) if session else False,
    }


def load_wiki_agent_status(reports_dir: Path, *, runner: TmuxRunner | None = None) -> dict[str, Any]:
    report_path = reports_dir / "wiki-agent-run-latest.json"
    report = _read_report_payload(report_path)
    session = str(report.get("tmux_session") or report.get("session_name") or "")
    reported_status = str(report.get("status") or report.get("job_status") or ("ready" if report else "not started"))
    reconciled = reconcile_tmux_job_status(reported_status, session, runner=runner)
    return {
        "tmux_session": session,
        "runtime": str(report.get("runtime") or "ralph-pi"),
        "job_status": reconciled["job_status"],
        "reported_job_status": reconciled["reported_job_status"],
        "stale_running": reconciled["stale_running"],
        "tmux_session_alive": reconciled["tmux_session_alive"],
        "last_progress": str(report.get("last_progress") or report.get("updated_at") or report.get("generated_at") or ""),
        "latest_report_path": report_path if report else None,
        "latest_report": report,
    }


def load_wiki_status(layout, raw_status: dict, *, runner: TmuxRunner | None = None) -> dict:
    report_path, report = latest_json_report(layout.wiki_dir / "reports", "wiki-build-*.json")
    if not report:
        report_path, report = _fallback_report(layout.wiki_dir / "build_report.json")
    review_queue_path = layout.wiki_dir / "review_queue.md"
    raw_rows = [row for row in raw_status.get("rows", []) if isinstance(row, dict)]
    ready_rows = [row for row in raw_rows if str(row.get("status") or "").lower() == "ready"]
    integrated_sources = len(
        [
            row
            for row in ready_rows
            if str(row.get("wiki_status") or "").lower() in INTEGRATED_STATES
        ]
    )
    pending_rows = [
        row
        for row in ready_rows
        if str(row.get("wiki_status") or "").lower() not in INTEGRATED_STATES
        or str(row.get("change_state") or "").lower() == "changed"
    ]
    pending_by_kind = Counter(str(row.get("source_kind") or "unknown") for row in pending_rows)
    changed_source_count = len([row for row in ready_rows if str(row.get("change_state") or "").lower() == "changed"])
    pages_created = safe_int(report.get("pages_created") or report.get("created_pages"), 0)
    pages_updated = safe_int(report.get("pages_updated") or report.get("updated_pages"), 0)
    session = str(report.get("tmux_session") or report.get("tmux_session_name") or f"llm-wiki-{layout.site_root.name}")
    reported_status = str(report.get("status") or report.get("job_status") or ("ready" if report else "not started"))
    reconciled = reconcile_tmux_job_status(reported_status, session, runner=runner)
    return {
        "tmux_session": session,
        "log_path": str(report.get("log_path") or layout.wiki_dir / "log.md"),
        "runtime": str(report.get("runtime") or "python"),
        "job_status": reconciled["job_status"],
        "reported_job_status": reconciled["reported_job_status"],
        "stale_running": reconciled["stale_running"],
        "tmux_session_alive": reconciled["tmux_session_alive"],
        "last_progress": str(report.get("last_progress") or report.get("updated_at") or report.get("generated_at") or ""),
        "pages_created": pages_created,
        "pages_updated": pages_updated,
        "integrated_sources": safe_int(report.get("integrated_sources"), integrated_sources),
        "source_count": len(ready_rows),
        "pending_source_count": len(pending_rows),
        "pending_source_count_by_kind": dict(pending_by_kind),
        "changed_source_count": changed_source_count,
        "review_queue_count": safe_int(report.get("review_queue_count"), count_markdown_items(review_queue_path)),
        "latest_report_path": report_path,
        "latest_report": report,
        "index_path": layout.wiki_dir / "index.md",
        "review_queue_path": review_queue_path,
    }


def wiki_ready(wiki_status: dict) -> bool:
    index_path = Path(wiki_status["index_path"])
    if index_path.exists():
        return True
    content_count = (
        safe_int(wiki_status.get("pages_created"), 0)
        + safe_int(wiki_status.get("pages_updated"), 0)
        + safe_int(wiki_status.get("integrated_sources"), 0)
    )
    return content_count > 0


def load_embedding_status(layout) -> dict:
    report_path, report = latest_json_report(layout.indexes_dir / "reports", "embedding-*.json")
    for fallback_name in ("embedding_status.json", "index_status.json", "zvec_index_manifest.json"):
        fallback = layout.indexes_dir / fallback_name
        if not report:
            report_path, report = _fallback_report(fallback)
    raw_count = safe_int(report.get("raw_index_count") or report.get("raw_documents") or report.get("raw_count"), 0)
    wiki_count = safe_int(report.get("wiki_index_count") or report.get("wiki_documents") or report.get("wiki_count"), 0)
    changed_raw = safe_int(report.get("changed_raw_count") or report.get("changed_raw_documents"), 0)
    changed_wiki = safe_int(report.get("changed_wiki_count") or report.get("changed_wiki_documents"), 0)
    reranker_ready = bool(report.get("reranker_ready") or report.get("rerank_ready"))
    return {
        "raw_index_count": raw_count,
        "wiki_index_count": wiki_count,
        "last_build_time": str(report.get("last_build_time") or report.get("built_at") or report.get("generated_at") or ""),
        "reranker_ready": reranker_ready,
        "changed_document_count": changed_raw + changed_wiki,
        "index_health": str(report.get("index_health") or report.get("status") or ("ready" if raw_count or wiki_count else "missing")),
        "latest_report_path": report_path,
        "latest_report": report,
    }


def _expected_mcp_command(layout) -> list[str]:
    return [sys.executable, "-m", FUTURE_MCP_MODULE, "--site-root", str(layout.site_root)]


def _coerce_command(value: Any) -> list[str]:
    if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
        return value
    if isinstance(value, str) and value.strip():
        return shlex.split(value)
    return []


def _command_module_available(command: list[str]) -> bool:
    if "-m" in command:
        flag_idx = command.index("-m")
        if flag_idx == 0:
            return False
        executable = Path(command[0])
        if executable.name not in {"python", "python3"} and not executable.exists():
            return False
        module_idx = flag_idx + 1
        if module_idx >= len(command):
            return False
        try:
            return importlib.util.find_spec(command[module_idx]) is not None
        except (ImportError, AttributeError, ValueError):
            return False
    if not command or len(command) < 1:
        return False
    command_path = Path(command[0])
    if command_path.suffix == ".py":
        return command_path.is_file()
    if len(command) >= 2:
        script_path = Path(command[1])
        if script_path.suffix == ".py":
            return script_path.is_file()
    return False


def _config_for_command(layout, command: list[str]) -> dict:
    return {
        "mcpServers": {
            f"llm-wiki-{layout.site_root.name}": {
                "command": command[0],
                "args": command[1:],
            }
        }
    }


def load_mcp_status(layout) -> dict:
    report_path, report = latest_json_report(layout.indexes_dir / "reports", "mcp-*.json")
    if not report:
        report_path, report = _fallback_report(layout.indexes_dir / "mcp_status.json")
    expected_command = _expected_mcp_command(layout)
    reported_command = _coerce_command(report.get("server_command"))
    command = reported_command if _command_module_available(reported_command) else []
    if not command and _command_module_available(expected_command):
        command = expected_command
    embedding_status = load_embedding_status(layout)
    config = report.get("config_snippet") if command and isinstance(report.get("config_snippet"), dict) else {}
    if command and not config:
        config = _config_for_command(layout, command)
    return {
        "server_command": " ".join(command),
        "expected_server_command": " ".join(expected_command),
        "server_available": bool(command),
        "config_snippet": config,
        "index_health": str(report.get("index_health") or embedding_status.get("index_health") or "missing"),
        "latest_report_path": report_path,
        "latest_report": report,
    }
