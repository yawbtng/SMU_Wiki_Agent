from src.scrape_planner.app.navigation import WORKFLOW_TABS


def test_workflow_tabs_match_operator_ui() -> None:
    assert WORKFLOW_TABS == [
        "Overview",
        "Sources",
        "Runs",
        "Documents",
        "Wiki",
        "Embeddings",
        "Metrics",
        "Settings",
    ]
