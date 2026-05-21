from __future__ import annotations

from pathlib import Path


def test_operator_component_helpers_are_defined() -> None:
    source = Path("src/scrape_planner/ui_operator_components.py").read_text()

    assert "def render_status_band(" in source
    assert "def render_metric_strip(" in source
    assert "def render_operator_details(" in source
    assert "def status_badge_html(" in source
    assert "border-radius: 8px" in source
    assert "Operator Details" in source


def test_operator_styles_are_restrained_dashboard_ui() -> None:
    source = Path("src/scrape_planner/ui_operator_components.py").read_text()

    assert "border-radius: 8px" in source
    assert "font-weight:750" in source or "font-weight: 750" in source
    assert "#0f172a" in source
    assert "gradient" not in source.lower()
    assert "border-radius: 24px" not in source
