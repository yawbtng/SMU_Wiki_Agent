from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal


STALE_REASON_SOURCE_HASH_CHANGED: Literal["source_hash_changed"] = "source_hash_changed"


@dataclass(frozen=True)
class SourceHashState:
    source_id: str
    content_hash: str


@dataclass(frozen=True)
class StaleTransitionRecord:
    source_id: str
    old_hash: str
    new_hash: str
    affected_pages: list[str]
    reason: Literal["source_hash_changed"]


@dataclass(frozen=True)
class TracerMaintenanceEvidenceRef:
    source_id: str
    chunk_id: str
    path: str


@dataclass(frozen=True)
class TracerMaintenanceTarget:
    page_id: str
    reasons: list[Literal["source_hash_changed"]]
    source_ids: list[str]


@dataclass(frozen=True)
class TracerMaintenanceJobPacket:
    packet_type: Literal["tracer_maintenance"]
    run_id: str
    stale_page_ids: list[str]
    transitions: list[StaleTransitionRecord]
    evidence_status: Literal["ok", "missing"]
    evidence_refs: list[TracerMaintenanceEvidenceRef]
    targets: list[TracerMaintenanceTarget]
    instructions: dict[str, Any]
    expected_outputs: list[str]


@dataclass(frozen=True)
class EvaluatorError:
    code: Literal["invalid_source_hash_entry", "invalid_reverse_dependency_map"]
    detail: str


@dataclass(frozen=True)
class StaleEvaluationResult:
    stale_page_ids: list[str]
    transitions: list[StaleTransitionRecord]
    errors: list[EvaluatorError]


def normalize_reverse_dependency_map(reverse_dependency_map: dict[str, Any]) -> dict[str, list[str]]:
    if not isinstance(reverse_dependency_map, dict):
        raise ValueError("reverse dependency map must be a dict keyed by source_id")

    normalized: dict[str, list[str]] = {}
    for source_id, page_ids in reverse_dependency_map.items():
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("reverse dependency map contains invalid source_id key")
        if not isinstance(page_ids, list):
            raise ValueError(f"reverse dependency for source '{source_id}' must be a list")

        deduped = sorted({str(page_id).strip() for page_id in page_ids if str(page_id).strip()})
        normalized[source_id] = deduped

    return normalized


def _normalize_source_hash_entries(entries: list[dict[str, Any]], which: str) -> tuple[dict[str, str], list[EvaluatorError]]:
    normalized: dict[str, str] = {}
    errors: list[EvaluatorError] = []

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(
                EvaluatorError(
                    code="invalid_source_hash_entry",
                    detail=f"{which}[{idx}] must be an object with source_id/content_hash",
                )
            )
            continue

        source_id = entry.get("source_id")
        content_hash = entry.get("content_hash")

        if not isinstance(source_id, str) or not source_id.strip():
            errors.append(
                EvaluatorError(
                    code="invalid_source_hash_entry",
                    detail=f"{which}[{idx}] missing required key 'source_id'",
                )
            )
            continue
        if not isinstance(content_hash, str) or not content_hash.strip():
            errors.append(
                EvaluatorError(
                    code="invalid_source_hash_entry",
                    detail=f"{which}[{idx}] missing required key 'content_hash'",
                )
            )
            continue

        normalized[source_id] = content_hash

    return normalized, errors


def evaluate_stale_dependencies(
    previous_source_hashes: list[dict[str, Any]],
    current_source_hashes: list[dict[str, Any]],
    reverse_dependency_map: dict[str, Any],
) -> StaleEvaluationResult:
    try:
        normalized_reverse_map = normalize_reverse_dependency_map(reverse_dependency_map)
    except ValueError as exc:
        return StaleEvaluationResult(
            stale_page_ids=[],
            transitions=[],
            errors=[EvaluatorError(code="invalid_reverse_dependency_map", detail=str(exc))],
        )

    previous_map, previous_errors = _normalize_source_hash_entries(previous_source_hashes, "previous_source_hashes")
    current_map, current_errors = _normalize_source_hash_entries(current_source_hashes, "current_source_hashes")

    errors = [*previous_errors, *current_errors]

    transitions: list[StaleTransitionRecord] = []
    stale_pages: set[str] = set()

    for source_id in sorted(current_map.keys()):
        old_hash = previous_map.get(source_id)
        new_hash = current_map[source_id]
        if old_hash is None or old_hash == new_hash:
            continue

        affected_pages = normalized_reverse_map.get(source_id, [])
        stale_pages.update(affected_pages)
        transitions.append(
            StaleTransitionRecord(
                source_id=source_id,
                old_hash=old_hash,
                new_hash=new_hash,
                affected_pages=affected_pages,
                reason=STALE_REASON_SOURCE_HASH_CHANGED,
            )
        )

    return StaleEvaluationResult(
        stale_page_ids=sorted(stale_pages),
        transitions=transitions,
        errors=errors,
    )


def build_tracer_maintenance_job_packet(
    run_id: str,
    result: StaleEvaluationResult,
    evidence_rows: list[dict[str, Any]] | None = None,
) -> TracerMaintenanceJobPacket:
    if not run_id.strip():
        raise ValueError("run_id is required")

    target_map: dict[str, set[str]] = {page_id: set() for page_id in result.stale_page_ids}
    for transition in result.transitions:
        for page_id in transition.affected_pages:
            if page_id in target_map:
                target_map[page_id].add(transition.source_id)

    targets = [
        TracerMaintenanceTarget(
            page_id=page_id,
            reasons=[STALE_REASON_SOURCE_HASH_CHANGED],
            source_ids=sorted(target_map.get(page_id, set())),
        )
        for page_id in result.stale_page_ids
    ]

    evidence_refs: list[TracerMaintenanceEvidenceRef] = []
    if evidence_rows:
        for idx, row in enumerate(evidence_rows):
            source_id = str(row.get("source_id") or "").strip()
            chunk_id = str(row.get("chunk_id") or "").strip()
            path = str(row.get("path") or "").strip()
            if not source_id or not chunk_id or not path:
                raise ValueError(f"evidence_rows[{idx}] missing required keys: source_id, chunk_id, path")
            evidence_refs.append(TracerMaintenanceEvidenceRef(source_id=source_id, chunk_id=chunk_id, path=path))

    return TracerMaintenanceJobPacket(
        packet_type="tracer_maintenance",
        run_id=run_id,
        stale_page_ids=result.stale_page_ids,
        transitions=result.transitions,
        evidence_status="ok" if evidence_refs else "missing",
        evidence_refs=evidence_refs,
        targets=targets,
        instructions={
            "executor": "agent_or_skill",
            "action": "refresh_tracer_pages",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        expected_outputs=[
            "tracer_pages_refreshed",
            "source_hashes_synced",
            "run_summary_written",
        ],
    )


def serialize_job_packet(packet: TracerMaintenanceJobPacket) -> dict[str, Any]:
    return asdict(packet)
