from __future__ import annotations


def resolve_active_workspace_id(
    *,
    current_active_workspace_id: str,
    loaded_active_workspace_id: str,
) -> str:
    """Preserve explicit workspace-list mode instead of auto-opening a single workspace."""

    current = str(current_active_workspace_id or "").strip()
    if current:
        return current
    return str(loaded_active_workspace_id or "").strip()
