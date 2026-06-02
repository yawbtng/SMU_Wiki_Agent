from __future__ import annotations

from pathlib import Path

from src.scrape_planner.runtime.agent_run_metrics import AgentRunMetricsRepository, build_embedding_metric_event, build_llm_metric_event


def test_rebuild_run_summary_separates_llm_and_embedding_usage(tmp_path: Path) -> None:
    repo = AgentRunMetricsRepository(tmp_path)
    repo.append_event(
        build_llm_metric_event(
            run_id="run-a",
            site_id="example.edu",
            timestamp="2026-05-01T12:00:00Z",
            stage="wiki",
            operation="draft_page",
            provider="openrouter",
            model="model-a",
            prompt_tokens=100,
            completion_tokens=25,
            latency_ms=500,
            cost_usd=0.03,
            cost_source="estimated",
        )
    )
    repo.append_event(
        build_embedding_metric_event(
            run_id="run-a",
            site_id="example.edu",
            timestamp="2026-05-01T12:01:00Z",
            stage="embed",
            operation="embedding_batch",
            provider="deterministic",
            model="hash-v1",
            input_tokens=200,
            document_count=4,
            chunk_count=12,
            vector_count=12,
            reused_vector_count=2,
            skipped_chunk_count=1,
            failed_chunk_count=0,
            duration_ms=3000,
            cost_usd=None,
            cost_source="unknown",
        )
    )

    summary = repo.rebuild_run_summary("example.edu", "run-a", status="completed")

    assert summary["total_model_tokens"] == 325
    assert summary["llm_usage"]["prompt_tokens"] == 100
    assert summary["llm_usage"]["completion_tokens"] == 25
    assert summary["llm_usage"]["total_tokens"] == 125
    assert summary["embedding_usage"]["input_tokens"] == 200
    assert summary["embedding_usage"]["document_count"] == 4
    assert summary["embedding_usage"]["chunk_count"] == 12
    assert summary["embedding_usage"]["vector_count"] == 12
    assert summary["embedding_usage"]["reused_vector_count"] == 2
    assert summary["cost"]["source"] == "partial"
    assert "unknown_cost" in summary["metrics_health"]["warnings"]


def test_rollups_use_standard_windows(tmp_path: Path) -> None:
    repo = AgentRunMetricsRepository(tmp_path)
    rows = [
        ("run-10", "2026-05-19T00:00:00Z", 10),
        ("run-45", "2026-04-14T00:00:00Z", 45),
        ("run-75", "2026-03-15T00:00:00Z", 75),
        ("run-200", "2025-11-11T00:00:00Z", 200),
        ("run-400", "2025-04-25T00:00:00Z", 400),
    ]
    for run_id, timestamp, tokens in rows:
        repo.append_event(
            build_llm_metric_event(
                run_id=run_id,
                site_id="example.edu",
                timestamp=timestamp,
                stage="wiki",
                operation="draft_page",
                provider="openrouter",
                model="model-a",
                prompt_tokens=tokens,
                completion_tokens=0,
                cost_usd=0.01,
                cost_source="reported",
            )
        )
        repo.rebuild_run_summary("example.edu", run_id, status="completed")

    rollups = repo.build_rollups("example.edu", as_of="2026-05-29T00:00:00Z", include_all_time=True)

    assert rollups["30d"]["total_tokens"] == 10
    assert rollups["60d"]["total_tokens"] == 55
    assert rollups["90d"]["total_tokens"] == 130
    assert rollups["365d"]["total_tokens"] == 330
    assert rollups["all_time"]["total_tokens"] == 730


def test_summary_rebuild_marks_unknown_cost_instead_of_zero(tmp_path: Path) -> None:
    repo = AgentRunMetricsRepository(tmp_path)
    repo.append_event(
        {
            "event_id": "evt_missing",
            "run_id": "run-missing",
            "site_id": "example.edu",
            "timestamp": "2026-05-01T12:00:00Z",
            "stage": "cleanup",
            "operation": "cleanup_markdown",
            "provider": "openrouter",
            "model": "model-a",
            "status": "success",
            "event_type": "llm",
            "metrics": {},
        }
    )

    summary = repo.rebuild_run_summary("example.edu", "run-missing", status="completed")

    assert summary["llm_usage"]["total_tokens"] is None
    assert summary["cost"] == {"amount_usd": None, "source": "unknown"}
    assert "missing_llm_tokens" in summary["metrics_health"]["warnings"]
