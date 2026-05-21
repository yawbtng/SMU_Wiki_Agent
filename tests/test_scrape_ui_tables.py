import pandas as pd

from src.scrape_planner.scrape_ui_tables import filter_page_rows, page_table_columns


def test_filter_page_rows_filters_status_url_and_latest_only() -> None:
    rows = pd.DataFrame(
        [
            {
                "url": "https://www.smu.edu/a",
                "status": "success",
                "duration_sec": 1.0,
                "updated_at": pd.Timestamp("2026-05-21T10:00:00Z"),
                "status_rank": 2,
            },
            {
                "url": "https://www.smu.edu/b",
                "status": "failed",
                "duration_sec": 12.0,
                "updated_at": pd.Timestamp("2026-05-21T11:00:00Z"),
                "status_rank": 1,
            },
            {
                "url": "https://www.smu.edu/c",
                "status": "failed",
                "duration_sec": 2.0,
                "updated_at": pd.Timestamp("2026-05-21T09:00:00Z"),
                "status_rank": 1,
            },
        ]
    )

    result = filter_page_rows(
        rows,
        selected_statuses=["failed"],
        url_query="smu.edu",
        slow_threshold=10,
        latest_only=True,
        latest_limit=1,
    )

    assert result["url"].tolist() == ["https://www.smu.edu/b"]
    assert result["is_slow"].tolist() == [True]


def test_filter_page_rows_treats_url_query_as_literal_text() -> None:
    rows = pd.DataFrame(
        [
            {
                "url": "https://www.smu.edu/catalog/[archived]",
                "status": "success",
                "duration_sec": 1.0,
                "updated_at": pd.Timestamp("2026-05-21T10:00:00Z"),
                "status_rank": 1,
            },
            {
                "url": "https://www.smu.edu/catalog/current",
                "status": "success",
                "duration_sec": 1.0,
                "updated_at": pd.Timestamp("2026-05-21T09:00:00Z"),
                "status_rank": 1,
            },
        ]
    )

    result = filter_page_rows(
        rows,
        selected_statuses=["success"],
        url_query="[",
        slow_threshold=10,
        latest_only=False,
    )

    assert result["url"].tolist() == ["https://www.smu.edu/catalog/[archived]"]


def test_page_table_columns_returns_existing_columns_in_display_order() -> None:
    df = pd.DataFrame(
        [
            {
                "status": "success",
                "url": "https://www.smu.edu/a",
                "worker_id": "worker-1",
                "ignored": "x",
            }
        ]
    )

    assert page_table_columns(df) == ["status", "url", "worker_id"]
