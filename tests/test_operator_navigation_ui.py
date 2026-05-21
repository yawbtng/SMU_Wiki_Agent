from __future__ import annotations

from pathlib import Path

from src.scrape_planner.ui_navigation import WORKFLOW_TABS


EXPECTED_OPERATOR_TABS = [
    "Overview",
    "Sources",
    "Runs",
    "Corpus",
    "Wiki",
    "Retrieval",
    "Settings",
]

OLD_WORKFLOW_LABELS = [
    "Workspace",
    "Raw Data Sources",
    "LLM Wiki",
    "Embed + Rerank",
    "MCP Query",
]


def test_operator_navigation_uses_decision_oriented_tabs() -> None:
    source = Path("src/scrape_planner/ui_navigation.py").read_text(encoding="utf-8")

    assert WORKFLOW_TABS == EXPECTED_OPERATOR_TABS
    for label in EXPECTED_OPERATOR_TABS:
        assert f'"{label}"' in source
    for label in OLD_WORKFLOW_LABELS:
        assert f'"{label}"' not in source


def test_settings_is_not_rendered_inside_mcp_query_tab() -> None:
    app_source = Path("app.py").read_text(encoding="utf-8")

    settings_tab_start = app_source.index("with tabs[6]:")
    settings_subheader = app_source.index('st.subheader("Settings")', settings_tab_start)

    assert settings_subheader > settings_tab_start
    assert 'st.subheader("MCP Query")' not in app_source
