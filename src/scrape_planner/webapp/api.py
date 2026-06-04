from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import sys
import threading
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ..runtime.agent_run_metrics import STANDARD_WINDOWS
from ..app.navigation import WORKFLOW_TABS
from ..pdf.pdf_ingest import PdfIngestConfig, ingest_pdfs
from ..runtime.run_persistence import read_page_states, read_run_events, read_run_status
from ..scrape.scrape_url_selection import urls_for_site_scrape
from ..scrape.scrape_worker import ScrapeRunner
from ..scrape.sitemap_discovery import discover_site_urls, normalize_site_url
from ..runtime.state import RunStateStore
from ..core.storage import read_json, write_json
from ..infra.tmux_runner import TmuxRunner
from ..sources.raw_source_normalizer import normalize_pdf_pages
from ..wiki.self_improving import read_confidence_gaps
from ..wiki.llm_wiki_index import site_mcp_query_readiness
from .approved_urls import (
    approval_chat_payload,
    approved_urls_payload,
    commit_approved_urls_payload,
    write_approved_urls_payload,
)
from .deps import (
    PROJECT_ROOT,
    app_state_path,
    artifact_repo,
    data_root,
    mcp_runner,
    metrics_repo,
    read_json_file,
    read_jsonl_tail,
    reports_dir,
    run_root,
    site_root,
    state_repo,
    status_model,
    to_jsonable,
    utc_now,
)
from .embeddings import (
    embedding_enabled,
    embedding_prerequisites_ready,
    load_embedding_job_state,
    maybe_auto_queue_embedding_job,
    run_embedding_job,
    trigger_embedding_rebuild,
)
from .schemas import ApprovedUrlsChatRequest
from .tmux_sessions import kill_site_tmux_sessions

__all__ = [
    "ApprovedUrlsChatRequest",
    "approval_chat_payload",
    "create_app",
    "discover_site_urls",
    "run_embedding_job",
    "scrape_runner",
    "site_event_stream",
    "sse_event",
    "start_mcp_server_for_site",
    "stop_mcp_server_for_site",
    "tmux_session_exists",
]


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


def delete_site_payload(site_id: str, *, runner: TmuxRunner | None = None) -> dict[str, Any]:
    root = site_root(site_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="site not found")

    metadata = _workspace_metadata()
    workspace_url = str(metadata.get(site_id, {}).get("url") or "")
    if not workspace_url:
        summary = read_json(root / "discovery_summary.json", {})
        if isinstance(summary, dict):
            workspace_url = str(summary.get("site_url") or "")

    killed_sessions = kill_site_tmux_sessions(site_id, runner=runner)
    shutil.rmtree(root)

    repo = state_repo()
    state = dict(repo.load())
    workspaces = [
        item
        for item in state.get("workspaces", [])
        if isinstance(item, dict) and str(item.get("id") or "") != site_id
    ]
    state["workspaces"] = workspaces
    if str(state.get("active_workspace_id") or "") == site_id:
        state["active_workspace_id"] = ""
    if str(state.get("last_site_id") or "") == site_id:
        state["last_site_id"] = ""
    if workspace_url:
        state["site_history"] = [item for item in state.get("site_history", []) if item != workspace_url]
    repo.save(state)

    return {
        "site_id": site_id,
        "deleted": True,
        "killed_sessions": killed_sessions,
        "app_state": repo.load(),
        **list_sites_payload(),
    }


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
    layout = statuses.layout(site_id)
    from ..wiki.stepper_status import load_wiki_status, raw_source_status

    raw_status = raw_source_status(layout)
    wiki_status = load_wiki_status(layout, raw_status)
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


GLOBAL_MCP_SESSION_NAME = "llm-wiki-mcp-global"


def mcp_server_state_path(root: Path | None = None) -> Path:
    if root is not None and root.name != "sites":
        return root / "indexes" / "mcp-server-latest.json"
    return data_root() / "runtime" / "mcp-server-latest.json"


