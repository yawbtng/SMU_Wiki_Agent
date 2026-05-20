from pathlib import Path


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"


def test_back_to_workspaces_is_not_overridden_by_single_workspace_auto_open() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert 'if top2.button("Back to Workspaces"):' in source
    assert 'len(st.session_state.get("workspaces", [])) == 1' not in source
