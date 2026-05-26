import ast
import importlib.util
import json
from pathlib import Path
from typing import Optional

from src.scrape_planner.site_layout import site_layout
from src.scrape_planner.stepper_status import (
    latest_json_report,
    load_embedding_status,
    load_mcp_status,
    load_wiki_status,
    raw_source_status,
    wiki_ready,
)
from src.scrape_planner.source_registry import build_source_row, write_registry_rows
from src.scrape_planner.ui_navigation import WORKFLOW_TABS


APP_SOURCE = Path(__file__).resolve().parents[1] / "app.py"
STATUS_SOURCE = Path(__file__).resolve().parents[1] / "src" / "scrape_planner" / "stepper_status.py"
EXPECTED_OPERATOR_TABS = [
    "Overview",
    "Sources",
    "Runs",
    "Documents",
    "Wiki",
    "Embeddings",
    "Metrics",
    "Settings",
]
LEGACY_WORKFLOW_COPY = [
    "Workspace -> Sources -> Raw Data Sources -> LLM Wiki -> Embed + Rerank -> MCP Query.",
    "Embed + Rerank",
    "MCP Query",
    "Query",
]


def _app_tree() -> ast.Module:
    return ast.parse(APP_SOURCE.read_text(encoding="utf-8"))


def _tab_body(tab_index: int) -> list[ast.stmt]:
    for node in ast.walk(_app_tree()):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "active_tab"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
        ):
            comparator = test.comparators[0]
            if (
                isinstance(comparator, ast.Subscript)
                and isinstance(comparator.value, ast.Name)
                and comparator.value.id == "WORKFLOW_TABS"
                and isinstance(comparator.slice, ast.Constant)
                and comparator.slice.value == tab_index
            ):
                return node.body
    raise AssertionError(f"WORKFLOW_TABS[{tab_index}] block not found")


def _literal_call_args(nodes: list[ast.stmt]) -> list[str]:
    values: list[str] = []
    for node in ast.walk(ast.Module(body=nodes, type_ignores=[])):
        if not isinstance(node, ast.Call):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                values.append(arg.value)
    return values


