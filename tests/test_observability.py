from pathlib import Path

from src.scrape_planner.observability import append_event, load_events, summarize_events


def test_append_and_load_events(tmp_path: Path):
    run_root = tmp_path / "run"
    append_event(run_root, {"provider": "openai", "status": "ok", "latency_ms": 120})
    append_event(run_root, {"provider": "anthropic", "status": "error", "latency_ms": 300})

    events = load_events(run_root)
    assert len(events) == 2
    assert events[0]["provider"] == "openai"
    assert "ts" in events[0]
    assert events[1]["provider"] == "anthropic"


def test_summarize_events_counts_and_latency():
    summary = summarize_events(
        [
            {"provider": "openai", "status": "ok", "latency_ms": 100},
            {"provider": "openai", "status": "ok", "latency_ms": 300},
            {"provider": "anthropic", "status": "error", "latency_ms": 200},
            {"status": "ok"},
        ]
    )
    assert summary["total_calls"] == 4
    assert summary["by_provider"] == {"openai": 2, "anthropic": 1, "unknown": 1}
    assert summary["by_status"] == {"ok": 3, "error": 1}
    assert summary["avg_latency_ms"] == 200.0
