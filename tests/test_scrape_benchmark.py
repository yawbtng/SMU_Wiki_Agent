from src.scrape_planner.scrape_benchmark import (
    build_report,
    quality_score,
    summarize_mode_results,
)


def test_quality_score_prefers_richer_successful_content() -> None:
    thin = quality_score(failure_reason=None, text_length=200, markdown_chars=250, link_density=0.12)
    rich = quality_score(failure_reason=None, text_length=2400, markdown_chars=3200, link_density=0.04)
    failed = quality_score(failure_reason="http_error", text_length=0, markdown_chars=0, link_density=0.0)

    assert rich > thin
    assert failed == 0.0


def test_summarize_mode_results_aggregates_speed_quality_and_failures() -> None:
    summary = summarize_mode_results(
        mode="fetcher",
        rows=[
            {
                "url": "https://example.com/a",
                "elapsed_sec": 0.5,
                "failure_reason": None,
                "text_length": 1200,
                "markdown_chars": 1500,
                "quality_score": 78.0,
            },
            {
                "url": "https://example.com/b",
                "elapsed_sec": 1.0,
                "failure_reason": "blocked",
                "text_length": 0,
                "markdown_chars": 0,
                "quality_score": 0.0,
            },
        ],
    )

    assert summary["mode"] == "fetcher"
    assert summary["sample_count"] == 2
    assert summary["success_count"] == 1
    assert summary["failure_count"] == 1
    assert summary["success_rate"] == 0.5
    assert summary["avg_quality_success"] == 78.0
    assert summary["failure_breakdown"] == {"blocked": 1}


def test_build_report_ranks_available_modes_before_skipped_modes() -> None:
    report = build_report(
        benchmark_name="smu",
        sample_urls=["https://example.com/a"],
        summaries=[
            {
                "mode": "lightpanda",
                "available": False,
                "reason": "missing cdp",
            },
            {
                "mode": "fetcher",
                "available": True,
                "sample_count": 1,
                "success_count": 1,
                "failure_count": 0,
                "success_rate": 1.0,
                "avg_elapsed_sec": 0.4,
                "pages_per_min": 150.0,
                "avg_quality_success": 81.0,
                "median_text_length_success": 1800,
                "median_markdown_chars_success": 2200,
                "failure_breakdown": {},
            },
        ],
    )

    assert report["winner"]["mode"] == "fetcher"
    assert report["winner"]["success_rate"] == 1.0


def test_mode_availability_marks_plain_agent_browser_available() -> None:
    from src.scrape_planner.scrape_benchmark import mode_availability

    available, reason = mode_availability("agent_browser")

    assert available is True
    assert reason == ""
