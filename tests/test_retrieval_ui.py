from pathlib import Path


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"


def test_retrieval_tab_combines_metrics_and_mcp_readiness() -> None:
    app = APP_SOURCE.read_text(encoding="utf-8")
    start = app.index("with tabs[5]:")
    end = app.index("with tabs[6]:", start)
    retrieval = app[start:end]

    assert 'st.subheader("Retrieval")' in retrieval
    assert "Scrape Analytics Charts" in retrieval
    assert 'key="retrieval_load_run_metrics"' in retrieval
    assert retrieval.index('key="retrieval_load_run_metrics"') < retrieval.index("Scrape Analytics Charts")
    assert retrieval.index('key="retrieval_load_run_metrics"') < retrieval.index("_load_run_analytics_inputs")
    assert "Index Health" in retrieval
    assert "Chunk quality" in retrieval
    assert "ready_for_retrieval" in retrieval
    assert "from src.scrape_planner.ui_preview_quality import" in app
    assert "build_chunk_quality_summary" in app
    assert (
        'chunk_rows = _read_jsonl_rows(layout.site_root / "sources" / "pdf_ingest" / "pdf_chunks.jsonl")'
        in retrieval
    )
    assert "build_chunk_quality_summary(row for row in chunk_rows if isinstance(row, dict))" in retrieval
    assert '"Blocked"' in retrieval
    assert "Chunk quality is unknown" in retrieval
    assert "Corpus Content Inspector" in retrieval
    assert '"Unknown"' not in retrieval
    assert "MCP readiness" in retrieval
    assert "Server command" in retrieval
    assert "Operator Details" in retrieval
    assert 'st.subheader("Settings")' not in retrieval
