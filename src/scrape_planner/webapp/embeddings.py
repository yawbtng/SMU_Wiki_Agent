from __future__ import annotations

import inspect
import os
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks

from ..runtime.agent_run_metrics import build_embedding_metric_event
from ..runtime.openrouter_pricing import resolve_embedding_metric_cost
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
        "progress": {},
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
        "progress": state.get("progress") if isinstance(state.get("progress"), dict) else {},
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
        "progress": {},
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
    from ..app.tmux_settings import apply_app_state_env_bridge

    apply_app_state_env_bridge()
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
    progress_log_state = {"last_logged_at": 0.0}

    def progress_callback(event: dict[str, Any]) -> None:
        nonlocal state
        progress = _embedding_progress_payload(event)
        state = write_embedding_job_state(root, {**state, "status": "running", "progress": progress})
        line = _embedding_progress_log_line(progress)
        if line and _should_log_embedding_progress(progress, progress_log_state):
            append_embedding_log(log_path, line)

    try:
        append_embedding_log(log_path, f"Embedding rebuild started for {site_id} via {trigger} at {utc_now()}")
        append_embedding_log(log_path, "Scanning raw sources and wiki pages…")
        write_embedding_job_state(root, {**state, "status": "running", "started_at": state.get("started_at") or utc_now()})
        if build_index is None:
            from ..wiki.llm_wiki_index import build_llm_wiki_index

            build_index = build_llm_wiki_index
        append_embedding_log(log_path, "Building hybrid BM25 + vector index…")
        report = _call_embedding_build_index(build_index, root, progress_callback=progress_callback)
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
                "progress": state.get("progress") if isinstance(state.get("progress"), dict) else {},
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
                "progress": state.get("progress") if isinstance(state.get("progress"), dict) else {},
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
                "progress": state.get("progress") if isinstance(state.get("progress"), dict) else {},
            },
        )
    finally:
        release_embedding_lock(root, fd)


def _call_embedding_build_index(build_index, root: Path, *, progress_callback) -> dict[str, Any]:
    try:
        signature = inspect.signature(build_index)
    except (TypeError, ValueError):
        return build_index(root, progress_callback=progress_callback)
    accepts_progress = "progress_callback" in signature.parameters or any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
    )
    if accepts_progress:
        return build_index(root, progress_callback=progress_callback)
    return build_index(root)


def _embedding_progress_payload(event: dict[str, Any]) -> dict[str, Any]:
    progress = {str(key): _json_safe_progress_value(value) for key, value in dict(event).items()}
    total = _progress_int(progress.get("total_changed_document_count") or progress.get("changed_document_count"))
    embedded = _progress_int(progress.get("embedded_document_count"))
    if total > 0:
        percent = min(100.0, max(0.0, (embedded / total) * 100.0))
    elif str(progress.get("stage") or "") in {"complete", "documents_written", "zvec_ready"}:
        percent = 100.0
    else:
        percent = 0.0
    progress["percent_complete"] = round(percent, 2)
    progress["label"] = _embedding_progress_label(progress)
    progress["updated_at"] = utc_now()
    return progress


def _json_safe_progress_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe_progress_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_progress_value(item) for item in value]
    return str(value)


def _embedding_progress_label(progress: dict[str, Any]) -> str:
    stage = str(progress.get("stage") or "")
    if stage == "embedding_plan":
        return "Embedding plan ready"
    if stage == "embedding_batch":
        return "Embedding chunks"
    if stage == "writing_artifacts":
        return "Writing index artifacts"
    if stage == "documents_written":
        return "Index artifacts written"
    if stage == "zvec_building":
        return "Building zvec store"
    if stage == "zvec_ready":
        return "Zvec store ready"
    if stage == "complete":
        return "Rebuild complete"
    if stage:
        return stage.replace("_", " ").capitalize()
    return "Embedding rebuild"


