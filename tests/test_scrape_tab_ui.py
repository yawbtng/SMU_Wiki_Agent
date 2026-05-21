from pathlib import Path


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"


def _scrape_tab_source() -> str:
    source = APP_SOURCE.read_text(encoding="utf-8")
    start = source.index("with tabs[2]:")
    end = source.index("with tabs[3]:", start)
    return source[start:end]


def test_scrape_tab_keeps_minimal_realtime_controls() -> None:
    scrape_tab = _scrape_tab_source()

    assert "Start New Scrape" in scrape_tab
    assert "Resume" in scrape_tab
    assert "All pages and filters" in scrape_tab
    assert "Quick Tavily Retry" not in scrape_tab
    assert "Retry Failed URLs" not in scrape_tab


def test_start_new_scrape_validates_selected_urls_before_persisting_run() -> None:
    scrape_tab = _scrape_tab_source()
    button_start = scrape_tab.index('if runs_cols[0].button("Start New Scrape", type="primary", key="runs_start_new_scrape"):')
    block_end = scrape_tab.index(
        'if runs_cols[1].button("Resume", disabled=not st.session_state["run_id"], key="runs_resume_scrape"):',
        button_start,
    )
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


def test_resume_block_checks_for_live_runner_thread_before_unpausing() -> None:
    scrape_tab = _scrape_tab_source()
    button_resume = scrape_tab.index(
        'if runs_cols[1].button("Resume", disabled=not st.session_state["run_id"], key="runs_resume_scrape"):'
    )
    block_end = scrape_tab.index(
        'if runs_cols[2].button("Pause", disabled=not st.session_state["run_id"], key="runs_pause_scrape"):',
        button_resume,
    )
    resume_block = scrape_tab[button_resume:block_end]

    assert 'runner.has_live_run(runs_site_id, st.session_state["run_id"])' in resume_block


def test_scrape_tab_marks_stale_running_state_when_no_live_runner_exists() -> None:
    scrape_tab = _scrape_tab_source()

    assert 'runs_status_stale = runs_summary.state in {"running", "pausing", "initializing"} and not runs_has_live_runner' in scrape_tab
    assert 'This run is not actively scraping right now.' not in scrape_tab
    assert "This run is paused in the UI. Resume it to continue from saved progress." in scrape_tab


def test_runs_tab_owns_run_controls_and_sources_does_not() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    sources_start = source.index("with tabs[1]:")
    sources_end = source.index("with tabs[2]:", sources_start)
    sources = source[sources_start:sources_end]
    runs = _scrape_tab_source()

    assert 'st.subheader("Runs")' in runs
    assert "Start New Scrape" in runs
    assert "Resume" in runs
    assert "Pause" in runs
    assert "Cancel" in runs
    assert "Start New Scrape" not in sources
    assert "Pause" not in sources
    assert "Cancel" not in sources
