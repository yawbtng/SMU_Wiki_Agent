from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from ..core.storage import append_jsonl as _append_jsonl_impl
from ..core.storage import read_jsonl
from ..core.storage import write_json_atomic as _write_json_atomic_impl
from ..tracer_dependencies import (
    StaleEvaluationResult,
    TracerMaintenanceJobPacket,
    serialize_job_packet,
)

_LOCK = Lock()


def _write_json_atomic(path: Path, payload: Any) -> None:
    with _LOCK:
        _write_json_atomic_impl(path, payload)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with _LOCK:
        _append_jsonl_impl(path, payload)


def write_run_status(run_root: Path, status: dict[str, Any]) -> None:
    _write_json_atomic(run_root / "run_status.json", status)


def read_run_status(run_root: Path) -> dict[str, Any]:
    path = run_root / "run_status.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_run_events(run_root: Path, limit: int | None = None) -> list[dict[str, Any]]:
    events = read_jsonl(run_root / "events.jsonl")
    if limit is None or limit <= 0:
        return events
    return events[-limit:]


def upsert_page_state(run_root: Path, page: dict[str, Any]) -> None:
    _append_jsonl(run_root / "pages.jsonl", page)


def write_page_states(run_root: Path, pages: list[dict[str, Any]]) -> None:
    """Overwrite page state JSONL with one compact row per URL.

    The scrape runner updates a full in-memory snapshot frequently. Appending
    that entire snapshot on every update makes pages.jsonl grow into tens of GB.
    This writer keeps the durable file bounded to the current page count.
    """
    path = run_root / "pages.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        with tmp_path.open("w", encoding="utf-8") as handle:
            for page in pages:
                handle.write(json.dumps(page, ensure_ascii=True) + "\n")
        tmp_path.replace(path)


def read_page_states(run_root: Path) -> list[dict[str, Any]]:
    rows = read_jsonl(run_root / "pages.jsonl")
    pages_by_url: dict[str, dict[str, Any]] = {}
    for row in rows:
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        pages_by_url[url] = row
    return list(pages_by_url.values())


def persist_stale_artifacts_and_packet(
    run_root: Path,
    run_id: str,
    result: StaleEvaluationResult,
    packet: TracerMaintenanceJobPacket | None,
) -> dict[str, Any]:
    stale_snapshot_path = run_root / "stale_dependencies.json"
    stale_events_path = run_root / "stale_dependencies.jsonl"

    snapshot = {
        "run_id": run_id,
        "stale_page_ids": result.stale_page_ids,
        "stale_count": len(result.stale_page_ids),
        "transition_count": len(result.transitions),
        "transitions": [
            {
                "source_id": t.source_id,
                "old_hash": t.old_hash,
                "new_hash": t.new_hash,
                "affected_pages": t.affected_pages,
                "reason": t.reason,
            }
            for t in result.transitions
        ],
        "errors": [{"code": e.code, "detail": e.detail} for e in result.errors],
    }
    _write_json_atomic(stale_snapshot_path, snapshot)

    for transition in result.transitions:
        _append_jsonl(
            stale_events_path,
            {
                "run_id": run_id,
                "source_id": transition.source_id,
                "old_hash": transition.old_hash,
                "new_hash": transition.new_hash,
                "affected_pages": transition.affected_pages,
                "reason": transition.reason,
            },
        )

    packet_dir: Path | None = None
    manifest_path: Path | None = None
    if packet is not None and packet.stale_page_ids:
        packet_dir = run_root / "packets" / run_id
        packet_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = packet_dir / "packet_manifest.json"
        _write_json_atomic(manifest_path, serialize_job_packet(packet))

    return {
        "stale_snapshot_path": str(stale_snapshot_path),
        "stale_events_path": str(stale_events_path),
        "stale_count": len(result.stale_page_ids),
        "transition_count": len(result.transitions),
        "packet_path": str(packet_dir) if packet_dir else None,
        "packet_manifest_path": str(manifest_path) if manifest_path else None,
    }
