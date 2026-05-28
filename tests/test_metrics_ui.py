from pathlib import Path


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"


def _metrics_tab_source() -> str:
    source = APP_SOURCE.read_text(encoding="utf-8")
    start = source.index("if active_tab == WORKFLOW_TABS[6]:")
    end = source.index("if active_tab == WORKFLOW_TABS[7]:", start)
    return source[start:end]


def test_metrics_tab_has_to_date_period_filters_and_per_run_table() -> None:
    source = _metrics_tab_source()

    assert 'st.markdown("### Metrics To Date")' in source
    assert '"Last 7 days"' in source
    assert '"Last 30 days"' in source
    assert '"Last 3 months"' in source
    assert '"Last 6 months"' in source
    assert '"Last year"' in source
    assert '"All time"' in source
    assert "Per-run metrics in the selected date range" in source
    assert "_build_run_metrics_row(" in source


def test_run_analytics_inputs_read_jsonl_via_persistence_helpers() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    start = source.index("def _load_run_analytics_inputs")
    end = source.index("def _fmt_compact_number", start)
    helper = source[start:end]

    assert "read_page_states(run_root)" in helper
    assert "read_run_status(run_root)" in helper
    assert "read_run_events(run_root)" in helper
    assert 'read_json(run_root / "pages.jsonl"' not in helper
    assert 'read_json(run_root / "events.jsonl"' not in helper
