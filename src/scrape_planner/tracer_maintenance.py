from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .core.models import utc_now_iso
from .runtime.run_persistence import _append_jsonl, _write_json_atomic


ALLOWED_STALE_REASONS = {"source_hash_changed", "missing_source", "manual_revalidate"}
FORBIDDEN_EVIDENCE_KEYS = {"raw_body", "raw_html", "content", "body", "full_text", "payload"}


@dataclass(frozen=True)
class TracerMaintenancePacket:
    job_id: str
    target_page_id: str
    target_page_path: str
    stale_reason: str
    source_hashes: dict[str, str]
    evidence_refs: list[dict[str, Any]]


@dataclass(frozen=True)
class TracerMaintenanceResult:
    job_id: str
    status: str
    started_at: str
    finished_at: str
    artifacts: dict[str, str]
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_tracer_packet(payload: dict[str, Any]) -> TracerMaintenancePacket:
    required = ["job_id", "target_page_id", "target_page_path", "stale_reason", "source_hashes", "evidence_refs"]
    missing = [k for k in required if k not in payload]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")

    job_id = str(payload["job_id"]).strip()
    page_id = str(payload["target_page_id"]).strip()
    page_path = str(payload["target_page_path"]).strip()
    stale_reason = str(payload["stale_reason"]).strip()

    if not job_id or not page_id or not page_path:
        raise ValueError("job_id, target_page_id, and target_page_path must be non-empty")
    if stale_reason not in ALLOWED_STALE_REASONS:
        raise ValueError(f"unsupported stale_reason: {stale_reason}")

    source_hashes = payload["source_hashes"]
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise ValueError("source_hashes must be a non-empty object")

    evidence_refs = payload["evidence_refs"]
    if not isinstance(evidence_refs, list):
        raise ValueError("evidence_refs must be a list")

    for idx, ref in enumerate(evidence_refs):
        if not isinstance(ref, dict):
            raise ValueError(f"evidence_refs[{idx}] must be an object")
        if FORBIDDEN_EVIDENCE_KEYS.intersection(ref.keys()):
            raise ValueError(f"evidence_refs[{idx}] contains forbidden raw payload fields")

    return TracerMaintenancePacket(
        job_id=job_id,
        target_page_id=page_id,
        target_page_path=page_path,
        stale_reason=stale_reason,
        source_hashes={str(k): str(v) for k, v in source_hashes.items()},
        evidence_refs=evidence_refs,
    )


def _job_root(run_root: Path, job_id: str) -> Path:
    return run_root / "maintenance" / job_id


def append_maintenance_event(run_root: Path, job_id: str, event_type: str, payload: dict[str, Any]) -> Path:
    path = _job_root(run_root, job_id) / "events.jsonl"
    _append_jsonl(
        path,
        {
            "timestamp": utc_now_iso(),
            "job_id": job_id,
            "event": event_type,
            **payload,
        },
    )
    return path


def write_source_usage(run_root: Path, packet: TracerMaintenancePacket) -> Path:
    path = _job_root(run_root, packet.job_id) / "source_usage.jsonl"
    for ref in packet.evidence_refs:
        if FORBIDDEN_EVIDENCE_KEYS.intersection(ref.keys()):
            raise ValueError("source usage record contains forbidden raw payload fields")
        _append_jsonl(
            path,
            {
                "timestamp": utc_now_iso(),
                "job_id": packet.job_id,
                "target_page_id": packet.target_page_id,
                "target_page_path": packet.target_page_path,
                "stale_reason": packet.stale_reason,
                "source_hashes": packet.source_hashes,
                "source_ref": ref,
            },
        )
    return path


def write_tracer_page(run_root: Path, packet: TracerMaintenancePacket) -> Path:
    page_path = _job_root(run_root, packet.job_id) / "page.md"
    text = [
        f"# {packet.target_page_id}",
        "",
        f"Path: `{packet.target_page_path}`",
        f"Stale reason: `{packet.stale_reason}`",
        "",
        "## Source hashes",
    ]
    for sid, shash in sorted(packet.source_hashes.items()):
        text.append(f"- `{sid}`: `{shash}`")
    _write_json_atomic(
        _job_root(run_root, packet.job_id) / "page_manifest.json",
        {
            "job_id": packet.job_id,
            "target_page_id": packet.target_page_id,
            "target_page_path": packet.target_page_path,
            "stale_reason": packet.stale_reason,
            "source_hashes": packet.source_hashes,
        },
    )
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text("\n".join(text) + "\n", encoding="utf-8")
    return page_path


def update_source_map(run_root: Path, packet: TracerMaintenancePacket) -> Path:
    path = _job_root(run_root, packet.job_id) / "source_map.json"
    payload = {
        "job_id": packet.job_id,
        "page_id": packet.target_page_id,
        "page_path": packet.target_page_path,
        "stale_reason": packet.stale_reason,
        "sources": [{"id": sid, "hash": shash} for sid, shash in sorted(packet.source_hashes.items())],
    }
    _write_json_atomic(path, payload)
    return path


def write_result(run_root: Path, result: TracerMaintenanceResult) -> Path:
    path = _job_root(run_root, result.job_id) / "result.json"
    _write_json_atomic(path, result.to_dict())
    return path


def run_tracer_maintenance_packet(run_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    started_at = utc_now_iso()
    job_id = str(payload.get("job_id") or "unknown")
    append_maintenance_event(run_root, job_id, "started", {"status": "started"})

    try:
        packet = validate_tracer_packet(payload)
        page_path = write_tracer_page(run_root, packet)
        events_path = _job_root(run_root, packet.job_id) / "events.jsonl"
        source_usage_path = write_source_usage(run_root, packet)
        source_map_path = update_source_map(run_root, packet)

        result = TracerMaintenanceResult(
            job_id=packet.job_id,
            status="succeeded",
            started_at=started_at,
            finished_at=utc_now_iso(),
            artifacts={
                "page": str(page_path),
                "events": str(events_path),
                "source_usage": str(source_usage_path),
                "source_map": str(source_map_path),
            },
            error=None,
        )
        result_path = write_result(run_root, result)
        append_maintenance_event(run_root, packet.job_id, "succeeded", {"status": "succeeded", "result_path": str(result_path)})
        return result.to_dict()
    except Exception as exc:
        failed = TracerMaintenanceResult(
            job_id=job_id,
            status="failed",
            started_at=started_at,
            finished_at=utc_now_iso(),
            artifacts={
                "events": str(_job_root(run_root, job_id) / "events.jsonl"),
            },
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        write_result(run_root, failed)
        append_maintenance_event(run_root, job_id, "failed", {"status": "failed", "error": failed.error})
        return failed.to_dict()
