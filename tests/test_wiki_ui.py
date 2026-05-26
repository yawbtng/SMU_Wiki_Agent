from pathlib import Path


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"


def test_wiki_tab_hides_logs_and_paths_by_default() -> None:
    app = APP_SOURCE.read_text(encoding="utf-8")
    start = app.index("with tabs[4]:")
    end = app.index("with tabs[5]:", start)
    wiki = app[start:end]

    assert 'st.subheader("Wiki")' in wiki
    assert "render_status_band" in wiki
    assert "Live wiki build logs" in wiki
    assert "max_lines=4" in wiki
    assert "expanded=True" in wiki
    assert "Operator Details" in wiki
    assert 'wiki_build_launch_notice' in wiki
    assert 'st.rerun()' in wiki
    assert "tmux session:" not in wiki
    assert "Log path:" not in wiki


def test_wiki_tab_exposes_markdown_browser_and_keeps_json_secondary() -> None:
    app = APP_SOURCE.read_text(encoding="utf-8")
    start = app.index("with tabs[4]:")
    end = app.index("with tabs[5]:", start)
    wiki = app[start:end]

    assert "Generated Markdown" in wiki
    assert "_list_wiki_markdown_files(layout.wiki_dir)" in wiki
    assert "_read_wiki_markdown(layout, selected_wiki_file)" in wiki
    assert "_parse_markdown_frontmatter(selected_markdown)" in wiki
    assert "Citations:" in wiki
    assert 'with st.expander("Latest wiki report", expanded=False):' in wiki
    assert 'st.json(wiki_status.get("latest_report") or {})' in wiki