def _embedding_progress_log_line(progress: dict[str, Any]) -> str:
    stage = str(progress.get("stage") or "")
    changed = _progress_int(progress.get("total_changed_document_count") or progress.get("changed_document_count"))
    total = _progress_int(progress.get("total_document_count"))
    reused = _progress_int(progress.get("skipped_document_count"))
    estimated_tokens = _progress_int(progress.get("estimated_input_tokens"))
    estimated_cost = _progress_float(progress.get("estimated_embedding_cost_usd"))
    if stage == "embedding_plan":
        return (
            "Embedding plan: "
            f"{_format_count(changed)} changed chunks, {_format_count(reused)} reused, {_format_count(total)} total; "
            f"batch size {_format_count(progress.get('batch_size'))}; "
            f"estimated {_format_count(estimated_tokens)} input tokens (~{_format_usd(estimated_cost)})."
        )
    if stage == "embedding_batch":
        embedded = _progress_int(progress.get("embedded_document_count"))
        percent = _progress_float(progress.get("percent_complete"))
        batch_index = _progress_int(progress.get("batch_index"))
        batch_count = _progress_int(progress.get("batch_count"))
        eta = _progress_float(progress.get("estimated_seconds_remaining"))
        elapsed = _progress_float(progress.get("elapsed_seconds"))
        return (
            "Embedding batch "
            f"{_format_count(batch_index)}/{_format_count(batch_count)}: "
            f"{_format_count(embedded)}/{_format_count(changed)} chunks ({percent:.1f}%), "
            f"elapsed {_format_duration(elapsed)}, ETA {_format_duration(eta)}, "
            f"estimated cost {_format_usd(estimated_cost)}."
        )
    if stage == "writing_artifacts":
        return "Embedding vectors ready; writing JSONL and BM25 artifacts."
    if stage == "documents_written":
        return "Index artifacts written; building zvec vector store."
    if stage == "zvec_building":
        return "Building zvec vector store from embedded rows."
    if stage == "zvec_ready":
        vector_store = progress.get("vector_store") if isinstance(progress.get("vector_store"), dict) else {}
        return f"Zvec vector store ready with {_format_count(vector_store.get('documents'))} documents."
    if stage == "complete":
        elapsed = _progress_float(progress.get("elapsed_seconds"))
        return f"Embedding rebuild complete in {_format_duration(elapsed)}; estimated embedding cost {_format_usd(estimated_cost)}."
    return ""


def _should_log_embedding_progress(progress: dict[str, Any], log_state: dict[str, float]) -> bool:
    stage = str(progress.get("stage") or "")
    if stage != "embedding_batch":
        return True
    batch_index = _progress_int(progress.get("batch_index"))
    batch_count = _progress_int(progress.get("batch_count"))
    now = time.monotonic()
    if batch_index <= 1 or (batch_count > 0 and batch_index >= batch_count):
        log_state["last_logged_at"] = now
        return True
    if now - float(log_state.get("last_logged_at") or 0.0) >= 30.0:
        log_state["last_logged_at"] = now
        return True
    return False


def _progress_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _progress_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _format_count(value: Any) -> str:
    return f"{_progress_int(value):,}"


def _format_usd(value: float) -> str:
    if value <= 0:
        return "$0.00"
    if value < 0.01:
        return f"${value:.4f}"
    return f"${value:.2f}"


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(round(float(seconds or 0))))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _record_embedding_metric_event(root: Path, site_id: str, *, state: dict[str, Any], report: dict[str, Any]) -> None:
    run_id = str(state.get("run_id") or os.getenv("WIKI_AGENT_RUN_ID") or os.getenv("RALPH_AGENT_RUN_ID") or "").strip()
    if not run_id:
        return
    raw_count = int(report.get("raw_index_count") or report.get("raw_count") or report.get("raw_documents") or 0)
    wiki_count = int(report.get("wiki_index_count") or report.get("wiki_count") or report.get("wiki_documents") or 0)
    skipped_count = int(report.get("skipped_document_count") or 0)
    changed_count = int(report.get("changed_document_count") or state.get("changed_document_count") or 0)
    embedding = report.get("embedding") if isinstance(report.get("embedding"), dict) else {}
    progress = state.get("progress") if isinstance(state.get("progress"), dict) else {}
    estimated_tokens = report.get("estimated_input_tokens")
    if estimated_tokens is None:
        estimated_tokens = embedding.get("estimated_input_tokens")
    if estimated_tokens is None:
        estimated_tokens = progress.get("estimated_input_tokens")
    input_tokens: int | None
    try:
        input_tokens = int(estimated_tokens) if estimated_tokens not in (None, "") else None
    except (TypeError, ValueError):
        input_tokens = None
    model = str(embedding.get("model") or report.get("embedding_model") or "openai/text-embedding-3-small")
    metric_cost = resolve_embedding_metric_cost(
        input_tokens=input_tokens,
        model=model,
        estimated_cost_usd=report.get("estimated_embedding_cost_usd") or progress.get("estimated_embedding_cost_usd"),
        report=report,
        progress=progress,
    )
    metrics = metrics_repo()
    try:
        metrics.append_event(
            build_embedding_metric_event(
                run_id=run_id,
                site_id=site_id,
                timestamp=str(report.get("built_at") or report.get("last_build_time") or utc_now()),
                stage="embed",
                operation="build_llm_wiki_index",
                provider=str(embedding.get("provider") or "openrouter"),
                model=model,
                input_tokens=input_tokens,
                document_count=raw_count + wiki_count,
                chunk_count=raw_count + wiki_count,
                vector_count=raw_count + wiki_count,
                reused_vector_count=skipped_count,
                skipped_chunk_count=skipped_count,
                failed_chunk_count=0,
                duration_ms=None,
                cost_usd=metric_cost.amount_usd,
                cost_source=metric_cost.source,
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
