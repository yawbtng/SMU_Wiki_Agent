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
    assert "expanded=False" in wiki
    assert "Operator Details" in wiki
    assert "tmux session:" not in wiki
    assert "Log path:" not in wiki
