from __future__ import annotations

from src.scrape_planner.workspace_state import resolve_active_workspace_id


def test_resolve_active_workspace_id_keeps_current_selection() -> None:
    assert (
        resolve_active_workspace_id(
            current_active_workspace_id="www.smu.edu",
            loaded_active_workspace_id="",
        )
        == "www.smu.edu"
    )


def test_resolve_active_workspace_id_uses_loaded_selection_when_current_missing() -> None:
    assert (
        resolve_active_workspace_id(
            current_active_workspace_id="",
            loaded_active_workspace_id="www.smu.edu",
        )
        == "www.smu.edu"
    )


def test_resolve_active_workspace_id_allows_workspace_list_mode() -> None:
    assert (
        resolve_active_workspace_id(
            current_active_workspace_id="",
            loaded_active_workspace_id="",
        )
        == ""
    )
