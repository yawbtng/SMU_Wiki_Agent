from __future__ import annotations

import json
from pathlib import Path

from src.scrape_planner.runtime.run_persistence import persist_stale_artifacts_and_packet
from src.scrape_planner.tracer_dependencies import (
    build_tracer_maintenance_job_packet,
    evaluate_stale_dependencies,
)


def test_persist_artifacts_and_packet_contract(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_id = "run-001"

    previous = [{"source_id": "src_a", "content_hash": "sha256:old"}]
    current = [{"source_id": "src_a", "content_hash": "sha256:new"}]
    reverse = {"src_a": ["page-2", "page-1"]}

    result = evaluate_stale_dependencies(previous, current, reverse)
    packet = build_tracer_maintenance_job_packet(
        run_id=run_id,
        result=result,
        evidence_rows=[{"source_id": "src_a", "chunk_id": "src_a:1", "path": "docs/a.md"}],
    )

    persisted = persist_stale_artifacts_and_packet(run_root, run_id, result, packet)

    snapshot_path = Path(persisted["stale_snapshot_path"])
    events_path = Path(persisted["stale_events_path"])
    manifest_path = Path(persisted["packet_manifest_path"])

    assert snapshot_path.exists()
    assert events_path.exists()
    assert manifest_path.exists()

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["stale_page_ids"] == ["page-1", "page-2"]
    assert snapshot["transition_count"] == 1

    lines = [line for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["reason"] == "source_hash_changed"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["packet_type"] == "tracer_maintenance"
    assert manifest["run_id"] == run_id
    assert manifest["stale_page_ids"] == ["page-1", "page-2"]
    assert manifest["evidence_status"] == "ok"
    assert manifest["evidence_refs"] == [{"source_id": "src_a", "chunk_id": "src_a:1", "path": "docs/a.md"}]
    assert "snippet" not in json.dumps(manifest)


def test_append_only_jsonl_and_no_packet_when_no_stale(tmp_path: Path) -> None:
    run_root = tmp_path / "run"

    previous = [{"source_id": "src_a", "content_hash": "sha256:1"}]
    current = [{"source_id": "src_a", "content_hash": "sha256:1"}]
    result = evaluate_stale_dependencies(previous, current, {"src_a": ["page-1"]})
    packet = build_tracer_maintenance_job_packet(run_id="run-002", result=result, evidence_rows=[])

    persisted = persist_stale_artifacts_and_packet(run_root, "run-002", result, packet)
    assert persisted["packet_path"] is None

    events_path = Path(persisted["stale_events_path"])
    assert events_path.exists() is False

    changed = evaluate_stale_dependencies(
        [{"source_id": "src_a", "content_hash": "sha256:1"}],
        [{"source_id": "src_a", "content_hash": "sha256:2"}],
        {"src_a": ["page-1"]},
    )
    changed_packet = build_tracer_maintenance_job_packet(run_id="run-003", result=changed, evidence_rows=[])
    persist_stale_artifacts_and_packet(run_root, "run-003", changed, changed_packet)
    persist_stale_artifacts_and_packet(run_root, "run-004", changed, changed_packet)

    lines = (run_root / "stale_dependencies.jsonl").read_text(encoding="utf-8").splitlines()
    assert len([line for line in lines if line.strip()]) == 2
    for line in lines:
        if line.strip():
            parsed = json.loads(line)
            assert parsed["reason"] == "source_hash_changed"


def test_packet_validation_missing_required_fields() -> None:
    result = evaluate_stale_dependencies([], [], {})

    try:
        build_tracer_maintenance_job_packet(run_id="", result=result, evidence_rows=[])
    except ValueError as exc:
        assert "run_id is required" in str(exc)
    else:
        raise AssertionError("expected run_id validation error")

    try:
        build_tracer_maintenance_job_packet(
            run_id="run-005",
            result=result,
            evidence_rows=[{"source_id": "src_a", "path": "docs/a.md"}],
        )
    except ValueError as exc:
        assert "missing required keys" in str(exc)
    else:
        raise AssertionError("expected evidence validation error")
