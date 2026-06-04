from __future__ import annotations

from pathlib import Path

from src.scrape_planner.webapp.embeddings import (
    append_embedding_log,
    embedding_job_status_payload,
    read_embedding_log_tail,
    run_embedding_job,
    start_embedding_job_state,
)


def test_read_embedding_log_tail_returns_recent_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "job.log"
    log_path.write_text("line1\nline2\nline3\n", encoding="utf-8")
    assert read_embedding_log_tail(log_path, lines=2) == ["line2", "line3"]


def test_embedding_job_status_payload_includes_log_tail(tmp_path: Path) -> None:
    site = tmp_path / "sites" / "demo.edu"
    indexes = site / "indexes" / "reports"
    indexes.mkdir(parents=True)
    state = start_embedding_job_state(site, "demo.edu", trigger="manual", changed_document_count=3, status="running")
    append_embedding_log(Path(state["log_path"]), "Scanning raw sources and wiki pages…")
    payload = embedding_job_status_payload("demo.edu", site)
    assert payload["phase"] == "building_index"
    assert "Scanning raw sources" in "\n".join(payload["log_tail"])


def test_run_embedding_job_persists_progress_eta_and_cost(tmp_path: Path) -> None:
    site = tmp_path / "sites" / "demo.edu"
    (site / "indexes").mkdir(parents=True)
    start_embedding_job_state(site, "demo.edu", trigger="manual", changed_document_count=2, status="queued")

    def fake_build_index(root: Path, *, progress_callback) -> dict[str, object]:
        progress_callback(
            {
                "stage": "embedding_plan",
                "total_changed_document_count": 2,
                "total_document_count": 2,
                "skipped_document_count": 0,
                "batch_size": 2,
                "batch_count": 1,
                "estimated_input_tokens": 1200,
                "estimated_embedding_cost_usd": 0.000024,
                "embedding_model": "openai/text-embedding-3-small",
            }
        )
        progress_callback(
            {
                "stage": "embedding_batch",
                "total_changed_document_count": 2,
                "embedded_document_count": 2,
                "batch_index": 1,
                "batch_count": 1,
                "estimated_seconds_remaining": 0,
                "estimated_input_tokens": 1200,
                "estimated_embedding_cost_usd": 0.000024,
                "embedding_model": "openai/text-embedding-3-small",
            }
        )
        report_path = root / "indexes" / "reports" / "fake-report.json"
        return {
            "status": "ready",
            "report_path": str(report_path),
            "wiki_index_count": 1,
            "raw_index_count": 1,
            "changed_document_count": 2,
            "embedding": {"provider": "openrouter", "model": "openai/text-embedding-3-small", "vector_dimensions": 1536},
        }

    result = run_embedding_job(site, "demo.edu", trigger="manual", build_index=fake_build_index)
    payload = embedding_job_status_payload("demo.edu", site)

    assert result["status"] == "complete"
    assert payload["progress"]["stage"] == "embedding_batch"
    assert payload["progress"]["percent_complete"] == 100
    assert payload["progress"]["estimated_embedding_cost_usd"] == 0.000024
    log = "\n".join(payload["log_tail"])
    assert "Embedding plan:" in log
    assert "ETA 0s" in log
    assert "estimated cost $0.0000" in log
