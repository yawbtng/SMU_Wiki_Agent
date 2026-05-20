from __future__ import annotations

from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
NAV_PATH = Path(__file__).resolve().parents[1] / "src" / "scrape_planner" / "ui_navigation.py"


def _choose_tab_source() -> str:
    text = APP_PATH.read_text(encoding="utf-8")
    start = text.index("with tabs[2]:")
    end = text.index("with tabs[3]:", start)
    return text[start:end]


def test_choose_tab_is_pdf_sources_not_url_selection() -> None:
    app_source = APP_PATH.read_text(encoding="utf-8")
    source = _choose_tab_source()
    navigation_source = NAV_PATH.read_text(encoding="utf-8")

    assert '"PDF Sources"' in navigation_source
    assert '"Choose URLs"' not in navigation_source
    assert "Choose URLs" not in app_source
    assert "Run LLM Choose URLs" not in app_source
    assert 'st.subheader("PDF Sources")' in source
    assert "Add PDFs for embedding" in source
    assert "Ready for Docling parsing and Zvec embedding." in source

    removed_url_selection_copy = [
        "Choose URLs",
        "Add manual links",
        "LLM Choose URLs",
        "Usefulness",
        "Max URLs",
        "Include PDF links",
        "Must contain",
        "Exclude contains",
        "Hosts/subdomains",
        "Selection saved",
        "score_and_filter_rows",
    ]
    for old_copy in removed_url_selection_copy:
        assert old_copy not in source
