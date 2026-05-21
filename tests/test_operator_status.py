from __future__ import annotations

from src.scrape_planner.ui_operator_status import (
    build_operator_run_status,
    build_operator_source_status,
)


def test_stale_running_status_becomes_paused_when_no_live_runner_exists() -> None:
    status = build_operator_run_status(
        state="running",
        done=18725,
        total=25376,
        running=0,
        failed=1341,
        queued=6651,
        has_live_runner=False,
    )

    assert status.state == "paused"
    assert status.state_label == "Paused"
    assert status.primary_action == "Resume run"
    assert status.attention_level == "warning"
    assert status.message == "This run is paused in the UI. Resume it to continue from saved progress."
    assert "not actively scraping" not in status.message


def test_active_running_status_stays_running_when_live_runner_exists() -> None:
    status = build_operator_run_status(
        state="running",
        done=18725,
        total=25376,
        running=4,
        failed=1341,
        queued=6651,
        has_live_runner=True,
    )

    assert status.state == "running"
    assert status.state_label == "Running"
    assert status.primary_action == "Monitor run"
    assert status.attention_level == "active"


def test_live_initializing_status_reports_startup_in_progress() -> None:
    status = build_operator_run_status(
        state="initializing",
        done=0,
        total=25376,
        running=0,
        failed=0,
        queued=25376,
        has_live_runner=True,
    )

    assert status.state == "initializing"
    assert status.state_label == "Initializing"
    assert status.attention_level == "active"
    assert status.primary_action in {"Monitor run", "Monitor startup"}
    assert status.primary_action != "Start run"
    assert any(term in status.message.lower() for term in ("workers", "startup", "preparing"))


def test_live_pausing_status_reports_pause_in_progress() -> None:
    status = build_operator_run_status(
        state="pausing",
        done=18725,
        total=25376,
        running=2,
        failed=1341,
        queued=6651,
        has_live_runner=True,
    )

    assert status.state == "pausing"
    assert status.state_label == "Pausing"
    assert status.attention_level in {"warning", "active"}
    assert status.primary_action == "Monitor run"
    assert status.primary_action != "Start run"
    assert "pause" in status.message.lower()


def test_pdf_extraction_counts_promote_real_progress_even_without_registry() -> None:
    status = build_operator_source_status(
        selected_url_count=25379,
        pdf_count=1,
        raw_source_count=0,
        raw_ready_count=0,
        raw_failed_count=0,
        raw_review_count=0,
        pdf_page_count=1165,
        pdf_chunk_count=3752,
    )

    assert status.readiness == "partially prepared"
    assert status.primary_count == 25379
    assert status.pdf_detail == "1 PDF, 1,165 pages, 3,752 chunks"
    assert status.message == "PDF extraction is ready; raw source normalization is still pending."
