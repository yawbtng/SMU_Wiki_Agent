from __future__ import annotations

from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
NAV_PATH = Path(__file__).resolve().parents[1] / "src" / "scrape_planner" / "ui_navigation.py"


def _sources_tab_source() -> str:
    text = APP_PATH.read_text(encoding="utf-8")
    start = text.index("with tabs[1]:")
    end = text.index("with tabs[2]:", start)
    return text[start:end]


def _corpus_tab_source() -> str:
    text = APP_PATH.read_text(encoding="utf-8")
    start = text.index("with tabs[3]:")
    end = text.index("with tabs[4]:", start)
    return text[start:end]


def test_sources_tab_keeps_pdf_sources_not_url_selection() -> None:
    app_source = APP_PATH.read_text(encoding="utf-8")
    source = _sources_tab_source()
    navigation_source = NAV_PATH.read_text(encoding="utf-8")

    assert '"Sources"' in navigation_source
    assert '"Choose URLs"' not in navigation_source
    assert "Choose URLs" not in app_source
    assert "Run LLM Choose URLs" not in app_source
    assert '"Documents"' in source
    assert "Upload PDFs" in source
    assert "Extract / Re-extract PDFs" in source

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


def test_sources_tab_uses_lightweight_page_preview_controls() -> None:
    source = _corpus_tab_source()

    assert '"PDF extraction"' in source
    assert '"Page-by-page markdown"' in source
    source = _sources_tab_source()

    assert '"Page number"' not in source
    assert '"Load preview"' not in source
    assert 'st.number_input(' not in source
    assert 'Click a path to preview:' not in source
    assert 'st.button(markdown_path, key=f"open_pdf_md_preview_{idx}"' not in source
    assert '"Preview page"' not in source


def test_pdf_extract_actions_handle_missing_docling_without_crashing() -> None:
    app_source = APP_PATH.read_text(encoding="utf-8")

    assert "PdfParserUnavailableError" in app_source
    assert "def _render_pdf_parser_unavailable_error(" in app_source
    assert "PDF extraction is unavailable until Docling is installed." in app_source
    assert 'Install `requirements-pdf.txt` in this environment' in app_source


def test_corpus_tab_promotes_pdf_extraction_progress() -> None:
    source = APP_PATH.read_text(encoding="utf-8")
    start = source.index("with tabs[3]:")
    end = source.index("with tabs[4]:", start)
    corpus = source[start:end]

    assert 'st.subheader("Corpus")' in corpus
    assert "PDF extraction" in corpus
    assert "Pages extracted" in corpus
    assert "Search chunks" in corpus
    assert "Chunk quality" in corpus
    assert "Content Inspector" in corpus
    assert "Registry path:" in corpus
    assert "Operator Details" in corpus
    assert "Raw Data Sources" not in corpus


def test_corpus_tab_uses_review_oriented_expander_defaults() -> None:
    corpus = _corpus_tab_source()

    assert 'with st.expander("PDF extraction", expanded=bool(page_rows)):' in corpus
    assert 'with st.expander("Embedding chunks", expanded=False):' in corpus
    assert 'with st.expander("PDF review queue", expanded=bool(quarantine_rows)):' in corpus


def test_corpus_tab_hides_raw_registry_path_outside_operator_details() -> None:
    corpus = _corpus_tab_source()

    assert 'st.caption(f"Registry path:' not in corpus
    assert 'st.caption("Registry path:' not in corpus
    registry_index = corpus.index('"Registry path:"')
    operator_details_index = corpus.rfind("render_operator_details(", 0, registry_index)
    assert operator_details_index != -1
    assert registry_index - operator_details_index < 250
