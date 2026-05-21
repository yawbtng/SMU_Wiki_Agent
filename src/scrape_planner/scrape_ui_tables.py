from __future__ import annotations

import pandas as pd


PAGE_TABLE_COLUMN_ORDER = [
    "status",
    "url",
    "worker_id",
    "fetch_mode",
    "http_status",
    "failure_reason",
    "attempt",
    "duration_sec",
    "is_slow",
    "updated_at_str",
]


def filter_page_rows(
    pages_df: pd.DataFrame,
    *,
    selected_statuses: list[str],
    url_query: str,
    slow_threshold: float,
    latest_only: bool,
    latest_limit: int = 250,
) -> pd.DataFrame:
    visible_df = pages_df.copy()
    if selected_statuses:
        visible_df = visible_df[visible_df["status"].isin(selected_statuses)]
    if url_query.strip():
        visible_df = visible_df[
            visible_df["url"]
            .astype(str)
            .str.contains(url_query.strip(), case=False, na=False, regex=False)
        ]
    visible_df["is_slow"] = visible_df["duration_sec"] >= float(slow_threshold)
    if latest_only:
        return visible_df.sort_values(
            ["status_rank", "updated_at"],
            ascending=[True, False],
            na_position="last",
        ).head(latest_limit)
    return visible_df.sort_values(
        ["status_rank", "updated_at", "url"],
        ascending=[True, False, True],
        na_position="last",
    )


def page_table_columns(df: pd.DataFrame) -> list[str]:
    return [column for column in PAGE_TABLE_COLUMN_ORDER if column in df.columns]
