from __future__ import annotations

from pathlib import Path


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"


def test_scraped_page_preview_route_has_real_content_contract() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "view" in source
    assert "scraped_page" in source
    assert "page_slug" in source
    assert "Back to Runs" in source or "Back to Corpus" in source or "st.page_link" in source
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


def test_recently_scraped_preview_list_has_compact_fields() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "recent_preview_rows" in source
    assert "Title" in source
    assert "Status" in source
    assert "Source URL" in source
    assert "Scraped timestamp" in source
    assert "Preview action" in source
