from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from src.scrape_planner.source_monitor import (
    SourceObservation,
    classify_observations,
    content_hash_for_text,
    ledger_rows_to_jsonl,
    load_ledger_jsonl,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "source_monitor"


def test_fixture_proof_and_run_artifacts_contract(tmp_path: Path) -> None:
    prior_ledger = load_ledger_jsonl(FIXTURE_ROOT / "prior_ledger.jsonl")
    raw_observations = json.loads((FIXTURE_ROOT / "current_observations.json").read_text(encoding="utf-8"))
    observations = [SourceObservation(**payload) for payload in raw_observations]

    next_rows, diffs, counts = classify_observations(prior_ledger, observations)

    run_root = tmp_path / "run-0001"
    run_root.mkdir(parents=True, exist_ok=True)

    run_json = {
        "run_id": "run-0001",
        "status": "completed",
        "source_counts": counts,
    }
    (run_root / "run.json").write_text(json.dumps(run_json, indent=2), encoding="utf-8")
    (run_root / "events.jsonl").write_text(
        json.dumps({"type": "run_started", "run_id": "run-0001"}) + "\n"
        + json.dumps({"type": "run_completed", "run_id": "run-0001"})
        + "\n",
        encoding="utf-8",
    )
    (run_root / "source_diff.jsonl").write_text(
        "\n".join(json.dumps(asdict(row), sort_keys=True) for row in diffs) + "\n",
        encoding="utf-8",
    )
    (run_root / "source_ledger.jsonl").write_text(
        "\n".join(ledger_rows_to_jsonl(next_rows)) + "\n",
        encoding="utf-8",
    )
    report_lines = [
        "# Build Report",
        "",
        f"- new: {counts.get('new', 0)}",
        f"- changed: {counts.get('changed', 0)}",
        f"- unchanged: {counts.get('unchanged', 0)}",
        f"- failed: {counts.get('failed', 0)}",
        f"- deleted_candidate: {counts.get('deleted_candidate', 0)}",
    ]
    (run_root / "build_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    assert (run_root / "run.json").exists()
    assert (run_root / "events.jsonl").exists()
    assert (run_root / "source_diff.jsonl").exists()
    assert (run_root / "source_ledger.jsonl").exists()
    assert (run_root / "build_report.md").exists()

    unchanged_diff = next(row for row in diffs if row.url == "https://example.com/a")
    assert unchanged_diff.status == "changed"
    assert unchanged_diff.current_hash == content_hash_for_text("same-content-a")

    new_diff = next(row for row in diffs if row.url == "https://example.com/c")
    assert new_diff.status == "redirected"

    missing_diff = next(row for row in diffs if row.url == "https://example.com/b")
    assert missing_diff.status == "deleted_candidate"

    report_text = (run_root / "build_report.md").read_text(encoding="utf-8")
    assert "new: 0" in report_text
    assert "changed: 1" in report_text
    assert "deleted_candidate: 1" in report_text
