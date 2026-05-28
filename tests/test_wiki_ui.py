from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = PROJECT_ROOT / "app.py"
WIKI_MARKDOWN_UI_SOURCE = PROJECT_ROOT / "src" / "scrape_planner" / "wiki_markdown_ui.py"


def _active_tab_block(app: str, tab_index: int) -> str:
    start = app.index(f"if active_tab == WORKFLOW_TABS[{tab_index}]:")
    try:
        end = app.index(f"if active_tab == WORKFLOW_TABS[{tab_index + 1}]:", start)
    except ValueError:
        end = len(app)
    return app[start:end]


def test_wiki_tab_hides_raw_logs_and_paths_by_default() -> None:
    app = APP_SOURCE.read_text(encoding="utf-8")
    wiki = _active_tab_block(app, 4)

    assert 'st.subheader("Wiki")' in wiki
    assert "render_status_band" in wiki
    assert "Live wiki build logs" not in wiki
    assert "max_lines=4" not in wiki
    assert "Operator Details" not in wiki
    assert "Latest wiki report" not in wiki
    assert "Build activity" in wiki
    assert "wiki_build_activity" in wiki
    assert "wiki_agent_activity_autorefresh_tick" in wiki
    assert "_schedule_live_refresh(" in wiki
    assert "wiki_agent_active" in wiki
    assert "Latest builder log" in wiki
    assert "_tail_text(Path(wiki_status[\"log_path\"]), max_lines=8)" in wiki
    assert "tool_execution_update" not in wiki
    assert "tool_output_tail" not in wiki
    assert "Latest assistant message" not in wiki
    assert "Rebuild Wiki" not in wiki
    assert "rebuild_llm_wiki" not in wiki
    assert "Refresh Wiki Status" not in wiki
    assert "refresh_llm_wiki_status" not in wiki
    assert 'wiki_build_launch_notice' in wiki
    assert 'st.rerun()' in wiki
    assert "tmux session:" not in wiki
    assert "Log path:" not in wiki


def test_wiki_build_button_stays_enabled_after_existing_build_when_sources_ready() -> None:
    app = APP_SOURCE.read_text(encoding="utf-8")
    wiki = _active_tab_block(app, 4)

    assert 'build_disabled = not raw_sources_ready' in wiki
    assert 'build_disabled = not raw_sources_ready or int(wiki_status.get("integrated_sources") or 0) > 0' not in wiki
    assert 'launch_wiki_builder(layout.site_root, runner=tmux_runner, resume=False, rebuild=True, runtime=selected_wiki_runtime)' in wiki


def test_wiki_tab_uses_python_runtime_only() -> None:
    app = APP_SOURCE.read_text(encoding="utf-8")
    wiki = _active_tab_block(app, 4)

    assert 'selected_wiki_runtime = "python"' in wiki
    assert "Python deterministic" in wiki
    assert "Wiki builder runtime" in wiki
    assert "agent event streaming" not in wiki
    assert "st.selectbox(" not in wiki
    assert "runtime=selected_wiki_runtime" in wiki
    assert "Rebuild Wiki" not in wiki


def test_wiki_tab_exposes_markdown_browser_and_keeps_json_secondary() -> None:
    app = APP_SOURCE.read_text(encoding="utf-8")
    wiki = _active_tab_block(app, 4)

    assert "Generated Markdown" in wiki
    assert "_list_wiki_markdown_files(layout.wiki_dir)" in wiki
    assert "_read_wiki_markdown(layout, selected_wiki_file)" in wiki
    assert "_parse_markdown_frontmatter(selected_markdown)" in wiki
    assert "Citations:" in wiki
    assert 'with st.expander("Latest wiki report", expanded=False):' not in wiki
    assert 'st.json(wiki_status.get("latest_report") or {})' not in wiki


def test_wiki_markdown_links_are_rewritten_to_app_routes() -> None:
    app = APP_SOURCE.read_text(encoding="utf-8")

    assert '"view": "wiki_file"' in app
    assert "_apply_wiki_file_query_state()" in app
    assert "_rewrite_wiki_markdown_links(" in app
    assert "current_rel_path=selected_wiki_file" in app
    assert "site_id=site_id" in app


def test_wiki_markdown_preview_strips_temp_clipboard_images() -> None:
    app = APP_SOURCE.read_text(encoding="utf-8")
    wiki_helpers = WIKI_MARKDOWN_UI_SOURCE.read_text(encoding="utf-8")
    wiki = _active_tab_block(app, 4)

    assert "def strip_temp_clipboard_images(" in wiki_helpers
    assert "pi-clipboard-" in wiki_helpers
    assert "_strip_temp_clipboard_images(" in wiki
    assert "_strip_markdown_frontmatter(selected_markdown)" in wiki
