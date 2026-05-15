from __future__ import annotations

from dataclasses import dataclass
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
class TracerMaintenanceJobPacket:
    packet_type: Literal["tracer_maintenance"]
    stale_page_ids: list[str]
    transitions: list[StaleTransitionRecord]


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


def build_tracer_maintenance_job_packet(result: StaleEvaluationResult) -> TracerMaintenanceJobPacket:
    return TracerMaintenanceJobPacket(
        packet_type="tracer_maintenance",
        stale_page_ids=result.stale_page_ids,
        transitions=result.transitions,
    )