def _module_string_constants(tree: ast.AST) -> list[str]:
    return [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def _call_label(call: ast.Call) -> Optional[str]:
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return None


def _call_keyword(call: ast.Call, keyword_name: str) -> Optional[ast.AST]:
    for keyword in call.keywords:
        if keyword.arg == keyword_name:
            return keyword.value
    return None


def test_stepper_tabs_use_current_operator_workflow_order() -> None:
    assert WORKFLOW_TABS == EXPECTED_OPERATOR_TABS


def test_operator_caption_and_labels_drop_legacy_stepper_copy() -> None:
    string_constants = _module_string_constants(_app_tree())

    assert "Documents" in string_constants
    assert "Embeddings" in string_constants
    assert "Metrics" in string_constants
    assert "Settings" in string_constants
    for legacy_copy in LEGACY_WORKFLOW_COPY:
        assert legacy_copy not in string_constants


def test_wiki_action_blocks_until_corpus_sources_are_ready() -> None:
    wiki_body = _tab_body(4)
    wiki_literals = set(_literal_call_args(wiki_body))
    wiki_calls = [
        node for node in ast.walk(ast.Module(body=wiki_body, type_ignores=[])) if isinstance(node, ast.Call)
    ]
    build_button = next(
        call
        for call in wiki_calls
        if isinstance(call.func, ast.Attribute)
        and call.func.attr == "button"
        and _call_label(call) == "Build Wiki"
    )
    disabled_expr = _call_keyword(build_button, "disabled")

    assert "Blocked: prepare source documents before building the LLM Wiki." in wiki_literals
    assert isinstance(disabled_expr, ast.Name)
    assert disabled_expr.id == "build_disabled"


def test_status_sections_read_durable_stepper_artifacts() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    status_source = STATUS_SOURCE.read_text(encoding="utf-8")

    assert "layout.registry_path" in source
    assert 'latest_json_report(layout.raw_reports_dir, "normalization-*.json")' in status_source
    assert 'latest_json_report(layout.wiki_dir / "reports", "wiki-build-*.json")' in status_source
    assert "load_wiki_status(layout, raw_status)" in source
    assert "load_embedding_status(layout)" in source


def test_sources_and_runs_tabs_keep_current_ownership_boundaries() -> None:
    sources_literals = set(_literal_call_args(_tab_body(1)))
    runs_literals = set(_literal_call_args(_tab_body(2)))

    assert {
        "Sources",
        "Source Inventory",
        "Next Action",
        "Add Sources",
        "Website URLs",
        "Documents",
        "Prepared Sources",
    }.issubset(sources_literals)
    assert "Current Run" not in sources_literals
    assert "Recently scraped" not in sources_literals
    assert "Page outcomes" not in sources_literals

    assert {"Runs", "Current Run", "Page outcomes", "Markdown saved"}.issubset(runs_literals)


def test_sources_tab_hides_deep_pdf_details_by_default() -> None:
    sources_literals = set(_literal_call_args(_tab_body(1)))
    documents_literals = set(_literal_call_args(_tab_body(3)))

    assert "Page MD" not in sources_literals
    assert "Chunks" not in sources_literals
    assert "Quarantine" not in sources_literals
    assert "PDF extraction" not in sources_literals
    assert "Page-by-page markdown" not in sources_literals
    assert "Embedding chunks" not in sources_literals

    assert {"Sources", "Preview", "Choose source type", "PDF pages", "Scraped URLs"}.issubset(documents_literals)
    assert "PDF extraction" not in documents_literals
    assert "Raw markdown" not in documents_literals
    assert "Debug normalization report" not in documents_literals
    assert "#### Source Quality Examples" not in documents_literals
    assert "### Markdown Preview" not in documents_literals


def test_documents_review_source_uses_formatted_table_picker() -> None:
    source = APP_SOURCE.read_text(encoding="utf-8")
    documents_source = source[source.index("if active_tab == WORKFLOW_TABS[3]:") : source.index("# with tabs[4]:")]

    assert "def _document_source_picker(" in source
    assert "_document_source_picker(visible_docs, source_group=str(source_group))" in documents_source
    assert "def _document_source_title(" in source
    assert "def _document_source_subtitle(" in source
    assert "st.button(" in source
    assert "type=\"primary\" if selected else \"secondary\"" in source
    assert "Source website:" in source
    assert "st.dataframe(" not in documents_source
    assert "st.selectbox(\n                    \"Review source\"" not in documents_source
    assert "render_operator_details(\n                        \"Selected source\"" not in documents_source
    assert "{row['kind']} · {row['status']} · {row['title']} · {row['source_id']}" not in documents_source


def test_wiki_markdown_rendering_is_user_toggleable() -> None:
    wiki_literals = set(_literal_call_args(_tab_body(4)))

    assert "Show rendered Markdown" in wiki_literals


def test_wiki_stage_exposes_build_update_and_rebuild_actions() -> None:
    wiki_literals = set(_literal_call_args(_tab_body(4)))

    assert "Build Wiki" in wiki_literals
    assert "Update Wiki" in wiki_literals
    assert "Rebuild Wiki" in wiki_literals
    assert "Sources Waiting" in wiki_literals
    assert "PDF Waiting" in wiki_literals


def test_wiki_status_counts_pending_and_changed_sources_by_kind(tmp_path: Path) -> None:
    layout = site_layout(tmp_path / "site")
    layout.raw_sources_dir.mkdir(parents=True)
    web_pending = build_source_row(
        source_kind="web",
        title="Admissions",
        original_url="https://example.edu/admissions",
        original_path="",
        markdown_path="raw_sources/web/admissions.md",
        metadata_path="raw_sources/web/admissions.metadata.json",
        checksum="web-1",
        parser="fixture",
        status="ready",
    )
    pdf_pending = build_source_row(
        source_kind="pdf",
        title="Catalog",
        original_url="",
        original_path="/uploads/catalog.pdf",
        markdown_path="raw_sources/pdf/catalog.md",
        metadata_path="raw_sources/pdf/catalog.metadata.json",
        checksum="pdf-1",
        parser="docling",
        status="ready",
    )
    integrated = build_source_row(
        source_kind="pdf",
        title="Old Catalog",
        original_url="",
        original_path="/uploads/old.pdf",
        markdown_path="raw_sources/pdf/old.md",
        metadata_path="raw_sources/pdf/old.metadata.json",
        checksum="pdf-0",
        parser="docling",
        status="ready",
        wiki_status="integrated",
    )
    changed = build_source_row(
        source_kind="web",
        title="Tuition",
        original_url="https://example.edu/tuition",
        original_path="",
        markdown_path="raw_sources/web/tuition.md",
        metadata_path="raw_sources/web/tuition.metadata.json",
        checksum="web-2",
        parser="fixture",
        status="ready",
        wiki_status="integrated",
    )
    changed["change_state"] = "changed"
    write_registry_rows(layout.registry_path, [web_pending, pdf_pending, integrated, changed])

    raw_status = raw_source_status(layout)
    wiki_status = load_wiki_status(layout, raw_status)

    assert wiki_status["source_count"] == 4
    assert wiki_status["integrated_sources"] == 2
    assert wiki_status["pending_source_count"] == 3
    assert wiki_status["changed_source_count"] == 1
    assert wiki_status["pending_source_count_by_kind"]["pdf"] == 1
    assert wiki_status["pending_source_count_by_kind"]["web"] == 2


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
    layout.indexes_dir.mkdir(parents=True)
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