def mcp_session_name(site_id: str = "global") -> str:
    if site_id == "global":
        return GLOBAL_MCP_SESSION_NAME
    normalized = "".join(ch if ch.isalnum() else "-" for ch in site_id.lower()).strip("-")
    return f"llm-wiki-mcp-{normalized or 'site'}"


def global_mcp_server_command() -> str:
    return " ".join([sys.executable, "-m", "mcp_servers.llm_wiki_mcp", "--data-root", str(data_root())])


def _workspace_metadata() -> dict[str, dict[str, Any]]:
    state = state_repo().load()
    rows = state.get("workspaces") if isinstance(state, dict) else []
    metadata: dict[str, dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            site_id = str(row.get("id") or "").strip()
            if site_id:
                metadata[site_id] = row
    return metadata


def _site_has_markdown_pages(site_path: Path) -> bool:
    wiki_dir = site_path / "wiki"
    if (wiki_dir / "index.md").exists():
        return True
    pages_dir = wiki_dir / "pages"
    return pages_dir.exists() and any(pages_dir.rglob("*.md"))


def _site_has_query_index(site_path: Path) -> bool:
    candidates = [
        site_path / "indexes" / "llm_wiki_documents.jsonl",
        site_path / "indexes" / "llm_wiki_manifest.json",
        site_path / "wiki" / "index" / "llm_wiki_documents.jsonl",
        site_path / "wiki" / "index" / "llm_wiki_manifest.json",
    ]
    if any(path.exists() for path in candidates):
        return True
    reports_dir = site_path / "indexes" / "reports"
    if not reports_dir.exists():
        return False
    for report_path in sorted(reports_dir.glob("embedding-*.json"), reverse=True):
        report = read_json(report_path, {})
        if not isinstance(report, dict):
            continue
        if str(report.get("status") or "").lower() not in {"ready", "complete", "completed"}:
            continue
        if int(report.get("raw_index_count") or 0) > 0 or int(report.get("wiki_index_count") or 0) > 0:
            return True
    return False


def list_mcp_universities_payload() -> dict[str, Any]:
    sites_root = data_root() / "sites"
    metadata = _workspace_metadata()
    universities: list[dict[str, Any]] = []
    if sites_root.exists():
        for path in sorted(sites_root.iterdir(), key=lambda item: item.name):
            if not path.is_dir():
                continue
            summary = read_json(path / "discovery_summary.json", {})
            site_id = path.name
            meta = metadata.get(site_id, {})
            url = str(meta.get("url") or summary.get("site_url") or "")
            domain = urlparse(url).netloc or site_id
            wiki_ready = _site_has_markdown_pages(path)
            query_health = site_mcp_query_readiness(path)
            index_ready = bool(query_health.get("query_ready"))
            universities.append(
                {
                    "site_id": site_id,
                    "name": str(meta.get("name") or summary.get("name") or site_id),
                    "url": url,
                    "domain": domain,
                    "site_root": str(path),
                    "wiki_ready": wiki_ready,
                    "index_ready": index_ready,
                    "mcp_enabled": index_ready,
                    "mcp_block_reason": str(query_health.get("mcp_block_reason") or ""),
                }
            )
    ready_count = sum(1 for row in universities if row["mcp_enabled"])
    return {
        "universities": universities,
        "count": len(universities),
        "ready_count": ready_count,
        "generated_at": utc_now(),
    }


def empty_mcp_server_state(site_id: str = "global") -> dict[str, Any]:
    is_global = site_id == "global"
    return {
        "scope": "global" if is_global else "site",
        "site_id": "global" if is_global else site_id,
        "session_name": mcp_session_name(site_id),
        "status": "idle",
        "running": False,
        "server_command": global_mcp_server_command() if is_global else "",
        "started_at": "",
        "updated_at": "",
        "last_error": "",
    }


def load_mcp_server_state(root: Path | None = None, site_id: str = "global") -> dict[str, Any]:
    payload = read_json(mcp_server_state_path(root), {})
    state = empty_mcp_server_state(site_id)
    if isinstance(payload, dict):
        state.update(payload)
    is_global = root is None and site_id == "global"
    state["scope"] = "global" if is_global else "site"
    state["site_id"] = "global" if is_global else site_id
    state["session_name"] = mcp_session_name("global" if is_global else site_id)
    if is_global:
        state["server_command"] = str(state.get("server_command") or global_mcp_server_command())
    return state


def write_mcp_server_state(root: Path | None, state: dict[str, Any]) -> dict[str, Any]:
    is_global = root is None
    site_id = str(state.get("site_id") or "global")
    state = {
        **state,
        "scope": "global" if is_global else "site",
        "site_id": "global" if is_global else site_id,
        "session_name": mcp_session_name("global" if is_global else site_id),
        "updated_at": utc_now(),
    }
    write_json(mcp_server_state_path(root), state)
    return state


def mcp_runtime_status(root: Path | None, site_id: str, mcp_status: dict[str, Any]) -> dict[str, Any]:
    state = load_mcp_server_state(None, "global")
    runner = mcp_runner()
    running = runner.session_exists(GLOBAL_MCP_SESSION_NAME) if runner.available() else False
    universities = list_mcp_universities_payload()
    command = state.get("server_command") or global_mcp_server_command()
    return {
        "scope": "global",
        "site_id": "global",
        "session_name": GLOBAL_MCP_SESSION_NAME,
        "running": running,
        "server_available": True,
        "last_start_status": state.get("status") or "idle",
        "last_error": state.get("last_error") or "",
        "updated_at": state.get("updated_at") or "",
        "server_command": command,
        "university_count": universities["count"],
        "ready_university_count": universities["ready_count"],
        "index_health": mcp_status.get("index_health") or "global",
    }


def global_mcp_status_payload(*, runner: TmuxRunner | None = None) -> dict[str, Any]:
    tmux = runner or mcp_runner()
    state = load_mcp_server_state(None, "global")
    running = tmux.session_exists(GLOBAL_MCP_SESSION_NAME) if tmux.available() else False
    state = {**state, "running": running, "server_command": state.get("server_command") or global_mcp_server_command()}
    universities = list_mcp_universities_payload()
    return {
        "mcp": {
            **state,
            "server_available": True,
            "last_start_status": state.get("status") or "idle",
            "university_count": universities["count"],
            "ready_university_count": universities["ready_count"],
        },
        **universities,
    }


def start_global_mcp_server(*, runner: TmuxRunner | None = None) -> dict[str, Any]:
    state = load_mcp_server_state(None, "global")
    tmux = runner or mcp_runner()
    command = global_mcp_server_command()
    if not tmux.available():
        state = write_mcp_server_state(None, {**state, "status": "failed", "running": False, "server_command": command, "last_error": "tmux_not_available"})
        return {"status": "failed", "mcp": state, **list_mcp_universities_payload()}
    if tmux.session_exists(GLOBAL_MCP_SESSION_NAME):
        state = write_mcp_server_state(None, {**state, "status": "running", "running": True, "server_command": command, "last_error": ""})
        return {"status": "already_running", "mcp": state, **list_mcp_universities_payload()}
    result = tmux.start(GLOBAL_MCP_SESSION_NAME, command, str(PROJECT_ROOT))
    if not result.get("ok"):
        state = write_mcp_server_state(None, {**state, "status": "failed", "running": False, "server_command": command, "last_error": str(result.get("error") or "failed_to_start_mcp_server")})
        return {"status": "failed", "mcp": state, **list_mcp_universities_payload()}
    state = write_mcp_server_state(None, {**state, "status": "running", "running": True, "server_command": command, "started_at": utc_now(), "last_error": ""})
    return {"status": "started", "mcp": state, **list_mcp_universities_payload()}


def stop_global_mcp_server(*, runner: TmuxRunner | None = None) -> dict[str, Any]:
    state = load_mcp_server_state(None, "global")
    tmux = runner or mcp_runner()
    if not tmux.available():
        state = write_mcp_server_state(None, {**state, "status": "failed", "running": False, "last_error": "tmux_not_available"})
        return {"status": "failed", "mcp": state, **list_mcp_universities_payload()}
    if not tmux.session_exists(GLOBAL_MCP_SESSION_NAME):
        state = write_mcp_server_state(None, {**state, "status": "stopped", "running": False, "last_error": ""})
        return {"status": "not_running", "mcp": state, **list_mcp_universities_payload()}
    kill = tmux.kill(GLOBAL_MCP_SESSION_NAME)
    if not kill.get("ok"):
        state = write_mcp_server_state(None, {**state, "status": "failed", "running": False, "last_error": str(kill.get("error") or "failed_to_stop_mcp_server")})
        return {"status": "failed", "mcp": state, **list_mcp_universities_payload()}
    state = write_mcp_server_state(None, {**state, "status": "stopped", "running": False, "stopped_at": utc_now(), "last_error": ""})
    return {"status": "stopped", "mcp": state, **list_mcp_universities_payload()}


def restart_global_mcp_server(*, runner: TmuxRunner | None = None) -> dict[str, Any]:
    tmux = runner or mcp_runner()
    stop_global_mcp_server(runner=tmux)
    return start_global_mcp_server(runner=tmux)


def start_mcp_server_for_site(root: Path, site_id: str, mcp_status: dict[str, Any], *, runner: TmuxRunner | None = None) -> dict[str, Any]:
    """Compatibility wrapper: MCP is now one global gateway, not a site-scoped server."""
    result = start_global_mcp_server(runner=runner)
    result["deprecated_site_route"] = True
    result["requested_site_id"] = site_id
    return result


def stop_mcp_server_for_site(root: Path, site_id: str, *, runner: TmuxRunner | None = None) -> dict[str, Any]:
    """Compatibility wrapper: MCP is now one global gateway, not a site-scoped server."""
    result = stop_global_mcp_server(runner=runner)
    result["deprecated_site_route"] = True
    result["requested_site_id"] = site_id
    return result


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


def upload_documents_payload(site_id: str, files: list[dict[str, Any]]) -> dict[str, Any]:
    root = site_root(site_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="site not found")
    if not files:
        raise HTTPException(status_code=400, detail="no files uploaded")

    sources_root = root / "sources"
    uploads_dir = sources_root / "pdf_uploads"
    ingest_dir = sources_root / "pdf_ingest"
    pages_dir = sources_root / "pdf_pages"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    ingest_dir.mkdir(parents=True, exist_ok=True)

    uploaded: list[dict[str, Any]] = []
    paths: list[Path] = []
    timestamp = utc_now()
    for item in files:
        filename = _safe_upload_filename(str(item.get("filename") or "document.pdf"))
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"unsupported file type: {filename}")
        content = item.get("content")
        if not isinstance(content, bytes) or not content:
            raise HTTPException(status_code=400, detail=f"empty upload: {filename}")
        path = _unique_upload_path(uploads_dir, filename)
        path.write_bytes(content)
        paths.append(path)
        uploaded.append({"path": str(path), "filename": path.name, "uploaded_at": timestamp})

    _merge_pdf_manifest(sources_root / "pdf_manifest.json", uploaded)

    result = ingest_pdfs(paths, PdfIngestConfig(page_markdown_dir=pages_dir))
    _write_jsonl(ingest_dir / "pdf_sources.jsonl", [row.to_dict() for row in result.sources])
    _write_jsonl(ingest_dir / "pdf_chunks.jsonl", [row.to_dict() for row in result.chunks])
    _write_jsonl(ingest_dir / "pdf_quarantine.jsonl", [row.to_dict() for row in result.quarantine])
    registry = normalize_pdf_pages(root)

    return {
        "site_id": site_id,
        "uploaded_count": len(uploaded),
        "accepted_count": sum(1 for row in result.sources if row.accepted),
        "chunk_count": len(result.chunks),
        "quarantine_count": len(result.quarantine),
        "uploaded": uploaded,
        "sources": [row.to_dict() for row in result.sources],
        "quarantine": [row.to_dict() for row in result.quarantine],
        "registry": {
            "counts": registry.counts,
            "registry_path": registry.registry_path,
            "report_path": registry.report_path,
        },
        "generated_at": utc_now(),
    }


