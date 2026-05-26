from pathlib import Path


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"


def _discover_tab_source() -> str:
    source = APP_SOURCE.read_text(encoding="utf-8")
    start = source.index("with tabs[1]:")
    end = source.index("with tabs[2]:", start)
    return source[start:end]


def test_refresh_sitemap_updates_summary_rows_before_metrics_render() -> None:
    source = _discover_tab_source()
    refresh_start = source.index('if st.button("Refresh Sitemap URLs"')
    refresh_block = source[refresh_start:source.index('st.session_state["manual_urls"]', refresh_start)]

    assert "Refreshing discovery is additive" in source
    assert "merged = {" in refresh_block
    assert "for row in refreshed_rows:" in refresh_block
    assert 'discovered_rows_for_summary = st.session_state["discovered"]' in refresh_block
