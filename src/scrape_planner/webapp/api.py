from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..app import APP_STATE_DEFAULTS
from ..app.repositories import AppStateRepository, SiteArtifactRepository, SiteStatusReadModel
from ..agent_run_metrics import AgentRunMetricsRepository, STANDARD_WINDOWS, build_embedding_metric_event
from ..run_persistence import read_page_states, read_run_events, read_run_status
from ..scrape.scrape_url_selection import urls_for_site_scrape
from ..scrape.scrape_worker import ScrapeRunner
from ..sitemap_discovery import discover_site_urls, normalize_site_url
from ..state import RunStateStore
from ..storage import read_json, write_json
from ..stepper_status import raw_sources_ready, read_jsonl_rows, wiki_ready
from ..tmux_runner import TmuxRunner
from ..ui_navigation import WORKFLOW_TABS
from ..url_policy import classify_url_for_student_wiki
from ..data_root import resolve_data_root

from ..wiki.self_improving import read_confidence_gaps

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ACTIVE_EMBEDDING_JOB_STATUSES = {"queued", "running", "starting", "initializing"}


def data_root() -> Path:
    return resolve_data_root(PROJECT_ROOT)


def app_state_path() -> Path:
    return data_root() / "app_state.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "items"):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    return value


def read_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_jsonl_tail(path: Path, limit: int = 200) -> list[dict[str, Any]]:
    rows = read_jsonl_rows(path)
    return rows[-limit:] if limit > 0 else rows


def site_root(site_id: str) -> Path:
    safe = site_id.strip().strip("/")
    if not safe or ".." in safe or "/" in safe:
        raise HTTPException(status_code=400, detail="invalid site_id")
    return data_root() / "sites" / safe


def run_root(site_id: str, run_id: str) -> Path:
    safe = run_id.strip().strip("/")
    if not safe or ".." in safe or "/" in safe:
        raise HTTPException(status_code=400, detail="invalid run_id")
    return site_root(site_id) / safe


def reports_dir(site_id: str) -> Path:
    return site_root(site_id) / "wiki" / "reports"


def artifact_repo() -> SiteArtifactRepository:
    return SiteArtifactRepository(data_root())


def status_model() -> SiteStatusReadModel:
    return SiteStatusReadModel(data_root())


def state_repo() -> AppStateRepository:
    return AppStateRepository(app_state_path(), defaults={**APP_STATE_DEFAULTS})


def metrics_repo() -> AgentRunMetricsRepository:
    return AgentRunMetricsRepository(data_root())


def mcp_runner() -> TmuxRunner:
    return TmuxRunner()


def list_sites_payload() -> dict[str, Any]:
    sites_root = data_root() / "sites"
    sites = []
    if sites_root.exists():
        for path in sorted(sites_root.iterdir(), key=lambda item: item.name):
            if not path.is_dir():
                continue
            sites.append(
                {
                    "id": path.name,
                    "root": str(path),
                    "has_wiki": (path / "wiki").exists(),
                    "has_sources": (path / "raw_sources" / "registry.jsonl").exists(),
                    "run_count": len([item for item in path.iterdir() if item.is_dir() and item.name != "meta"]),
                }
            )
    return {"data_root": str(data_root()), "sites": sites, "generated_at": utc_now()}


def _counter_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    if hasattr(value, "items"):
        return {str(key): item for key, item in value.items()}
    return {}


def compact_raw_sources(raw_status: dict[str, Any]) -> dict[str, Any]:
    """Drop registry rows from API payloads; Sources tab loads rows on demand."""
    return {
        "registry_exists": raw_status.get("registry_exists"),
        "ready_count": raw_status.get("ready_count"),
        "by_kind": _counter_dict(raw_status.get("by_kind")),
        "by_status": _counter_dict(raw_status.get("by_status")),
        "by_change": _counter_dict(raw_status.get("by_change")),
        "by_quality_action": _counter_dict(raw_status.get("by_quality_action")),
        "latest_report_path": str(raw_status.get("latest_report_path") or ""),
    }


def compact_wiki_status(wiki_status: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_status": wiki_status.get("job_status"),
        "runtime": wiki_status.get("runtime"),
        "tmux_session": wiki_status.get("tmux_session"),
        "last_progress": wiki_status.get("last_progress"),
        "pages_created": wiki_status.get("pages_created"),
        "pages_updated": wiki_status.get("pages_updated"),
        "integrated_sources": wiki_status.get("integrated_sources"),
        "source_count": wiki_status.get("source_count"),
        "pending_source_count": wiki_status.get("pending_source_count"),
        "changed_source_count": wiki_status.get("changed_source_count"),
        "review_queue_count": wiki_status.get("review_queue_count"),
    }


def compact_embeddings(index_status: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_index_count": index_status.get("raw_index_count"),
        "wiki_index_count": index_status.get("wiki_index_count"),
        "last_build_time": index_status.get("last_build_time"),
        "reranker_ready": index_status.get("reranker_ready"),
        "index_health": index_status.get("index_health"),
        "changed_document_count": index_status.get("changed_document_count"),
        "freshness": index_status.get("freshness"),
        "auto_rebuild_enabled": index_status.get("auto_rebuild_enabled"),
        "auto_rebuild_reason": index_status.get("auto_rebuild_reason"),
        "job_state": index_status.get("job_state"),
    }


def compact_mcp_status(mcp_status: dict[str, Any]) -> dict[str, Any]:
    return {
        "server_available": mcp_status.get("server_available"),
        "index_health": mcp_status.get("index_health"),
        "server_command": mcp_status.get("server_command"),
        "session_name": mcp_status.get("session_name"),
        "running": mcp_status.get("running"),
        "last_start_status": mcp_status.get("last_start_status"),
        "last_error": mcp_status.get("last_error"),
        "updated_at": mcp_status.get("updated_at"),
    }


def site_overview_payload(site_id: str, *, compact: bool = True) -> dict[str, Any]:
    root = site_root(site_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="site not found")
    statuses = status_model()
    raw_status = statuses.load_raw_source_status(site_id)
    wiki_status = statuses.load_wiki_status(site_id)
    index_status = statuses.load_index_status(site_id)
    index_status.update(
        maybe_auto_queue_embedding_job(
            site_id,
            root,
            raw_status=raw_status,
            wiki_status=wiki_status,
            index_status=index_status,
        )
    )
    mcp_status = statuses.load_mcp_status(site_id)
    mcp_status.update(mcp_runtime_status(root, site_id, mcp_status))
    agent = wiki_agent_payload(site_id, compact=compact)
    if compact:
        raw_status = compact_raw_sources(raw_status)
        wiki_status = compact_wiki_status(wiki_status)
        index_status = compact_embeddings(index_status)
        mcp_status = compact_mcp_status(mcp_status)
    return {
        "site_id": site_id,
        "site_root": str(root),
        "raw_sources": raw_status,
        "wiki": wiki_status,
        "embeddings": index_status,
        "mcp": mcp_status,
        "agent": agent,
        "generated_at": utc_now(),
    }


def mcp_server_state_path(root: Path) -> Path:
    return root / "indexes" / "mcp-server-latest.json"


def mcp_session_name(site_id: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "-" for ch in site_id.lower()).strip("-")
    return f"llm-wiki-mcp-{normalized or 'site'}"


def empty_mcp_server_state(site_id: str) -> dict[str, Any]:
    return {
        "site_id": site_id,
        "session_name": mcp_session_name(site_id),
        "status": "idle",
        "running": False,
        "server_command": "",
        "started_at": "",
        "updated_at": "",
        "last_error": "",
    }