def _safe_upload_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    cleaned = "".join(ch if ch.isalnum() or ch in {".", "-", "_"} else "-" for ch in name).strip(".-")
    return cleaned or "document.pdf"


def _unique_upload_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(2, 1000):
        next_candidate = directory / f"{stem}-{index}{suffix}"
        if not next_candidate.exists():
            return next_candidate
    raise HTTPException(status_code=409, detail=f"too many uploads named {filename}")


def _merge_pdf_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    current = read_json(path, [])
    merged = {str(row.get("path") or ""): row for row in current if isinstance(row, dict) and row.get("path")}
    for row in rows:
        merged[str(row["path"])] = row
    write_json(path, list(merged.values()))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    existing = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                with contextlib.suppress(json.JSONDecodeError):
                    parsed = json.loads(line)
                    if isinstance(parsed, dict):
                        existing.append(parsed)
    key = "chunk_id" if path.name == "pdf_chunks.jsonl" else "pdf_source_id"
    merged = {str(row.get(key) or ""): row for row in existing if row.get(key)}
    for row in rows:
        row_key = str(row.get(key) or "")
        if row_key:
            merged[row_key] = row
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=True) + "\n" for row in merged.values()), encoding="utf-8")


_TMUX_CACHE: dict[str, tuple[float, bool]] = {}
_TMUX_CACHE_TTL_SECONDS = 3.0


