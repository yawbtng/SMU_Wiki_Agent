from __future__ import annotations

import ast
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


def _tab_body(tab_index: int) -> list[ast.stmt]:
    tree = ast.parse(Path("app.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            context_expr = item.context_expr
            if (
                isinstance(context_expr, ast.Subscript)
                and isinstance(context_expr.value, ast.Name)
                and context_expr.value.id == "tabs"
                and isinstance(context_expr.slice, ast.Constant)
                and context_expr.slice.value == tab_index
            ):
                return node.body
    raise AssertionError(f"tabs[{tab_index}] block not found")


def _literal_call_args(nodes: list[ast.stmt]) -> list[str]:
    values: list[str] = []
    for node in ast.walk(ast.Module(body=nodes, type_ignores=[])):
        if not isinstance(node, ast.Call):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                values.append(arg.value)
    return values


def _called_streamlit_methods(nodes: list[ast.stmt]) -> set[str]:
    methods: set[str] = set()
    for node in ast.walk(ast.Module(body=nodes, type_ignores=[])):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            methods.add(node.func.attr)
    return methods


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


def test_runs_tab_owns_concrete_run_controls_and_activity() -> None:
    runs_body = _tab_body(2)
    literals = set(_literal_call_args(runs_body))
    methods = _called_streamlit_methods(runs_body)

    assert {"button", "progress", "metric"}.issubset(methods)
    assert {"Start New Scrape", "Resume", "Pause"}.issubset(literals)
    assert {"Current Run", "Recently scraped"}.issubset(literals)
    assert not any("preserved under Sources" in literal for literal in literals)


def test_retrieval_tab_exposes_graph_build_inspection_search_and_path_controls() -> None:
    retrieval_body = _tab_body(5)
    literals = set(_literal_call_args(retrieval_body))
    methods = _called_streamlit_methods(retrieval_body)
    visible_text = "\n".join(literals)

    assert {"selectbox", "button", "tabs", "dataframe"}.issubset(methods)
    assert "Knowledge Graph" in visible_text
    assert {
        "Build Deterministic Graph",
        "Search Matching Pages",
        "Shortest Path",
        "Traverse From Page",
    }.issubset(literals)
