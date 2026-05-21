from __future__ import annotations

from pathlib import Path


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"


def test_scraped_page_preview_route_has_real_content_contract() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "view" in source
    assert "scraped_page" in source
    assert "page_slug" in source
    assert "Back to Runs" in source or "Back to Corpus" in source or "st.page_link" in source
    assert 'st.button("Back to Runs")' in source
    assert "st.query_params.clear()" in source
    assert "Source URL" in source
    assert "Extracted content" in source or "Markdown preview" in source
    assert "Scraped page preview" in source


def test_preview_route_has_useful_not_found_operator_details() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "render_operator_details(" in source
    assert '"Operator Details"' in source
    assert "Expected markdown path" in source


def test_preview_links_are_not_rendered_as_repetitive_raw_rows() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "Content Inspector" in source
    assert source.count("Open preview") <= 2
    assert "Recently scraped" in source
    assert '"Preview URL": href' in source
    assert 'st.column_config.LinkColumn("Preview", display_text="Preview")' in source
    assert "column_config={" in source
    assert '"Preview URL": st.column_config.LinkColumn' in source
    assert '"Preview action"' not in source


def test_recently_scraped_preview_list_has_compact_fields() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "recent_preview_rows" in source
    assert "Title" in source
    assert "Status" in source
    assert "Source URL" in source
    assert "Scraped timestamp" in source
    assert "Preview URL" in source


def test_preview_route_shows_visible_metadata_summary_before_operator_details() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    preview_route_start = source.index("def _render_scraped_page_preview()")
    visible_summary_index = source.index('st.markdown("#### Metadata summary")', preview_route_start)
    ready_operator_details_index = source.index('"Preview route": "view=scraped_page"', preview_route_start)

    assert visible_summary_index < ready_operator_details_index
    assert "metadata_summary_rows" in source
    assert 'st.dataframe(pd.DataFrame(metadata_summary_rows)' in source
    assert '"Metric": "HTTP status"' in source
    assert '"Metric": "Fetch mode"' in source
    assert '"Metric": "Text length"' in source


def test_preview_route_stops_before_normal_tabs() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    route_call_index = source.index("\n_render_scraped_page_preview()")
    init_state_index = source.index("_init_state()", route_call_index)
    preview_route_source = source[source.index("def _render_scraped_page_preview()"):route_call_index]

    assert route_call_index < init_state_index
    assert "st.stop()" in preview_route_source