def wiki_agent_payload(site_id: str, *, compact: bool = False) -> dict[str, Any]:
    directory = reports_dir(site_id)
    run_state = read_json_file(directory / "wiki-agent-run-latest.json", {})
    tasks = read_json_file(directory / "wiki-agent-tasks-latest.json", {})
    wiki_build_report = read_json_file(directory / "wiki-build-latest.json", {})
    build_session = str(wiki_build_report.get("tmux_session") or "")
    build_status = str(wiki_build_report.get("job_status") or wiki_build_report.get("status") or "")
    if wiki_build_report:
        build_alive = tmux_session_exists(build_session) if build_session else False
        run_state = {
            "status": build_status,
            "job_status": build_status,
            "runtime": wiki_build_report.get("runtime"),
            "site_root": wiki_build_report.get("site_root"),
            "site_id": site_id,
            "tmux_session": build_session,
            "mode": "rebuild" if wiki_build_report.get("rebuild") else "resume",
            "current_task": wiki_build_report.get("last_progress") or "LLM Wiki v2 compile",
            "last_error": wiki_build_report.get("last_error") or "",
            "started_at": wiki_build_report.get("generated_at") or "",
            "updated_at": wiki_build_report.get("updated_at") or "",
            "job_finished_at": wiki_build_report.get("job_finished_at") or "",
            "tmux_session_alive": build_alive,
        }
    summary = ""
    summary_path = directory / "wiki-agent-summary-latest.md"
    if summary_path.exists() and not compact:
        try:
            summary = summary_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            summary = ""
    event_limit = 5 if compact else 200
    events = read_jsonl_tail(directory / "wiki-agent-events-latest.jsonl", event_limit)
    pi_events_path = wiki_build_report.get("pi_events_path")
    if pi_events_path:
        from ..app.pi_agent import read_pi_events_after

        pi_events, _ = read_pi_events_after(Path(pi_events_path), 0, limit=event_limit)
        if pi_events:
            events = pi_events
    pane_log_path = directory / "wiki-agent-pane-latest.log"
    pane_tail = ""
    if pane_log_path.exists() and not compact:
        try:
            pane_tail = "\n".join(pane_log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-160:])
        except OSError:
            pane_tail = ""

    stale_running = False
    if str(run_state.get("status") or "").lower() == "running":
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
    from ..infra.tmux_session_shell import sanitize_tmux_session_name

    session = sanitize_tmux_session_name(session)
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


