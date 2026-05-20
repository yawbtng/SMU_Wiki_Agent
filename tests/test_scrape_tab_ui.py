from pathlib import Path


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"


def _scrape_tab_source() -> str:
    source = APP_SOURCE.read_text(encoding="utf-8")
    start = source.index("with tabs[3]:")
    end = source.index("if st.session_state.get(\"_show_legacy_cleanup_ui\", False):", start)
    return source[start:end]


def test_scrape_tab_keeps_minimal_realtime_controls() -> None:
    scrape_tab = _scrape_tab_source()

    assert "Start New Scrape" in scrape_tab
    assert "Resume Current Run" in scrape_tab
    assert "All pages and filters" in scrape_tab
    assert "Quick Tavily Retry" not in scrape_tab
    assert "Retry Failed URLs" not in scrape_tab


def test_start_new_scrape_validates_selected_urls_before_persisting_run() -> None:
    scrape_tab = _scrape_tab_source()
    button_start = scrape_tab.index('if c1.button("Start New Scrape", type="primary"):')
    block_end = scrape_tab.index('if c4.button("Pause", disabled=not st.session_state["run_id"]):', button_start)
    start_block = scrape_tab[button_start:block_end]

    assert start_block.index("_rows_to_discovered_urls") < start_block.index('st.session_state["run_id"] = run_id')
    validation_indexes = [
        index
        for marker in ('urlparse(item.url.strip())', '_is_valid_scrape_url')
        if (index := start_block.find(marker)) >= 0
    ]
    assert validation_indexes
    validation_index = min(validation_indexes)
    assert validation_index < start_block.index('st.session_state["run_id"] = run_id')
