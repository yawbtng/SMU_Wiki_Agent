from __future__ import annotations

import ast
from pathlib import Path

from src.scrape_planner.ui_navigation import WORKFLOW_TABS


APP_SOURCE = Path("app.py")
SETTINGS_CAPTION = "Configure local providers, models, scraping, retrieval, and research."
SENSITIVE_KEY_NAMES = {
    "OPENROUTER_API_KEY",
    "TAVILY_API_KEY",
    "openrouter_api_key",
    "tavily_api_key",
}
KEY_RENDER_METHODS = {"caption", "code", "json", "markdown"}

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


def _call_label(call: ast.Call) -> str | None:
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return None


def _call_keyword_literal(call: ast.Call, keyword_name: str) -> object:
    for keyword in call.keywords:
        if keyword.arg == keyword_name and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    return None


def _is_sensitive_session_state_reference(node: ast.AST) -> bool:
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "st"
        and node.value.attr == "session_state"
        and isinstance(node.slice, ast.Constant)
        and node.slice.value in SENSITIVE_KEY_NAMES
    ):
        return True
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Attribute)
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "st"
        and node.func.value.attr == "session_state"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value in SENSITIVE_KEY_NAMES
    ):
        return True
    return False


def _render_call_uses_sensitive_key(call: ast.Call) -> bool:
    rendered_nodes = [*call.args, *(keyword.value for keyword in call.keywords)]
    for node in rendered_nodes:
        for child in ast.walk(node):
            if _is_sensitive_session_state_reference(child):
                return True
            if isinstance(child, ast.Constant) and child.value in SENSITIVE_KEY_NAMES:
                return True
    return False


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


def test_settings_has_own_top_level_tab() -> None:
    app_source = Path("app.py").read_text(encoding="utf-8")
    settings_tab_start = app_source.index("with tabs[6]:")
    settings_block = app_source[settings_tab_start:]

    assert 'st.subheader("Settings")' in settings_block
    assert f'st.caption("{SETTINGS_CAPTION}")' in settings_block
    assert "settings_tabs = st.tabs" in settings_block
    assert 'settings_tabs = st.tabs(["Keys", "LLM", "Scraping", "Retrieval", "Research"])' in settings_block
    assert "OPENROUTER_API_KEY" in settings_block
    assert "TAVILY_API_KEY" in settings_block
    assert "Save All Settings" in settings_block
    assert 'type="password"' in settings_block[settings_block.index('"OPENROUTER_API_KEY"') : settings_block.index('key="save_openrouter_key"')]
    assert 'type="password"' in settings_block[settings_block.index('"TAVILY_API_KEY"') : settings_block.index('key="save_tavily_key"')]
    assert not any(label in settings_block for label in ["🔑", "🤖", "🕷", "🔎", "🧪"])


def test_settings_masks_api_key_text_inputs() -> None:
    settings_body = _tab_body(6)
    text_inputs = [
        node
        for node in ast.walk(ast.Module(body=settings_body, type_ignores=[]))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "text_input"
        and _call_label(node) in {"OPENROUTER_API_KEY", "TAVILY_API_KEY"}
    ]

    labels_to_types = {_call_label(call): _call_keyword_literal(call, "type") for call in text_inputs}

    assert labels_to_types == {
        "OPENROUTER_API_KEY": "password",
        "TAVILY_API_KEY": "password",
    }


def test_settings_does_not_render_api_key_state_outside_password_inputs() -> None:
    settings_body = _tab_body(6)
    leaking_calls: list[str] = []
    for node in ast.walk(ast.Module(body=settings_body, type_ignores=[])):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr not in KEY_RENDER_METHODS:
            continue
        if node.func.attr == "text_input":
            continue
        if _render_call_uses_sensitive_key(node):
            leaking_calls.append(ast.unparse(node))

    assert leaking_calls == []


def test_runs_tab_owns_concrete_run_controls_and_activity() -> None:
    runs_body = _tab_body(2)
    literals = set(_literal_call_args(runs_body))
    methods = _called_streamlit_methods(runs_body)

    assert {"button", "progress", "metric"}.issubset(methods)
    assert {"Start New Scrape", "Resume", "Pause"}.issubset(literals)
    assert {"Current Run", "Recently scraped"}.issubset(literals)
    assert not any("preserved under Sources" in literal for literal in literals)


def test_overview_is_command_center_not_file_path_dump() -> None:
    app = APP_SOURCE.read_text(encoding="utf-8")
    start = app.index("with tabs[0]:")
    end = app.index("with tabs[1]:", start)
    overview = app[start:end]

    assert 'st.subheader("Overview")' in overview
    assert "render_status_band" in overview
    assert "build_operator_run_status" in overview
    assert "build_operator_source_status" in overview
    assert "Attention Needed" in overview
    assert "Registry path:" not in overview
    assert "tmux session:" not in overview
    assert "Server command" not in overview


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
