import importlib.util
import json
from pathlib import Path

from src.scrape_planner.site_layout import site_layout
from src.scrape_planner.stepper_status import (
    latest_json_report,
    load_embedding_status,
    load_mcp_status,
    load_wiki_status,
    wiki_ready,
)
from src.scrape_planner.ui_navigation import WORKFLOW_TABS


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"
STATUS_SOURCE = Path(__file__).resolve().parents[1] / "src" / "scrape_planner" / "stepper_status.py"


def test_stepper_tabs_use_llm_wiki_workflow_order() -> None:
    assert WORKFLOW_TABS == [
        "Workspace",
        "Sources",
        "Raw Data Sources",
        "LLM Wiki",
        "Embed + Rerank",
        "MCP Query",
    ]


def test_llm_wiki_is_primary_post_source_action() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert 'st.caption("Workspace -> Sources -> Raw Data Sources -> LLM Wiki -> Embed + Rerank -> MCP Query.")' in source
    assert 'if build_col.button("Build LLM Wiki", type="primary", disabled=not raw_sources_ready' in source
    assert "Build Graph" not in source


def test_llm_wiki_action_blocks_until_raw_sources_are_ready() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    llm_wiki_tab = source[source.index("with tabs[3]:") : source.index("with tabs[4]:")]

    assert "raw_sources_ready = _raw_sources_ready(raw_status)" in llm_wiki_tab
    assert "Missing prerequisite: normalize raw data sources before building the LLM Wiki." in llm_wiki_tab
    assert 'disabled=not raw_sources_ready' in llm_wiki_tab


def test_status_sections_read_durable_stepper_artifacts() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    status_source = STATUS_SOURCE.read_text(encoding="utf-8")

    assert 'layout.registry_path' in source
    assert 'latest_json_report(layout.raw_reports_dir, "normalization-*.json")' in status_source
    assert 'latest_json_report(layout.wiki_dir / "reports", "wiki-build-*.json")' in status_source
    assert 'load_wiki_status(layout, raw_status)' in source
    assert 'load_embedding_status(layout)' in source
    assert 'load_mcp_status(layout)' in source


def test_stepper_copy_does_not_present_graph_as_primary_retrieval_path() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "Primary retrieval graph" not in source
    assert "Build Dynamic URL Graph" not in source
    assert "Dynamic URL graph is primary" not in source
    assert "primary graph path" not in source
    assert "Build LLM Wiki" in source
    assert "Supporting Knowledge Graph" in source


def test_supporting_graph_does_not_expose_primary_query_workbench() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "Ask the markdown graph" not in source
    assert "Ask Graph / Get Evidence" not in source
    assert "Search Matching Pages" not in source
    assert 'st.tabs(["Query", "Path", "Explain", "Knowledge Graph HTML"])' not in source


def test_sources_tab_presents_clean_intake_sections() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    sources_tab = source[source.index("with tabs[1]:") : source.index("with tabs[2]:")]

    assert 'st.subheader("Sources")' in sources_tab
    assert '"Source Inventory"' in sources_tab
    assert '"Next Action"' in sources_tab
    assert '"Add Sources"' in sources_tab
    assert '"Website URLs"' in sources_tab
    assert '"Documents"' in sources_tab
    assert '"Current Run"' in sources_tab
    assert '"Details"' in sources_tab
    assert '"Start New Scrape"' in sources_tab


def test_sources_tab_hides_technical_pdf_and_scrape_details_by_default() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    sources_tab = source[source.index("with tabs[1]:") : source.index("with tabs[2]:")]
    raw_tab = source[source.index("with tabs[2]:") : source.index("with tabs[3]:")]

    assert '"Page MD"' not in sources_tab
    assert '"Chunks"' not in sources_tab
    assert '"Quarantine"' not in sources_tab
    assert 'st.subheader("Current Activity")' not in sources_tab
    assert 'st.subheader("Recently Scraped")' not in sources_tab
    assert 'st.subheader("Current Failures")' not in sources_tab
    assert 'with st.expander("Scrape activity details"' in sources_tab
    assert 'with st.expander("All pages and filters"' in sources_tab
    assert 'with st.expander("PDF extraction details"' not in sources_tab
    assert 'with st.expander("Page-by-page markdown"' not in sources_tab
    assert 'with st.expander("Embedding chunks"' not in sources_tab
    assert 'with st.expander("PDF extraction details"' in raw_tab
    assert 'with st.expander("Page-by-page markdown"' in raw_tab
    assert 'with st.expander("Embedding chunks"' in raw_tab


