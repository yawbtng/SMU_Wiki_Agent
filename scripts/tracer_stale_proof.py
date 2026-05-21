from __future__ import annotations

import json
from pathlib import Path

from src.scrape_planner.run_persistence import persist_stale_artifacts_and_packet
from src.scrape_planner.tracer_dependencies import build_tracer_maintenance_job_packet, evaluate_stale_dependencies


def run_proof(run_root: Path) -> dict[str, object]:
    run_id = "proof-run"
    previous = [{"source_id": "src_demo", "content_hash": "sha256:old"}]
    current = [{"source_id": "src_demo", "content_hash": "sha256:new"}]
    reverse = {"src_demo": ["page-demo"]}

    result = evaluate_stale_dependencies(previous, current, reverse)
    packet = build_tracer_maintenance_job_packet(
        run_id=run_id,
        result=result,
        evidence_rows=[{"source_id": "src_demo", "chunk_id": "src_demo:1", "path": "docs/demo.md"}],
    )
    persisted = persist_stale_artifacts_and_packet(run_root, run_id, result, packet)

    return {
        "stale_count": persisted["stale_count"],
        "transition_count": persisted["transition_count"],
        "packet_path": persisted["packet_path"],
        "packet_manifest_path": persisted["packet_manifest_path"],
    }


if __name__ == "__main__":
    root = Path(".tmp/tracer-proof")
    root.mkdir(parents=True, exist_ok=True)
    output = run_proof(root)
    print(json.dumps(output, indent=2))