_GUIDE_PAGE_TYPES = frozenset({"semantic", "category", "navigation", "concept", "entity", "workflow", "process"})
_PDF_SHARD_MARKERS = ("catalog-pdf", "/pdf-p-", "-pdf-")
_EVIDENCE_PAGE_DIRS = frozenset({"admissions", "general", "finance", "departments", "registrar", "scholarships"})
_GUIDE_PAGE_PREFIXES = ("schools", "answers")


def _iter_wiki_page_paths(pages_root: Path, *, view: str):
    normalized_view = str(view or "guides").strip().lower()
    if normalized_view == "all":
        yield from pages_root.rglob("*.md")
        return
    if normalized_view == "sources":
        for directory in sorted(_EVIDENCE_PAGE_DIRS):
            root = pages_root / directory
            if root.is_dir():
                yield from root.rglob("*.md")
        return
    yield from pages_root.glob("*.md")
    for prefix in _GUIDE_PAGE_PREFIXES:
        root = pages_root / prefix
        if root.is_dir():
            yield from root.rglob("*.md")


def _wiki_page_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:8192]
    except OSError:
        return {}, ""
    if not head.startswith("---"):
        return {}, head
    end = head.find("\n---", 3)
    if end < 0:
        return {}, head
    meta: dict[str, str] = {}
    for line in head[3:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    body = head[end + 4 :]
    return meta, body


def _wiki_display_title(meta: dict[str, str], path: Path, body: str) -> str:
    title = str(meta.get("title") or "").strip()
    if title and not title.startswith("Source:"):
        return title
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    if title:
        return title
    return path.stem.replace("-", " ").strip() or "Untitled"


def _wiki_page_type(meta: dict[str, str], rel_str: str) -> str:
    explicit = str(meta.get("page_type") or "").strip().lower()
    if explicit:
        return explicit
    if any(marker in rel_str for marker in _PDF_SHARD_MARKERS):
        return "source"
    if rel_str.startswith("pages/schools/") or rel_str.endswith("-guide.md"):
        return "semantic"
    if rel_str.count("/") <= 1:
        return "category"
    return "unknown"


def _wiki_page_in_view(page_type: str, rel_str: str, *, view: str) -> bool:
    normalized_view = str(view or "guides").strip().lower()
    if normalized_view == "all":
        return True
    is_pdf_shard = any(marker in rel_str for marker in _PDF_SHARD_MARKERS)
    if normalized_view == "sources":
        return page_type == "source" or is_pdf_shard
    # Default: student-facing guides and hubs, not per-PDF evidence shards.
    if page_type == "source" or is_pdf_shard:
        return False
    if page_type in _GUIDE_PAGE_TYPES:
        return True
    if rel_str.startswith("pages/schools/") or rel_str.endswith("-guide.md"):
        return True
    if page_type == "unknown" and rel_str.count("/") <= 1:
        return True
    return False


def wiki_generation_payload(site_id: str) -> dict[str, Any]:
    root = site_root(site_id)
    wiki_dir = root / "wiki"
    reports_dir = wiki_dir / "reports"
    build_report = read_json_file(reports_dir / "wiki-build-latest.json", {})
    index_path = wiki_dir / "index.md"
    index_updated = ""
    if index_path.exists():
        try:
            index_updated = datetime.fromtimestamp(index_path.stat().st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            index_updated = ""

    counts = {"semantic": 0, "category": 0, "source": 0, "other": 0, "total": 0, "guides": 0}
    pages_root = wiki_dir / "pages"
    if pages_root.exists():
        for path in _iter_wiki_page_paths(pages_root, view="guides"):
            meta, _ = _wiki_page_frontmatter(path)
            rel_str = str(path.relative_to(wiki_dir))
            page_type = _wiki_page_type(meta, rel_str)
            counts["guides"] += 1
            if page_type in counts:
                counts[page_type] += 1
            else:
                counts["other"] += 1
        for path in _iter_wiki_page_paths(pages_root, view="sources"):
            counts["source"] += 1
        counts["total"] = counts["guides"] + counts["source"]

    session = str(build_report.get("tmux_session") or "")
    job_status = str(build_report.get("job_status") or build_report.get("status") or "unknown")
    return {
        "site_id": site_id,
        "job_status": job_status,
        "runtime": build_report.get("runtime"),
        "tmux_session": session,
        "tmux_session_alive": tmux_session_exists(session) if session else False,
        "pages_created": build_report.get("pages_created"),
        "pages_updated": build_report.get("pages_updated"),
        "integrated_sources": build_report.get("integrated_sources"),
        "semantic_page_count": counts["semantic"],
        "category_page_count": counts["category"],
        "guide_page_count": counts["guides"],
        "source_page_count": counts["source"],
        "total_page_count": counts["total"],
        "index_updated_at": index_updated,
        "pi_events_path": build_report.get("pi_events_path"),
        "report_path": str(reports_dir / "wiki-build-latest.json"),
        "generated_at": utc_now(),
    }


def wiki_pages_payload(site_id: str, query: str = "", limit: int = 200, *, view: str = "guides") -> dict[str, Any]:
    pages_root = site_root(site_id) / "wiki" / "pages"
    rows: list[dict[str, Any]] = []
    needle = query.strip().lower()
    if pages_root.exists():
        for path in _iter_wiki_page_paths(pages_root, view=view):
            rel = path.relative_to(site_root(site_id) / "wiki")
            rel_str = str(rel)
            meta, body = _wiki_page_frontmatter(path)
            page_type = _wiki_page_type(meta, rel_str)
            if not _wiki_page_in_view(page_type, rel_str, view=view):
                continue
            title = _wiki_display_title(meta, path, body)
            category = meta.get("category") or (rel.parts[1] if len(rel.parts) > 2 else rel.parts[0] if rel.parts else "")
            haystack = " ".join([rel_str, title, category, page_type]).lower()
            if needle and needle not in haystack:
                continue
            rows.append(
                {
                    "path": rel_str,
                    "title": title,
                    "category": category,
                    "page_type": page_type,
                    "size": path.stat().st_size,
                    "mtime": path.stat().st_mtime,
                }
            )
        rows.sort(
            key=lambda row: (
                0 if str(row.get("page_type")) == "semantic" else 1,
                str(row.get("category") or "").lower(),
                str(row.get("title") or "").lower(),
            )
        )
        rows = rows[:limit]
    return {
        "site_id": site_id,
        "query": query,
        "view": view,
        "pages": rows,
        "total_matching": len(rows),
        "generated_at": utc_now(),
    }


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


async def site_event_stream(
    site_id: str,
    interval: float,
    *,
    is_disconnected: Any | None = None,
) -> AsyncIterator[str]:
    from ..app.pi_agent import active_pi_events_for_site, read_pi_events_after

    previous_digest = ""
    pi_offset = 0
    while True:
        if is_disconnected is not None and await is_disconnected():
            break
        try:
            payload = await asyncio.to_thread(site_overview_payload, site_id, compact=True)
            digest = json.dumps(to_jsonable(payload), sort_keys=True, default=str)
            if digest != previous_digest:
                previous_digest = digest
                yield sse_event("site", payload)

            root = site_root(site_id)
            events_path, skill = await asyncio.to_thread(active_pi_events_for_site, root)
            if events_path:
                batch, pi_offset = await asyncio.to_thread(read_pi_events_after, events_path, pi_offset, limit=80)
                if batch:
                    yield sse_event(
                        "pi",
                        {
                            "site_id": site_id,
                            "skill": skill,
                            "events_path": str(events_path),
                            "events": batch,
                            "generated_at": utc_now(),
                        },
                    )
        except Exception as exc:  # keep stream alive for transient file writes
            yield sse_event("error", {"message": str(exc), "generated_at": utc_now()})
        await asyncio.sleep(interval)


def create_app() -> FastAPI:
    from .routes import register_routes

    app = FastAPI(title="Ultra Fast RAG Web API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("SCRAPE_PLANNER_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_routes(app)
    static_dir = PROJECT_ROOT / "frontend" / "dist"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    return app


app = create_app()
