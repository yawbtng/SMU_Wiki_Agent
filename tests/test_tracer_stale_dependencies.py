from __future__ import annotations

from src.scrape_planner.tracer_dependencies import (
    STALE_REASON_SOURCE_HASH_CHANGED,
    build_tracer_maintenance_job_packet,
    evaluate_stale_dependencies,
    normalize_reverse_dependency_map,
)


def test_unchanged_hashes_return_no_stale_pages() -> None:
    previous = [{"source_id": "src_a", "content_hash": "sha256:1"}]
    current = [{"source_id": "src_a", "content_hash": "sha256:1"}]
    reverse = {"src_a": ["page-1"]}

    result = evaluate_stale_dependencies(previous, current, reverse)

    assert result.errors == []
    assert result.stale_page_ids == []
    assert result.transitions == []


def test_single_hash_change_marks_dependent_pages_stale() -> None:
    previous = [{"source_id": "src_a", "content_hash": "sha256:old"}]
    current = [{"source_id": "src_a", "content_hash": "sha256:new"}]
    reverse = {"src_a": ["page-2", "page-1", "page-2"]}

    result = evaluate_stale_dependencies(previous, current, reverse)

    assert result.errors == []
    assert result.stale_page_ids == ["page-1", "page-2"]
    assert len(result.transitions) == 1
    transition = result.transitions[0]
    assert transition.source_id == "src_a"
    assert transition.old_hash == "sha256:old"
    assert transition.new_hash == "sha256:new"
    assert transition.affected_pages == ["page-1", "page-2"]
    assert transition.reason == STALE_REASON_SOURCE_HASH_CHANGED


def test_multiple_sources_to_same_page_are_deduped_and_ordered() -> None:
    previous = [
        {"source_id": "src_a", "content_hash": "sha256:1"},
        {"source_id": "src_b", "content_hash": "sha256:2"},
    ]
    current = [
        {"source_id": "src_b", "content_hash": "sha256:22"},
        {"source_id": "src_a", "content_hash": "sha256:11"},
    ]
    reverse = {
        "src_a": ["page-2", "page-1"],
        "src_b": ["page-1", "page-3"],
    }

    result = evaluate_stale_dependencies(previous, current, reverse)

    assert result.errors == []
    assert [t.source_id for t in result.transitions] == ["src_a", "src_b"]
    assert result.stale_page_ids == ["page-1", "page-2", "page-3"]


def test_changed_source_missing_from_reverse_map_is_safe() -> None:
    previous = [{"source_id": "src_x", "content_hash": "sha256:old"}]
    current = [{"source_id": "src_x", "content_hash": "sha256:new"}]

    result = evaluate_stale_dependencies(previous, current, {})

    assert result.errors == []
    assert result.stale_page_ids == []
    assert len(result.transitions) == 1
    assert result.transitions[0].affected_pages == []


def test_malformed_reverse_map_is_rejected() -> None:
    result = evaluate_stale_dependencies([], [], {"src_a": "not-a-list"})

    assert result.stale_page_ids == []
    assert result.transitions == []
    assert len(result.errors) == 1
    assert result.errors[0].code == "invalid_reverse_dependency_map"


def test_malformed_source_hash_entries_are_reported() -> None:
    previous = [{"content_hash": "sha256:old"}, {"source_id": "src_a", "content_hash": None}]
    current = [{"source_id": "src_a", "content_hash": "sha256:new"}]

    result = evaluate_stale_dependencies(previous, current, {"src_a": ["page-1"]})

    assert len(result.errors) == 2
    assert all(err.code == "invalid_source_hash_entry" for err in result.errors)


def test_job_packet_contract_shape() -> None:
    previous = [{"source_id": "src_a", "content_hash": "sha256:old"}]
    current = [{"source_id": "src_a", "content_hash": "sha256:new"}]
    reverse = {"src_a": ["page-1"]}

    result = evaluate_stale_dependencies(previous, current, reverse)
    packet = build_tracer_maintenance_job_packet(result)

    assert packet.packet_type == "tracer_maintenance"
    assert packet.stale_page_ids == ["page-1"]
    assert len(packet.transitions) == 1


def test_normalize_reverse_map_dedupes_and_sorts_values() -> None:
    normalized = normalize_reverse_dependency_map({"src_a": [" page-2 ", "page-1", "page-1", ""]})
    assert normalized == {"src_a": ["page-1", "page-2"]}
