from pathlib import Path


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"


def test_retrieval_tab_combines_metrics_and_mcp_readiness() -> None:
    app = APP_SOURCE.read_text(encoding="utf-8")
    start = app.index("with tabs[5]:")
    end = app.index("with tabs[6]:", start)
    retrieval = app[start:end]

    assert 'st.subheader("Retrieval")' in retrieval
    assert "Scrape Analytics Charts" in retrieval
    assert "Index Health" in retrieval
    assert "Chunk quality" in retrieval
    assert "ready_for_retrieval" in retrieval
    assert "MCP readiness" in retrieval
    assert "Server command" in retrieval
    assert "Operator Details" in retrieval
    assert 'st.subheader("Settings")' not in retrieval
