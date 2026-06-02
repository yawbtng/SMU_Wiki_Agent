from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks

from ..runtime.agent_run_metrics import build_embedding_metric_event
from ..wiki.stepper_status import raw_sources_ready, wiki_ready
from ..core.storage import read_json, write_json
from .deps import metrics_repo, state_repo, utc_now

ACTIVE_EMBEDDING_JOB_STATUSES = {"queued", "running", "starting", "initializing"}
TERMINAL_EMBEDDING_JOB_STATUSES = {"complete", "completed", "success", "failed", "error", "skipped"}


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


def append_embedding_log(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(str(message).rstrip() + "\n")


def read_embedding_log_tail(log_path: Path, *, lines: int = 40) -> list[str]:
    if not log_path.exists():
        return []
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [line for line in content[-max(1, int(lines)) :] if line.strip()]


def embedding_job_status_payload(site_id: str, root: Path) -> dict[str, Any]:
    state = load_embedding_job_state(root, site_id)
    log_path = Path(str(state.get("log_path") or ""))
    report_path = Path(str(state.get("report_path") or ""))
    report_summary: dict[str, Any] = {}
    if report_path.exists():
        report = read_json(report_path, {})
        if isinstance(report, dict):
            report_summary = {
                "status": report.get("status"),
                "wiki_index_count": report.get("wiki_index_count"),
                "raw_index_count": report.get("raw_index_count"),
                "changed_document_count": report.get("changed_document_count"),
                "last_error": report.get("last_error"),
            }
    status = str(state.get("status") or "idle").lower()
    phase = "idle"
    if status in ACTIVE_EMBEDDING_JOB_STATUSES:
        phase = "queued" if status == "queued" else "building_index"
    elif status in TERMINAL_EMBEDDING_JOB_STATUSES:
        phase = status
    return {
        "site_id": site_id,
        "phase": phase,
        "job_state": state,
        "log_tail": read_embedding_log_tail(log_path),
        "report_summary": report_summary,
        "generated_at": utc_now(),
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
        append_embedding_log(log_path, f"Embedding rebuild started for {site_id} via {trigger} at {utc_now()}")
        append_embedding_log(log_path, "Scanning raw sources and wiki pages…")
        write_embedding_job_state(root, {**state, "status": "running", "started_at": state.get("started_at") or utc_now()})
        if build_index is None:
            from ..wiki.llm_wiki_index import build_llm_wiki_index

            build_index = build_llm_wiki_index
        append_embedding_log(log_path, "Building hybrid BM25 + vector index (may take 1–3 minutes)…")
        report = build_index(root)
        append_embedding_log(
            log_path,
            "Index build finished: "
            f"{int(report.get('wiki_index_count') or 0)} wiki docs, "
            f"{int(report.get('raw_index_count') or 0)} source docs.",
        )
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
        append_embedding_log(log_path, f"Embedding rebuild failed: {error}")
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
        append_embedding_log(log_path, f"Embedding rebuild completed at {utc_now()}")
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
    log_path = Path(str(state.get("log_path") or ""))
    if log_path:
        append_embedding_log(log_path, "Rebuild queued — waiting for background worker…")
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
