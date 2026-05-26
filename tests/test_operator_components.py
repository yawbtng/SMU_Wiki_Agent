from __future__ import annotations

from pathlib import Path


def test_operator_component_helpers_are_defined() -> None:
    source = Path("src/scrape_planner/ui_operator_components.py").read_text()

    assert "def render_status_band(" in source
    assert "def render_metric_strip(" in source
    assert "def render_operator_details(" in source
    assert "def status_badge_html(" in source
    assert "operator-metric-card" in source
    assert "Operator Details" in source


def test_operator_styles_are_high_contrast_text_first_ui() -> None:
    component_source = Path("src/scrape_planner/ui_operator_components.py").read_text()
    app_source = Path("app.py").read_text()

    assert "COMMAND CENTER //" in component_source
    assert "operator-metric-sigil" in component_source
    assert "operator-metric-value" in app_source
    assert "#fffaf0" in app_source
    assert "-webkit-text-fill-color" in app_source
    assert "text-shadow" in app_source