def test_sources_ui_has_next_action_helper() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert "def _source_next_action(" in source
    assert 'return "Resume scrape"' in source
    assert 'return "Monitor scrape"' in source
    assert 'return "Start scrape"' in source
    assert 'return "Prepare sources"' in source
    assert 'return "Add sources"' in source


def test_latest_json_report_ignores_malformed_and_empty_reports(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "wiki-build-1.json").write_text("{not-json", encoding="utf-8")
    (report_dir / "wiki-build-2.json").write_text("{}", encoding="utf-8")

    report_path, report = latest_json_report(report_dir, "wiki-build-*.json")

    assert report_path is None
    assert report == {}


def test_wiki_ready_requires_valid_report_counts_or_index_artifact(tmp_path: Path) -> None:
    layout = site_layout(tmp_path / "site")
    (layout.wiki_dir / "reports").mkdir(parents=True)
    (layout.wiki_dir / "reports" / "wiki-build-bad.json").write_text("{not-json", encoding="utf-8")

    status = load_wiki_status(layout, {"rows": []})

    assert status["latest_report_path"] is None
    assert wiki_ready(status) is False

    layout.wiki_dir.mkdir(parents=True, exist_ok=True)
    (layout.wiki_dir / "index.md").write_text("# Wiki\n", encoding="utf-8")

    assert wiki_ready(load_wiki_status(layout, {"rows": []})) is True


def test_embedding_status_safely_defaults_malformed_numeric_fields(tmp_path: Path) -> None:
    layout = site_layout(tmp_path / "site")
    reports = layout.indexes_dir / "reports"
    reports.mkdir(parents=True)
    (reports / "embedding-bad-counts.json").write_text(
        json.dumps(
            {
                "raw_index_count": float("inf"),
                "wiki_documents": {"nope": 1},
                "changed_raw_count": "also-bad",
                "changed_wiki_documents": None,
            }
        ),
        encoding="utf-8",
    )

    status = load_embedding_status(layout)

    assert status["raw_index_count"] == 0
    assert status["wiki_index_count"] == 0
    assert status["changed_document_count"] == 0
    assert status["index_health"] == "missing"


def test_mcp_status_exposes_available_llm_wiki_server_command(tmp_path: Path) -> None:
    layout = site_layout(tmp_path / "site")

    status = load_mcp_status(layout)

    assert status["server_command"]
    assert status["server_available"] is True
    assert "mcp_servers.llm_wiki_mcp" in status["expected_server_command"]
    assert str(layout.site_root) in status["server_command"]
    assert status["config_snippet"]["mcpServers"]


def test_mcp_status_rejects_bare_executable_report_command(tmp_path: Path) -> None:
    layout = site_layout(tmp_path / "site")
    (layout.indexes_dir).mkdir(parents=True)
    (layout.indexes_dir / "mcp_status.json").write_text(
        json.dumps({"server_command": "/usr/bin/python3"}),
        encoding="utf-8",
    )

    status = load_mcp_status(layout)

    assert status["server_command"] != "/usr/bin/python3"
    assert "mcp_servers.llm_wiki_mcp" in status["server_command"]
    assert status["server_available"] is True
    assert status["config_snippet"]["mcpServers"]


def test_mcp_status_rejects_module_flag_without_executable(tmp_path: Path) -> None:
    layout = site_layout(tmp_path / "site")
    layout.indexes_dir.mkdir(parents=True)
    (layout.indexes_dir / "mcp_status.json").write_text(
        json.dumps({"server_command": "-m json"}),
        encoding="utf-8",
    )

    status = load_mcp_status(layout)

    assert status["server_command"].startswith(status["expected_server_command"].split(" -m ")[0])
    assert "mcp_servers.llm_wiki_mcp" in status["server_command"]
    assert status["server_available"] is True


def test_mcp_status_degrades_when_reported_module_lookup_raises(tmp_path: Path, monkeypatch) -> None:
    layout = site_layout(tmp_path / "site")
    layout.indexes_dir.mkdir(parents=True)
    (layout.indexes_dir / "mcp_status.json").write_text(
        json.dumps({"server_command": "python -m missing.module"}),
        encoding="utf-8",
    )
    real_find_spec = importlib.util.find_spec

    def flaky_find_spec(name: str):
        if name == "missing.module":
            raise ModuleNotFoundError("No module named missing")
        return real_find_spec(name)

    monkeypatch.setattr(importlib.util, "find_spec", flaky_find_spec)

    status = load_mcp_status(layout)

    assert "missing.module" not in status["server_command"]
    assert "mcp_servers.llm_wiki_mcp" in status["server_command"]
    assert status["server_available"] is True