def load_mcp_server_state(root: Path, site_id: str) -> dict[str, Any]:
    payload = read_json(mcp_server_state_path(root), {})
    state = empty_mcp_server_state(site_id)
    if isinstance(payload, dict):
        state.update(payload)
    state["site_id"] = site_id
    state["session_name"] = mcp_session_name(site_id)
    return state


def write_mcp_server_state(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    state = {**state, "updated_at": utc_now()}
    write_json(mcp_server_state_path(root), state)
    return state


def mcp_runtime_status(root: Path, site_id: str, mcp_status: dict[str, Any]) -> dict[str, Any]:
    state = load_mcp_server_state(root, site_id)
    runner = mcp_runner()
    running = runner.session_exists(state["session_name"]) if runner.available() else False
    return {
        "session_name": state["session_name"],
        "running": running,
        "last_start_status": state.get("status") or "idle",
        "last_error": state.get("last_error") or "",
        "updated_at": state.get("updated_at") or "",
        "server_command": mcp_status.get("server_command") or state.get("server_command") or "",
    }


def start_mcp_server_for_site(root: Path, site_id: str, mcp_status: dict[str, Any], *, runner: TmuxRunner | None = None) -> dict[str, Any]:
    command = str(mcp_status.get("server_command") or "").strip()
    state = load_mcp_server_state(root, site_id)
    tmux = runner or mcp_runner()
    session = state["session_name"]
    if not command:
        state = write_mcp_server_state(
            root,
            {
                **state,
                "status": "blocked",
                "running": False,
                "server_command": "",
                "last_error": "mcp_server_command_unavailable",
            },
        )
        return {"status": "blocked", "mcp": state}
    if not tmux.available():
        state = write_mcp_server_state(
            root,
            {
                **state,
                "status": "failed",
                "running": False,
                "server_command": command,
                "last_error": "tmux_not_available",
            },
        )
        return {"status": "failed", "mcp": state}
    if tmux.session_exists(session):
        state = write_mcp_server_state(
            root,
            {
                **state,
                "status": "running",
                "running": True,
                "server_command": command,
                "last_error": "",
            },
        )
        return {"status": "already_running", "mcp": state}
    result = tmux.start(session, command, str(PROJECT_ROOT))
    if not result.get("ok"):
        state = write_mcp_server_state(
            root,
            {
                **state,
                "status": "failed",
                "running": False,
                "server_command": command,
                "last_error": str(result.get("error") or "failed_to_start_mcp_server"),
            },
        )
        return {"status": "failed", "mcp": state}
    state = write_mcp_server_state(
        root,
        {
            **state,
            "status": "running",
            "running": True,
            "server_command": command,
            "started_at": utc_now(),
            "last_error": "",
        },
    )
    return {"status": "started", "mcp": state}


def embedding_job_state_path(root: Path) -> Path:
    return root / "indexes" / "embedding-job-latest.json"


def embedding_reports_dir(root: Path) -> Path:
    return root / "indexes" / "reports"


def embedding_lock_path(root: Path) -> Path:
    return root / "indexes" / ".embedding-job.lock"


def timestamp_slug() -> str:
    return utc_now().replace("+00:00", "Z").replace(":", "").replace("-", "").replace(".", "")


def empty_embedding_job_state(site_id: str) -> dict[str, Any]:
    return {
        "site_id": site_id,
        "status": "idle",
        "trigger": "",
        "started_at": "",
        "updated_at": "",
        "completed_at": "",
        "changed_document_count": 0,
        "report_path": "",
        "log_path": "",
        "last_error": "",
    }


def load_embedding_job_state(root: Path, site_id: str) -> dict[str, Any]:
    payload = read_json(embedding_job_state_path(root), {})
    if not isinstance(payload, dict) or not payload:
        return empty_embedding_job_state(site_id)
    state = empty_embedding_job_state(site_id)
    state.update(payload)
    state["site_id"] = site_id
    return state


def write_embedding_job_state(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    state = {**state, "updated_at": utc_now()}
    write_json(embedding_job_state_path(root), state)
    return state


def report_path_for_embedding_job(root: Path, trigger: str, status: str) -> Path:
    return embedding_reports_dir(root) / f"embedding-{trigger}-{status}-{timestamp_slug()}.json"


def embedding_enabled() -> bool:
    state = state_repo().load()
    return bool(state.get("embedding_enabled", True))


def embedding_prerequisites_ready(raw_status: dict[str, Any], wiki_status: dict[str, Any]) -> bool:
    return raw_sources_ready(raw_status) and wiki_ready(wiki_status)


def start_embedding_job_state(
    root: Path,
    site_id: str,
    *,
    trigger: str,
    changed_document_count: int,
    status: str = "queued",
) -> dict[str, Any]:
    now = utc_now()
    run_id = os.getenv("WIKI_AGENT_RUN_ID") or os.getenv("RALPH_AGENT_RUN_ID") or f"embedding-{trigger}-{timestamp_slug()}"
    report_path = report_path_for_embedding_job(root, trigger, status)
    log_path = embedding_reports_dir(root) / f"embedding-{trigger}-{timestamp_slug()}.log"
    state = {
        "site_id": site_id,
        "run_id": run_id,
        "status": status,
        "trigger": trigger,
        "started_at": now if status != "queued" else "",
        "updated_at": now,
        "completed_at": "",
        "changed_document_count": int(changed_document_count),
        "report_path": str(report_path),
        "log_path": str(log_path),
        "last_error": "",
    }
    return write_embedding_job_state(root, state)


def coalesce_embedding_job(root: Path, state: dict[str, Any], *, trigger: str) -> dict[str, Any]:
    if trigger == "manual":
        state = {**state, "trigger": "manual", "operator_requested": True}
        return write_embedding_job_state(root, state)
    return state


def skip_embedding_job(root: Path, site_id: str, *, trigger: str, changed_document_count: int) -> dict[str, Any]:
    state = start_embedding_job_state(root, site_id, trigger=trigger, changed_document_count=changed_document_count, status="skipped")
    report = {
        "site_id": site_id,
        "status": "skipped",
        "trigger": trigger,
        "changed_document_count": int(changed_document_count),
        "message": "Embedding rebuild skipped: no changed documents required indexing.",
        "generated_at": utc_now(),
    }
    report_path = Path(state["report_path"])
    write_json(report_path, report)
    state = {**state, "completed_at": utc_now(), "report_path": str(report_path)}
    return write_embedding_job_state(root, state)


def try_acquire_embedding_lock(root: Path) -> int | None:
    lock = embedding_lock_path(root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    os.write(fd, str(os.getpid()).encode("ascii"))
    return fd


def release_embedding_lock(root: Path, fd: int | None) -> None:
    if fd is not None:
        os.close(fd)
    try:
        embedding_lock_path(root).unlink()
    except FileNotFoundError:
        pass


def run_embedding_job(
    root: Path,
    site_id: str,
    *,
    trigger: str,
    build_index=None,
) -> dict[str, Any]:
    fd = try_acquire_embedding_lock(root)
    if fd is None:
        state = load_embedding_job_state(root, site_id)
        return coalesce_embedding_job(root, state, trigger=trigger)
    state = load_embedding_job_state(root, site_id)
    if state.get("status") not in ACTIVE_EMBEDDING_JOB_STATUSES:
        state = start_embedding_job_state(
            root,
            site_id,
            trigger=trigger,
            changed_document_count=int(state.get("changed_document_count") or 0),
            status="running",
        )
    else:
        state = write_embedding_job_state(root, {**state, "status": "running", "started_at": state.get("started_at") or utc_now()})
    log_path = Path(state["log_path"])
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(f"Embedding rebuild started for {site_id} via {trigger} at {utc_now()}\n", encoding="utf-8")
        if build_index is None:
            from ..llm_wiki_index import build_llm_wiki_index

            build_index = build_llm_wiki_index
        report = build_index(root)
    except Exception as exc:
        error = str(exc)
        report_path = Path(state["report_path"])
        write_json(
            report_path,
            {
                "site_id": site_id,
                "status": "failed",
                "trigger": trigger,
                "changed_document_count": int(state.get("changed_document_count") or 0),
                "last_error": error,
                "generated_at": utc_now(),
            },
        )
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"Embedding rebuild failed: {error}\n")
        return write_embedding_job_state(
            root,
            {
                **state,
                "status": "failed",
                "completed_at": utc_now(),
                "report_path": str(report_path),
                "log_path": str(log_path),
                "last_error": error,
            },
        )
    else:
        _record_embedding_metric_event(root, site_id, state=state, report=report)
        report_path = Path(str(report.get("report_path") or state["report_path"]))
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"Embedding rebuild completed at {utc_now()}\n")
        return write_embedding_job_state(
            root,
            {
                **state,
                "status": "complete",
                "completed_at": utc_now(),
                "changed_document_count": int(report.get("changed_document_count") or state.get("changed_document_count") or 0),
                "report_path": str(report_path),
                "log_path": str(log_path),
                "last_error": "",
            },
        )
    finally:
        release_embedding_lock(root, fd)


def _record_embedding_metric_event(root: Path, site_id: str, *, state: dict[str, Any], report: dict[str, Any]) -> None:
    run_id = str(state.get("run_id") or os.getenv("WIKI_AGENT_RUN_ID") or os.getenv("RALPH_AGENT_RUN_ID") or "").strip()
    if not run_id:
        return
    raw_count = int(report.get("raw_index_count") or report.get("raw_count") or report.get("raw_documents") or 0)
    wiki_count = int(report.get("wiki_index_count") or report.get("wiki_count") or report.get("wiki_documents") or 0)
    skipped_count = int(report.get("skipped_document_count") or 0)
    changed_count = int(report.get("changed_document_count") or state.get("changed_document_count") or 0)
    embedding = report.get("embedding") if isinstance(report.get("embedding"), dict) else {}
    metrics = metrics_repo()
    try:
        metrics.append_event(
            build_embedding_metric_event(
                run_id=run_id,
                site_id=site_id,
                timestamp=str(report.get("built_at") or report.get("last_build_time") or utc_now()),
                stage="embed",
                operation="build_llm_wiki_index",
                provider=str(embedding.get("provider") or "unknown"),
                model=str(embedding.get("model") or "unknown"),
                input_tokens=None,
                document_count=raw_count + wiki_count,
                chunk_count=raw_count + wiki_count,
                vector_count=raw_count + wiki_count,
                reused_vector_count=skipped_count,
                skipped_chunk_count=skipped_count,
                failed_chunk_count=0,
                duration_ms=None,
                cost_usd=None,
                cost_source="unknown",
                raw_provider_usage={
                    "changed_document_count": changed_count,
                    "raw_index_count": raw_count,
                    "wiki_index_count": wiki_count,
                    "vector_dimensions": embedding.get("vector_dimensions"),
                },
            )
        )
        metrics.rebuild_run_summary(site_id, run_id, status="complete", trigger=str(state.get("trigger") or "embedding"), agent_mode="webapp")
    except Exception:
        return


def schedule_embedding_job(root: Path, site_id: str, *, trigger: str) -> None:
    timer = threading.Timer(0.1, run_embedding_job, args=(root, site_id), kwargs={"trigger": trigger})
    timer.daemon = True
    timer.start()


def trigger_embedding_rebuild(
    site_id: str,
    root: Path,
    *,
    trigger: str,
    changed_document_count: int,
    force: bool,
    launch: bool,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    state = load_embedding_job_state(root, site_id)
    if str(state.get("status") or "").lower() in ACTIVE_EMBEDDING_JOB_STATUSES:
        state = coalesce_embedding_job(root, state, trigger=trigger)
        return {"status": "already_running", "job_state": state}
    if not force and int(changed_document_count) <= 0:
        state = skip_embedding_job(root, site_id, trigger=trigger, changed_document_count=0)
        return {"status": "skipped", "job_state": state}
    state = start_embedding_job_state(root, site_id, trigger=trigger, changed_document_count=changed_document_count)
    if launch:
        if background_tasks is not None:
            background_tasks.add_task(run_embedding_job, root, site_id, trigger=trigger)
        else:
            schedule_embedding_job(root, site_id, trigger=trigger)
    return {"status": "queued", "job_state": state}


def maybe_auto_queue_embedding_job(
    site_id: str,
    root: Path,
    *,
    raw_status: dict[str, Any],
    wiki_status: dict[str, Any],
    index_status: dict[str, Any],
) -> dict[str, Any]:
    enabled = embedding_enabled()
    state = load_embedding_job_state(root, site_id)
    changed = int(index_status.get("changed_document_count") or 0)
    prerequisites_ready = embedding_prerequisites_ready(raw_status, wiki_status)
    freshness = "stale" if changed > 0 else "current"
    reason = "ready"
    if not enabled:
        reason = "embedding_disabled"
    elif not prerequisites_ready:
        reason = "prerequisites_unhealthy"
    elif str(state.get("status") or "").lower() in ACTIVE_EMBEDDING_JOB_STATUSES:
        reason = "already_running"
    elif changed > 0:
        result = trigger_embedding_rebuild(
            site_id,
            root,
            trigger="auto",
            changed_document_count=changed,
            force=False,
            launch=True,
        )
        state = result["job_state"]
        reason = result["status"]
    return {
        "freshness": freshness,
        "auto_rebuild_enabled": enabled and prerequisites_ready,
        "auto_rebuild_reason": reason,
        "job_state": state,
    }


def list_runs_payload(site_id: str) -> dict[str, Any]:
    root = site_root(site_id)
    runs = []
    if root.exists():
        for path in sorted(root.iterdir(), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True):
            if not path.is_dir() or path.name == "meta":
                continue
            status = read_run_status(path)
            runs.append(
                {
                    "run_id": path.name,
                    "path": str(path),
                    "mtime": path.stat().st_mtime,
                    "status": status,
                    "event_count": len(read_run_events(path)),
                    "page_count": len(read_page_states(path)),
                }
            )
    return {"site_id": site_id, "runs": runs, "generated_at": utc_now()}


def metrics_runs_payload(site_id: str, *, limit: int = 50) -> dict[str, Any]:
    root = site_root(site_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="site not found")
    summaries = metrics_repo().list_run_summaries(site_id)
    return {
        "site_id": site_id,
        "runs": summaries[: max(1, int(limit))],
        "generated_at": utc_now(),
    }


def metrics_run_payload(site_id: str, run_id: str) -> dict[str, Any]:
    root = site_root(site_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="site not found")
    summary = metrics_repo().read_run_summary(site_id, run_id)
    if not summary:
        raise HTTPException(status_code=404, detail="metrics run not found")
    return {"site_id": site_id, "run_id": run_id, "run": summary, "generated_at": utc_now()}


_scrape_runner: ScrapeRunner | None = None
_scrape_runner_lock = threading.Lock()


def scrape_runner() -> ScrapeRunner:
    global _scrape_runner
    with _scrape_runner_lock:
        if _scrape_runner is None:
            redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:0/0")
            _scrape_runner = ScrapeRunner(RunStateStore(redis_url=redis_url), data_root())
        return _scrape_runner


def _url_selection_guidance() -> str:
    path = PROJECT_ROOT / "prompts" / "pi_url_selection_prompt.md"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    marker = "<URLs>"
    if marker in text:
        return text.split(marker)[0].strip()
    return text.strip()


def start_scrape_payload(
    site_id: str,
    *,
    concurrency: int = 4,
    prefer_approved: bool = True,
    browser_mode: str = "none",
) -> dict[str, Any]:
    root = site_root(site_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="site not found")
    urls = urls_for_site_scrape(root, prefer_approved=prefer_approved)
    if not urls:
        raise HTTPException(
            status_code=400,
            detail="No policy-eligible URLs to scrape. Discover URLs and update approved_urls.md first.",
        )
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    scrape_runner().start(
        site_id,
        run_id,
        urls,
        concurrency=max(1, min(int(concurrency or 4), 16)),
        browser_mode=browser_mode or "none",
    )
    repo = state_repo()
    state = dict(repo.load())
    last_run_by_site = dict(state.get("last_run_by_site") or {})
    last_run_by_site[site_id] = run_id
    state.update({"last_run_by_site": last_run_by_site, "last_run_id": run_id, "last_site_id": site_id})
    repo.save(state)
    return {
        "site_id": site_id,
        "run_id": run_id,
        "url_count": len(urls),
        "prefer_approved": prefer_approved,
        "started_at": utc_now(),
    }


def confidence_gaps_payload(site_id: str, *, limit: int = 50) -> dict[str, Any]:
    root = site_root(site_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="site not found")
    gaps = read_confidence_gaps(root, limit=limit)
    return {"site_id": site_id, "gaps": gaps, "count": len(gaps), "generated_at": utc_now()}


def discover_site_payload(site_url: str, *, timeout: int = 15) -> dict[str, Any]:
    normalized = normalize_site_url(site_url)
    site_id = urlparse(normalized).netloc
    if not site_id:
        raise HTTPException(status_code=400, detail="invalid site_url")
    result = discover_site_urls(normalized, timeout=timeout)
    rows = [item.to_dict() for item in result.urls]
    root = site_root(site_id)
    root.mkdir(parents=True, exist_ok=True)
    artifact_repo().save_discovered_rows(site_id, rows)
    selected_count = sum(1 for item in result.urls if item.selected and not item.excluded_reason)
    rejected_count = len(result.urls) - selected_count
    excluded_by_policy = sum(1 for item in result.urls if not item.selected and item.excluded_reason)
    summary = {
        "site_id": site_id,
        "site_url": normalized,
        "discovered_total": len(result.urls),
        "eligible_total": selected_count,
        "rejected_total": rejected_count,
        "excluded_by_policy": excluded_by_policy,
        "sitemap_sources": result.sitemap_sources,
        "notes": result.notes,
        "generated_at": utc_now(),
    }
    write_json(root / "discovery_summary.json", summary)
    repo = state_repo()
    state = dict(repo.load())
    workspaces = [item for item in state.get("workspaces", []) if isinstance(item, dict) and item.get("id") != site_id]
    workspaces.append({"id": site_id, "name": site_id, "url": normalized})
    history = [item for item in state.get("site_history", []) if item != normalized]
    state.update(
        {
            "active_workspace_id": site_id,
            "last_site_id": site_id,
            "last_site_url": normalized,
            "workspaces": sorted(workspaces, key=lambda item: str(item.get("id") or "")),
            "site_history": [normalized, *history][:20],
        }
    )
    repo.save(state)
    return {**summary, "rows_written": len(rows), "app_state": repo.load()}


def metrics_rollups_payload(
    site_id: str,
    *,
    windows: str = ",".join(STANDARD_WINDOWS),
    as_of: str | None = None,
    include_all_time: bool = True,
) -> dict[str, Any]:
    root = site_root(site_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="site not found")
    parsed_windows = tuple(item.strip() for item in windows.split(",") if item.strip() and item.strip() != "all_time")
    if not parsed_windows:
        parsed_windows = STANDARD_WINDOWS
    rollups = metrics_repo().build_rollups(site_id, windows=parsed_windows, as_of=as_of, include_all_time=include_all_time or "all_time" in windows.split(","))
    return {"site_id": site_id, "rollups": rollups, "generated_at": utc_now()}


def run_payload(site_id: str, run_id: str, event_limit: int = 200) -> dict[str, Any]:
    root = run_root(site_id, run_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "site_id": site_id,
        "run_id": run_id,
        "status": read_run_status(root),
        "events": read_run_events(root, limit=event_limit),
        "pages": read_page_states(root),
        "generated_at": utc_now(),
    }


def sources_payload(site_id: str, limit: int = 500, offset: int = 0) -> dict[str, Any]:
    rows = artifact_repo().load_raw_source_rows(site_id)
    total = len(rows)
    return {
        "site_id": site_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "rows": rows[offset : offset + limit],
        "generated_at": utc_now(),
    }


APPROVED_URLS_HEADER = "# Approved URLs\n\n<!-- scrape-planner:approved-urls:v1 -->\n"
URL_RE = re.compile(r"https?://[^\s)\]}>\"']+")


def approved_urls_path(site_id: str) -> Path:
    return site_root(site_id) / "approved_urls.md"


def parse_approved_urls_markdown(markdown: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in URL_RE.finditer(markdown or ""):
        url = match.group(0).rstrip(".,;")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


SCHOOL_PATH_ROOTS = {"cox", "dedman", "dedmanlaw", "lyle", "meadows", "simmons", "perkins"}


def _url_group_key(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return "/"
    if parts[0].lower() in SCHOOL_PATH_ROOTS:
        return f"/{parts[0]}"
    if len(parts) == 1:
        return f"/{parts[0]}"
    return f"/{parts[0]}/{parts[1]}"


def _url_groups(urls: list[str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = {}
    for url in urls:
        grouped.setdefault(_url_group_key(url), []).append(url)
    return [
        {"subpath": subpath, "count": len(items), "examples": items[:3]}
        for subpath, items in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def _term_matches_url_or_group(url: str, terms: list[str]) -> bool:
    haystack = f"{url}\n{_url_group_key(url)}".lower().replace("-", " ")
    compact = haystack.replace(" ", "-")
    for term in terms:
        needle = str(term or "").strip().lower().replace("/", " ").replace("-", " ")
        if not needle:
            continue
        if needle in haystack or needle.replace(" ", "-") in compact:
            return True
    return False


def _discovery_url_pool(site_id: str, *, extra_exclude_terms: list[str] | None = None) -> dict[str, Any]:
    rows = read_json(site_root(site_id) / "discovered_urls.json", [])
    exclude_terms = extra_exclude_terms or []
    eligible_urls: list[str] = []
    rejected = 0
    total = 0
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        total += 1
        url = str(row.get("url") or "")
        title = str(row.get("title") or "")
        if row.get("excluded_reason") == "operator_rejected_area" or _term_matches_url_or_group(url, exclude_terms):
            rejected += 1
            continue
        decision = classify_url_for_student_wiki(url, title=title, lastmod=row.get("lastmod"))
        if decision.selected:
            eligible_urls.append(url)
        else:
            rejected += 1
    return {
        "discovered_total": total,
        "eligible_total": len(eligible_urls),
        "rejected_total": rejected,
        "groups": _url_groups(eligible_urls),
    }


def approved_urls_payload(site_id: str) -> dict[str, Any]:
    path = approved_urls_path(site_id)
    markdown = path.read_text(encoding="utf-8") if path.exists() else APPROVED_URLS_HEADER + "\n"
    urls = parse_approved_urls_markdown(markdown)
    pool = _discovery_url_pool(site_id)
    return {"site_id": site_id, "path": str(path), "markdown": markdown, "urls": urls, "groups": _url_groups(urls), "available_groups": pool["groups"], "discovery": {"discovered_total": pool["discovered_total"], "eligible_total": pool["eligible_total"], "rejected_total": pool["rejected_total"]}, "count": len(urls), "generated_at": utc_now()}


def write_approved_urls_payload(site_id: str, markdown: str) -> dict[str, Any]:
    path = approved_urls_path(site_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = markdown if markdown.strip() else APPROVED_URLS_HEADER + "\n"
    if "scrape-planner:approved-urls:v1" not in content:
        content = APPROVED_URLS_HEADER + "\n" + content.strip() + "\n"
    path.write_text(content, encoding="utf-8")
    return approved_urls_payload(site_id)


def apply_operator_discovery_exclusions(site_id: str, terms: list[str]) -> int:
    clean_terms = [str(term or "").strip() for term in terms if str(term or "").strip()]
    if not clean_terms:
        return 0
    path = site_root(site_id) / "discovered_urls.json"
    rows = read_json(path, [])
    if not isinstance(rows, list):
        return 0
    changed = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "")
        if not url or not _term_matches_url_or_group(url, clean_terms):
            continue
        if row.get("excluded_reason") != "operator_rejected_area" or row.get("selected") is not False:
            row["selected"] = False
            row["excluded_reason"] = "operator_rejected_area"
            changed += 1
    if changed:
        write_json(path, rows)
    return changed


def commit_approved_urls_payload(site_id: str, request: ApprovedUrlsCommitRequest) -> dict[str, Any]:
    excluded_count = apply_operator_discovery_exclusions(site_id, request.remove_terms)
    payload = write_approved_urls_payload(site_id, request.markdown)
    return {**payload, "operator_excluded_count": excluded_count}


def approval_chat_log_path(site_id: str) -> Path:
    return site_root(site_id) / "approved_urls_chat.jsonl"


def _append_approval_chat_event(site_id: str, event: dict[str, Any]) -> None:
    path = approval_chat_log_path(site_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {**event, "site_id": site_id, "created_at": utc_now()}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(to_jsonable(row), sort_keys=True) + "\n")


def _approved_url_lines(markdown: str) -> dict[str, str]:
    lines: dict[str, str] = {}
    for line in (markdown or "").splitlines():
        match = URL_RE.search(line)
        if not match:
            continue
        url = match.group(0).rstrip(".,;")
        lines.setdefault(url, line.strip() or f"- [x] {url}")
    return lines


def _render_approved_urls_markdown(lines_by_url: dict[str, str], *, note: str = "") -> str:
    lines = [APPROVED_URLS_HEADER.rstrip(), ""]
    if note:
        lines.extend([f"> {note}", ""])
    lines.extend(["## Approved for next scrape", ""])
    for url, line in sorted(lines_by_url.items()):
        rendered = line if url in line else f"- [x] {url}"
        if not rendered.lstrip().startswith("-"):
            rendered = f"- [x] {rendered}"
        lines.append(rendered)
    return "\n".join(lines).rstrip() + "\n"


def _message_urls(message: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in URL_RE.finditer(message or ""):
        url = match.group(0).rstrip(".,;")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _removal_terms(message: str) -> list[str]:
    stop = {"remove", "delete", "exclude", "filter", "demove", "noise", "noisy", "bad", "reject", "rejected", "approved", "approve", "source", "sources", "url", "urls", "page", "pages", "anything", "with", "from", "file", "scrape", "please"}
    terms: list[str] = []
    for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", message.lower()):
        if token not in stop and token not in terms:
            terms.append(token)
    return terms


def _candidate_rows_for_instruction(site_id: str, instruction: str, *, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    root = site_root(site_id)
    raw_rows = read_json(root / "discovered_urls.json", [])
    row_list = [row for row in raw_rows if isinstance(row, dict)] if isinstance(raw_rows, list) else []
    terms = _message_terms(instruction)
    explicit_urls = _message_urls(instruction)
    matched_groups: set[str] = {_url_group_key(url) for url in explicit_urls}
    rejected: list[dict[str, Any]] = []

    for row in row_list:
        url = str(row.get("url") or "")
        title = str(row.get("title") or "")
        haystack = f"{url}\n{title}".lower()
        if url and (not terms or any(term in haystack for term in terms)):
            matched_groups.add(_url_group_key(url))

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    discovered_urls = {str(row.get("url") or "") for row in row_list}

    for url in explicit_urls:
        if url in discovered_urls:
            continue
        decision = classify_url_for_student_wiki(url)
        if decision.selected:
            candidates.append({"url": url, "title": "", "reason": "explicit_url"})
            seen.add(url)
        else:
            rejected.append({"url": url, "reason": decision.reason})

    for row in row_list:
        if len(candidates) >= limit:
            break
        url = str(row.get("url") or "")
        if not url or url in seen:
            continue
        if row.get("excluded_reason") == "operator_rejected_area":
            continue
        if matched_groups and _url_group_key(url) not in matched_groups:
            continue
        title = str(row.get("title") or "")
        decision = classify_url_for_student_wiki(url, title=title, lastmod=row.get("lastmod"))
        if decision.selected:
            candidates.append({"url": url, "title": title, "reason": f"subpath:{_url_group_key(url)}"})
            seen.add(url)
        else:
            rejected.append({"url": url, "reason": decision.reason})
    return candidates, rejected, terms


def _positive_instruction_text(message: str) -> str:
    return re.split(r"\b(?:exclude|reject|do not include|avoid|remove)\b", message, maxsplit=1, flags=re.IGNORECASE)[0]


def _message_terms(message: str) -> list[str]:
    message = _positive_instruction_text(message)
    aliases = {
        "registrar": ["registrar", "enrollment-services", "transcript", "records"],
        "calendar": ["academic-calendar", "final-exam", "calendar"],
        "catalog": ["course-catalog", "catalog", "course", "degree", "program"],
        "tuition": ["tuition", "bursar", "billing", "payment", "cost"],
        "aid": ["financial-aid", "financialaid", "scholarship"],
        "housing": ["housing", "dining", "student-life", "health", "counseling", "parking", "orientation", "accessibility"],
        "admission": ["admission", "apply", "application", "transfer", "visit"],
        "cox": ["cox"],
        "dedman": ["dedman", "deadman"],
        "deadman": ["dedman", "deadman"],
        "meadows": ["meadows"],
        "lyle": ["lyle"],
        "simmons": ["simmons"],
        "perkins": ["perkins"],
        "schools": ["cox", "dedman", "dedmanlaw", "meadows", "lyle", "simmons", "perkins"],
    }
    lowered = message.lower()
    terms: list[str] = []
    for key, values in aliases.items():
        if key in lowered or any(value in lowered for value in values):
            terms.extend(values)
    for token in re.findall(r"[a-z0-9][a-z0-9-]{3,}", lowered):
        if token not in {"approve", "approved", "source", "sources", "scrape", "pages", "urls", "student", "students"}:
            terms.append(token)
    deduped: list[str] = []
    for term in terms:
        if term not in deduped:
            deduped.append(term)
    return deduped


def _analysis_terms(message: str) -> list[str]:
    stop = {"how", "many", "count", "counts", "summary", "summarize", "show", "list", "top", "breakdown", "why", "explain", "could", "eligible", "available", "selected", "urls", "url", "select", "selected", "have", "we", "the", "for", "from", "and", "group", "groups"}
    terms: list[str] = []
    for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", message.lower()):
        if token not in stop and token not in terms:
            terms.append(token)
    return terms


def _approval_analysis(site_id: str, markdown: str, message: str) -> dict[str, Any]:
    rows = read_json(site_root(site_id) / "discovered_urls.json", [])
    selected_urls = set(parse_approved_urls_markdown(markdown))
    terms = _analysis_terms(message)
    eligible_urls: list[str] = []
    matched_eligible_urls: list[str] = []
    reject_reasons: Counter[str] = Counter()
    root_counts: Counter[str] = Counter()
    school_roots = {"cox", "dedman", "dedmanlaw", "law", "lyle", "meadows", "simmons", "perkins"}
    student_roots = {"admission", "enrollment-services", "studentaffairs", "student-life", "libraries", "bursar", "financialaid", "student-financial-services", "housing", "dining"}
    school_or_student = 0

    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "")
        title = str(row.get("title") or "")
        haystack = f"{url}\n{title}".lower()
        if row.get("excluded_reason") == "operator_rejected_area":
            reject_reasons["operator_rejected_area"] += 1
            continue
        decision = classify_url_for_student_wiki(url, title=title, lastmod=row.get("lastmod"))
        if decision.selected:
            eligible_urls.append(url)
            if not terms or any(term in haystack for term in terms):
                matched_eligible_urls.append(url)
            parts = [part.lower() for part in urlparse(url).path.split("/") if part]
            root = parts[0] if parts else "/"
            root_counts[root] += 1
            if root in school_roots or root in student_roots or any(marker in haystack for marker in ("/registrar", "/academic-calendar", "/tuition", "/financial-aid", "/scholarship", "/housing", "/dining", "/health", "/accessibility", "/orientation")):
                school_or_student += 1
        else:
            reject_reasons[decision.reason] += 1

    selected_groups = _url_groups(sorted(selected_urls))
    available_groups = _url_groups(eligible_urls)
    matched_groups = _url_groups(matched_eligible_urls) if terms else available_groups
    return {
        "discovered_total": len(rows) if isinstance(rows, list) else 0,
        "eligible_total": len(eligible_urls),
        "rejected_total": sum(reject_reasons.values()),
        "selected_total": len(selected_urls),
        "school_or_student_total": school_or_student,
        "top_roots": [{"root": root, "count": count} for root, count in root_counts.most_common(15)],
        "top_available_groups": available_groups[:15],
        "matched_terms": terms,
        "matched_eligible_total": len(matched_eligible_urls),
        "matched_groups": matched_groups[:15],
        "selected_groups": selected_groups[:15],
        "reject_reasons": [{"reason": reason, "count": count} for reason, count in reject_reasons.most_common()],
    }


def _analysis_message(analysis: dict[str, Any]) -> str:
    lines = [
        f"Discovered {analysis['discovered_total']} URLs.",
        f"Could select {analysis['eligible_total']} policy-eligible URLs.",
        f"Filtered {analysis['rejected_total']} noisy or stale URLs.",
        f"Currently approved {analysis['selected_total']} URLs.",
        f"School or student-service candidate count is {analysis['school_or_student_total']} URLs.",
    ]
    if analysis.get("matched_terms"):
        lines.append(f"For {', '.join(analysis['matched_terms'])}, matched {analysis['matched_eligible_total']} eligible URLs.")
    top = analysis.get("matched_groups") or analysis.get("top_available_groups") or []
    if top:
        lines.append("Top selectable subpaths:")
        lines.extend(f"{item['subpath']}: {item['count']}" for item in top[:8])
    reasons = analysis.get("reject_reasons") or []
    if reasons:
        lines.append("Top rejection reasons:")
        lines.extend(f"{item['reason']}: {item['count']}" for item in reasons[:5])
    return "\n".join(lines)


def _read_dotenv_key(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith(f"{key}="):
            continue
        return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _openrouter_api_key() -> str:
    state = state_repo().load()
    return (
        os.getenv("OPENROUTER_API_KEY", "").strip()
        or str(state.get("openrouter_api_key") or "").strip()
        or _read_dotenv_key(PROJECT_ROOT / ".env", "OPENROUTER_API_KEY")
        or _read_dotenv_key(PROJECT_ROOT.parent / "ultra-fast-rag" / ".env", "OPENROUTER_API_KEY")
    )


def _url_chat_model() -> str:
    state = state_repo().load()
    return str(state.get("url_reasoning_openrouter_model") or os.getenv("URL_REASONING_OPENROUTER_MODEL") or "deepseek/deepseek-v4-flash").strip()


def _extract_json_object(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        payload = json.loads(match.group(0)) if match else {}
    return payload if isinstance(payload, dict) else {}


def _llm_decide_url_chat(message: str, base_prompt: str, analysis: dict[str, Any]) -> dict[str, Any]:
    api_key = _openrouter_api_key()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for URL approval chat")
    compact = {
        "discovered_total": analysis.get("discovered_total"),
        "eligible_total": analysis.get("eligible_total"),
        "selected_total": analysis.get("selected_total"),
        "top_available_groups": analysis.get("top_available_groups", [])[:20],
        "selected_groups": analysis.get("selected_groups", [])[:20],
        "reject_reasons": analysis.get("reject_reasons", [])[:8],
    }
    guidance = base_prompt.strip() or _url_selection_guidance()
    prompt = (
        "You are a URL selection agent for a university scraping workflow. Return strict JSON only. "
        "Classify the operator message into one intent: analyze, approve, remove. "
        "Use approve only when the user asks to add/select/include/scrape URLs. "
        "Use remove when the user asks to remove/delete/exclude/filter noise. "
        "Otherwise analyze. Return keys intent, terms, response. Terms are path words or school names to match. "
        "Never invent counts. Use the supplied analysis facts.\n"
        f"Student URL policy guidance:\n{guidance}\n"
        f"Operator message: {message}\n"
        f"Facts: {json.dumps(compact, ensure_ascii=False)}"
    )
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": _url_chat_model(), "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": 1200},
        timeout=90,
    )
    resp.raise_for_status()
    content = str(resp.json()["choices"][0]["message"]["content"] or "")
    decision = _extract_json_object(content)
    intent = str(decision.get("intent") or "analyze").lower()
    if intent not in {"analyze", "approve", "remove"}:
        intent = "analyze"
    terms = decision.get("terms") if isinstance(decision.get("terms"), list) else []
    return {
        "provider": "openrouter",
        "model": _url_chat_model(),
        "status": "success",
        "intent": intent,
        "terms": [str(term).strip() for term in terms if str(term).strip()][:20],
        "response": str(decision.get("response") or "").strip(),
    }


def approval_chat_payload(site_id: str, request: ApprovedUrlsChatRequest) -> dict[str, Any]:
    message = request.message.strip()
    current = request.markdown if request.markdown is not None else approved_urls_payload(site_id)["markdown"]
    lines_by_url = _approved_url_lines(current)
    removed: list[dict[str, str]] = []
    added: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    terms: list[str] = []
    analysis: dict[str, Any] | None = _approval_analysis(site_id, current, message)
    try:
        llm = _llm_decide_url_chat(message, request.base_prompt, analysis)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"LLM URL agent failed: {str(exc)[:300]}") from exc
    intent = str(llm.get("intent") or "").lower()
    if intent not in {"analyze", "approve", "remove"}:
        raise HTTPException(status_code=502, detail=f"LLM URL agent returned invalid intent: {intent or 'missing'}")
    llm_terms = [str(term) for term in llm.get("terms", []) if str(term).strip()]
    effective_message = " ".join(llm_terms) if llm_terms else message

    if intent == "remove":
        urls = _message_urls(message)
        terms = llm_terms or ([] if urls else _removal_terms(message))
        for url, line in list(lines_by_url.items()):
            lowered = line.lower()
            matched_url = next((item for item in urls if item == url or item in line), "")
            matched_term = next((term for term in terms if term in lowered), "")
            if matched_url or matched_term:
                removed.append({"url": url, "reason": matched_url or matched_term})
                lines_by_url.pop(url, None)
        if removed:
            assistant_message = f"{'Removed' if request.autosave else 'Proposed removing'} {len(removed)} approved URL(s)."
        else:
            assistant_message = "I did not find matching approved URLs. Paste an exact URL or a distinctive path term."
    elif intent == "approve":
        instruction = "\n".join(part for part in [request.base_prompt.strip(), effective_message] if part)
        candidates, rejected_rows, terms = _candidate_rows_for_instruction(site_id, instruction, limit=request.limit)
        rejected = [{"url": str(item.get("url") or ""), "reason": str(item.get("reason") or "") } for item in rejected_rows]
        for item in candidates:
            url = item["url"]
            if url in lines_by_url:
                continue
            label = f" — {item['title']}" if item.get("title") else ""
            lines_by_url[url] = f"- [x] {url}{label}"
            added.append({"url": url, "reason": str(item.get("reason") or "selected")})
        verb = "Added" if request.autosave else "Proposed adding"
        assistant_message = f"{verb} {len(added)} approved URL(s). Rejected {len(rejected)} noisy URL(s)."
    else:
        assistant_message = str(llm.get("response") or "").strip() or _analysis_message(analysis)

    markdown = _render_approved_urls_markdown(lines_by_url, note="Managed by Approval chat. Edit by chatting or changing this file directly.")
    should_save = request.autosave and intent in {"remove", "approve"}
    saved = False
    if should_save:
        write_approved_urls_payload(site_id, markdown)
        saved = True
    event = {
        "message": message,
        "base_prompt": request.base_prompt,
        "autosave": request.autosave,
        "added": added,
        "removed": removed,
        "rejected": rejected[:100],
        "approved_count": len(lines_by_url),
        "analysis": analysis,
        "llm": llm,
        "intent": intent,
    }
    _append_approval_chat_event(site_id, event)
    pool = _discovery_url_pool(site_id, extra_exclude_terms=terms if intent == "remove" else [])
    added_urls = [item["url"] for item in added]
    removed_urls = [item["url"] for item in removed]
    rejected_urls = [item["url"] for item in rejected]
    return {
        "site_id": site_id,
        "assistant_message": assistant_message + (" Saved approved_urls.md." if saved else (" Review the proposed URL groups, then click Update approved_urls.md." if intent in {"remove", "approve"} else "")),
        "markdown": markdown,
        "urls": list(lines_by_url),
        "groups": _url_groups(list(lines_by_url)),
        "added_groups": _url_groups(added_urls),
        "removed_groups": _url_groups(removed_urls),
        "rejected_groups": _url_groups(rejected_urls),
        "available_groups": pool["groups"],
        "discovery": {"discovered_total": pool["discovered_total"], "eligible_total": pool["eligible_total"], "rejected_total": pool["rejected_total"]},
        "count": len(lines_by_url),
        "added": added,
        "removed": removed,
        "rejected": rejected,
        "terms": terms,
        "saved": saved,
        "analysis": analysis,
        "llm": llm,
        "intent": intent,
        "path": str(approved_urls_path(site_id)),
        "generated_at": utc_now(),
    }


_TMUX_CACHE: dict[str, tuple[float, bool]] = {}
_TMUX_CACHE_TTL_SECONDS = 3.0


def wiki_agent_payload(site_id: str, *, compact: bool = False) -> dict[str, Any]:
    directory = reports_dir(site_id)
    run_state = read_json_file(directory / "wiki-agent-run-latest.json", {})
    tasks = read_json_file(directory / "wiki-agent-tasks-latest.json", {})
    summary = ""
    summary_path = directory / "wiki-agent-summary-latest.md"
    if summary_path.exists() and not compact:
        try:
            summary = summary_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            summary = ""
    event_limit = 5 if compact else 200
    events = read_jsonl_tail(directory / "wiki-agent-events-latest.jsonl", event_limit)
    pane_log_path = directory / "wiki-agent-pane-latest.log"
    pane_tail = ""
    if pane_log_path.exists() and not compact:
        try:
            pane_tail = "\n".join(pane_log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-160:])
        except OSError:
            pane_tail = ""

    stale_running = False
    if run_state.get("status") == "running":
        session = str(run_state.get("tmux_session") or "")
        stale_running = bool(session) and not tmux_session_exists(session)

    payload: dict[str, Any] = {
        "run": run_state,
        "tasks": tasks if not compact else {"items": (tasks.get("items") or [])[:8], "completed": tasks.get("completed"), "total": tasks.get("total")},
        "summary": summary[:400] if compact and summary else summary,
        "events": events,
        "event_count": len(events),
        "pane_log_tail": pane_tail,
        "stale_running": stale_running,
        "generated_at": utc_now(),
    }
    if compact:
        payload.pop("pane_log_tail", None)
    return payload


def tmux_session_exists(session: str) -> bool:
    if not session:
        return False
    import subprocess
    import time

    now = time.monotonic()
    cached = _TMUX_CACHE.get(session)
    if cached and (now - cached[0]) < _TMUX_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        completed = subprocess.run(
            ["tmux", "has-session", "-t", session],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        alive = False
    else:
        alive = completed.returncode == 0
    _TMUX_CACHE[session] = (now, alive)
    return alive


def wiki_pages_payload(site_id: str, query: str = "", limit: int = 200) -> dict[str, Any]:
    pages_root = site_root(site_id) / "wiki" / "pages"
    rows: list[dict[str, Any]] = []
    needle = query.strip().lower()
    if pages_root.exists():
        for path in sorted(pages_root.rglob("*.md")):
            rel = path.relative_to(site_root(site_id) / "wiki")
            if needle and needle not in str(rel).lower():
                continue
            rows.append({"path": str(rel), "size": path.stat().st_size, "mtime": path.stat().st_mtime})
            if len(rows) >= limit:
                break
    return {"site_id": site_id, "query": query, "pages": rows, "generated_at": utc_now()}


def site_relative_text_payload(site_id: str, relative_path: str, limit_chars: int = 80_000) -> dict[str, Any]:
    clean_path = relative_path.strip().lstrip("/")
    if not clean_path or ".." in Path(clean_path).parts:
        raise HTTPException(status_code=400, detail="invalid path")
    root = site_root(site_id).resolve()
    target = (root / clean_path).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(status_code=400, detail="invalid path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"failed to read file: {exc}") from exc
    if limit_chars > 0:
        content = content[:limit_chars]
    return {
        "site_id": site_id,
        "path": clean_path,
        "content": content,
        "size": target.stat().st_size,
        "generated_at": utc_now(),
    }


def sse_event(event: str, payload: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(to_jsonable(payload), ensure_ascii=True)}\n\n"


async def site_event_stream(site_id: str, interval: float) -> AsyncIterator[str]:
    previous_digest = ""
    while True:
        try:
            payload = await asyncio.to_thread(site_overview_payload, site_id, compact=True)
            digest = json.dumps(to_jsonable(payload), sort_keys=True, default=str)
            if digest != previous_digest:
                previous_digest = digest
                yield sse_event("site", payload)
        except Exception as exc:  # keep stream alive for transient file writes
            yield sse_event("error", {"message": str(exc), "generated_at": utc_now()})
        await asyncio.sleep(interval)


class AppStateUpdate(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class DiscoverSiteRequest(BaseModel):
    site_url: str
    timeout: int = Field(default=15, ge=3, le=60)


class ApprovedUrlsUpdate(BaseModel):
    markdown: str = ""


class ApprovedUrlsCommitRequest(BaseModel):
    markdown: str = ""
    remove_terms: list[str] = Field(default_factory=list)


class ApprovedUrlsChatRequest(BaseModel):
    message: str = ""
    base_prompt: str = ""
    markdown: str | None = None
    limit: int = Field(default=5000, ge=1, le=30000)
    autosave: bool = True


class StartScrapeRequest(BaseModel):
    concurrency: int = Field(default=4, ge=1, le=16)
    prefer_approved: bool = True
    browser_mode: str = "none"


def create_app() -> FastAPI:
    app = FastAPI(title="Ultra Fast RAG Web API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("SCRAPE_PLANNER_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "data_root": str(data_root()), "generated_at": utc_now()}

    @app.get("/api/navigation")
    def navigation() -> dict[str, Any]:
        return {"tabs": WORKFLOW_TABS}

    @app.get("/api/app-state")
    def get_app_state() -> dict[str, Any]:
        return {"state": state_repo().load(), "path": str(app_state_path())}

    @app.put("/api/app-state")
    def put_app_state(update: AppStateUpdate) -> dict[str, Any]:
        repo = state_repo()
        current = dict(repo.load())
        current.update(update.payload)
        repo.save(current)
        return {"state": repo.load(), "path": str(app_state_path())}

    @app.post("/api/discover")
    def discover_site(request: DiscoverSiteRequest) -> dict[str, Any]:
        return to_jsonable(discover_site_payload(request.site_url, timeout=request.timeout))

    @app.get("/api/sites")
    def list_sites() -> dict[str, Any]:
        return to_jsonable(list_sites_payload())

    @app.get("/api/sites/{site_id}/overview")
    def site_overview(site_id: str) -> dict[str, Any]:
        return to_jsonable(site_overview_payload(site_id))

    @app.post("/api/sites/{site_id}/mcp/start")
    def start_mcp_server(site_id: str) -> dict[str, Any]:
        root = site_root(site_id)
        if not root.exists():
            raise HTTPException(status_code=404, detail="site not found")
        mcp_status = status_model().load_mcp_status(site_id)
        return to_jsonable(start_mcp_server_for_site(root, site_id, mcp_status))

    @app.post("/api/sites/{site_id}/embeddings/rebuild")
    def rebuild_embeddings(
        site_id: str,
        background_tasks: BackgroundTasks,
        force: bool = Query(True),
    ) -> dict[str, Any]:
        root = site_root(site_id)
        if not root.exists():
            raise HTTPException(status_code=404, detail="site not found")
        statuses = status_model()
        raw_status = statuses.load_raw_source_status(site_id)
        wiki_status = statuses.load_wiki_status(site_id)
        index_status = statuses.load_index_status(site_id)
        if not embedding_enabled():
            return {
                "status": "disabled",
                "reason": "embedding_disabled",
                "job_state": load_embedding_job_state(root, site_id),
            }
        if not embedding_prerequisites_ready(raw_status, wiki_status):
            return {
                "status": "blocked",
                "reason": "prerequisites_unhealthy",
                "job_state": load_embedding_job_state(root, site_id),
            }
        result = trigger_embedding_rebuild(
            site_id,
            root,
            trigger="manual",
            changed_document_count=int(index_status.get("changed_document_count") or 0),
            force=force,
            launch=True,
            background_tasks=background_tasks,
        )
        return to_jsonable(result)

    @app.get("/api/sites/{site_id}/sources")
    def site_sources(site_id: str, limit: int = Query(500, ge=1, le=5000), offset: int = Query(0, ge=0)) -> dict[str, Any]:
        return to_jsonable(sources_payload(site_id, limit=limit, offset=offset))

    @app.get("/api/sites/{site_id}/approved-urls")
    def get_approved_urls(site_id: str) -> dict[str, Any]:
        return to_jsonable(approved_urls_payload(site_id))

    @app.put("/api/sites/{site_id}/approved-urls")
    def put_approved_urls(site_id: str, update: ApprovedUrlsUpdate) -> dict[str, Any]:
        return to_jsonable(write_approved_urls_payload(site_id, update.markdown))

    @app.post("/api/sites/{site_id}/approved-urls/commit")
    def commit_approved_urls(site_id: str, request: ApprovedUrlsCommitRequest) -> dict[str, Any]:
        return to_jsonable(commit_approved_urls_payload(site_id, request))

    @app.post("/api/sites/{site_id}/approved-urls/chat")
    def chat_approved_urls(site_id: str, request: ApprovedUrlsChatRequest) -> dict[str, Any]:
        return to_jsonable(approval_chat_payload(site_id, request))

    @app.post("/api/sites/{site_id}/scrape")
    def start_site_scrape(site_id: str, request: StartScrapeRequest) -> dict[str, Any]:
        return to_jsonable(
            start_scrape_payload(
                site_id,
                concurrency=request.concurrency,
                prefer_approved=request.prefer_approved,
                browser_mode=request.browser_mode,
            )
        )

    @app.get("/api/sites/{site_id}/self-improving/gaps")
    def site_confidence_gaps(site_id: str, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
        return to_jsonable(confidence_gaps_payload(site_id, limit=limit))

    @app.get("/api/sites/{site_id}/runs")
    def site_runs(site_id: str) -> dict[str, Any]:
        return to_jsonable(list_runs_payload(site_id))

    @app.get("/api/sites/{site_id}/runs/{run_id}")
    def site_run(site_id: str, run_id: str, event_limit: int = Query(200, ge=1, le=5000)) -> dict[str, Any]:
        return to_jsonable(run_payload(site_id, run_id, event_limit=event_limit))

    @app.get("/api/sites/{site_id}/metrics/runs")
    def site_metrics_runs(site_id: str, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
        return to_jsonable(metrics_runs_payload(site_id, limit=limit))

    @app.get("/api/sites/{site_id}/metrics/runs/{run_id}")
    def site_metrics_run(site_id: str, run_id: str) -> dict[str, Any]:
        return to_jsonable(metrics_run_payload(site_id, run_id))

    @app.get("/api/sites/{site_id}/metrics/rollups")
    def site_metrics_rollups(
        site_id: str,
        windows: str = Query(",".join(STANDARD_WINDOWS)),
        as_of: str = "",
        include_all_time: bool = True,
    ) -> dict[str, Any]:
        return to_jsonable(metrics_rollups_payload(site_id, windows=windows, as_of=as_of or None, include_all_time=include_all_time))

    @app.get("/api/sites/{site_id}/wiki/agent")
    def wiki_agent(site_id: str) -> dict[str, Any]:
        return to_jsonable(wiki_agent_payload(site_id))

    @app.get("/api/sites/{site_id}/wiki/pages")
    def wiki_pages(site_id: str, q: str = "", limit: int = Query(200, ge=1, le=2000)) -> dict[str, Any]:
        return to_jsonable(wiki_pages_payload(site_id, query=q, limit=limit))

    @app.get("/api/sites/{site_id}/document-preview")
    def document_preview(site_id: str, path: str, limit_chars: int = Query(80_000, ge=1, le=500_000)) -> dict[str, Any]:
        return to_jsonable(site_relative_text_payload(site_id, path, limit_chars=limit_chars))

    @app.get("/api/stream/sites/{site_id}")
    def stream_site(site_id: str, interval: float = Query(2.5, ge=0.5, le=10.0)) -> StreamingResponse:
        return StreamingResponse(site_event_stream(site_id, interval), media_type="text/event-stream")

    static_dir = PROJECT_ROOT / "frontend" / "dist"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


app = create_app()
