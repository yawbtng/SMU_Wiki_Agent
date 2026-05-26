from pathlib import Path


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"


def test_embeddings_metrics_and_query_have_separate_top_level_tabs() -> None:
    app = APP_SOURCE.read_text(encoding="utf-8")
    embeddings = app[app.index("with tabs[5]:"):app.index("with tabs[6]:")]
    metrics = app[app.index("with tabs[6]:"):app.index("with tabs[7]:")]
    settings = app[app.index("with tabs[7]:"):]

    assert 'st.subheader("Embeddings")' in embeddings
    assert "Build / Rebuild Embeddings" in embeddings
    assert "build_llm_wiki_index(layout.site_root)" in embeddings
    assert "Raw Docs" in embeddings
    assert "Wiki Docs" in embeddings
    assert "Chunk quality" not in embeddings

    assert 'st.subheader("Metrics")' in metrics
    assert 'key="metrics_load_run_metrics"' in metrics
    assert "_load_run_analytics_inputs" in metrics
    assert "Provider Requests" in metrics
    assert "OpenRouter" in metrics
    assert "Tavily" in metrics
    assert "Ollama" in metrics

    assert 'st.subheader("Settings")' in settings
    assert "Query Wiki Index" not in settings
    assert "MCP connection" not in settings
