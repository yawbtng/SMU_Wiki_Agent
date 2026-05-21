from datetime import datetime, timezone

from src.scrape_planner.url_action_insights import build_url_action_dashboard


def test_dashboard_summarizes_core_actions_from_discovery_and_manifest():
    discovered = [
        {"url": "https://www.smu.edu/admission/apply", "lastmod": "2026-05-10T00:00:00Z"},
        {"url": "https://www.smu.edu/archive/old", "lastmod": "2024-01-01T00:00:00Z"},
        {"url": "https://www.smu.edu/registrar/transcripts", "lastmod": "2026-03-10T00:00:00Z"},
        {"url": "https://www.smu.edu/map"},
    ]
    manifest = [
        {
            "url": "https://www.smu.edu/admission/apply",
            "status": "success",
            "text_length": 2400,
            "markdown_path": "/tmp/apply.md",
        },
        {
            "url": "https://www.smu.edu/archive/old",
            "status": "success",
            "text_length": 200,
            "markdown_path": "/tmp/old.md",
        },
        {
            "url": "https://www.smu.edu/registrar/transcripts",
            "status": "failed",
            "failure_reason": "http_error",
            "http_status": 404,
            "text_length": 0,
        },
        {
            "url": "https://www.smu.edu/map",
            "status": "failed",
            "failure_reason": "empty_content",
            "http_status": 200,
            "text_length": 0,
        },
    ]

    dashboard = build_url_action_dashboard(
        discovered,
        manifest,
        now=datetime(2026, 5, 21, tzinfo=timezone.utc),
        sample_limit=2,
    )

    assert dashboard["summary"] == {
        "discovered": 4,
        "scraped": 4,
        "successful": 2,
        "failed": 2,
        "thin_success": 1,
        "markdown_ready": 2,
    }
    assert dashboard["recommended_action"] == "Use 2 successful markdown pages, then repair or exclude 2 failed URLs."
    assert dashboard["failure_queue"][0] == {
        "failure_reason": "empty_content",
        "count": 1,
        "http_statuses": "200",
        "sample_url": "https://www.smu.edu/map",
        "recommended_action": "Retry with browser/JS extraction, then exclude if it is an app shell.",
    }
    assert dashboard["failure_queue"][1]["failure_reason"] == "http_error"
    assert dashboard["failure_queue"][1]["recommended_action"] == "Exclude 404s; retry only 5xx or temporary errors."
    assert dashboard["freshness"] == [
        {"bucket": "0-30 days", "count": 1},
        {"bucket": "31-90 days", "count": 1},
        {"bucket": ">365 days", "count": 1},
        {"bucket": "no lastmod", "count": 1},
    ]
    assert "samples" not in dashboard
