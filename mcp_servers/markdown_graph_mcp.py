from __future__ import annotations

import os
import inspect
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover - import guard for unit tests without optional MCP deps
    class FastMCP:  # type: ignore[no-redef]
        def __init__(self, _name: str) -> None:
            self.name = _name
            self._tools: dict[str, Any] = {}

        def tool(self):
            def decorator(func):
                self._tools[func.__name__] = func
                return func

            return decorator

        def run(self) -> None:
            _run_stdio_mcp_server(self.name, self._tools)

from src.scrape_planner.markdown_graph import (  # noqa: E402
    answer_context as _answer_context,
    get_page as _get_page,
    get_page_markdown as _get_page_markdown,
    get_unit as _get_unit,
    get_unit_pages as _get_unit_pages,
    graph_stats as _graph_stats,
    list_units as _list_units,
    search_pages as _search_pages,
    shortest_path as _shortest_path,
    traverse_from_page as _traverse_from_page,
)

mcp = FastMCP("markdown-graph-query")

DATA_ROOT = Path(os.getenv("MARKDOWN_GRAPH_DATA_ROOT", "data")).resolve()


def _json_type(annotation: Any) -> str:
    if annotation in {int, "int"}:
        return "integer"
    if annotation in {float, "float"}:
        return "number"
    if annotation in {bool, "bool"}:
        return "boolean"
    if annotation in {dict, "dict"}:
        return "object"
    if annotation in {list, "list"}:
        return "array"
    return "string"


def _tool_schema(func: Any) -> dict[str, Any]:
    signature = inspect.signature(func)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in signature.parameters.items():
        properties[name] = {"type": _json_type(param.annotation)}
        if param.default is inspect._empty:
            required.append(name)
    return {"type": "object", "properties": properties, "required": required}


def _tool_list(tools: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": inspect.getdoc(func) or "",
            "inputSchema": _tool_schema(func),
        }
        for name, func in sorted(tools.items())
    ]


def _write_response(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _run_stdio_mcp_server(name: str, tools: dict[str, Any]) -> None:
    """Small stdio MCP fallback used when the optional FastMCP package is absent."""
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        request_id = request.get("id")
        method = request.get("method")
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": name, "version": "0.1.0"},
                }
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                result = {"tools": _tool_list(tools)}
            elif method == "tools/call":
                params = request.get("params") or {}
                tool_name = str(params.get("name") or "")
                arguments = params.get("arguments") or {}
                if tool_name not in tools:
                    raise KeyError(tool_name)
                value = tools[tool_name](**arguments)
                result = {
                    "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=True)}],
                    "isError": False,
                }
            else:
                raise NotImplementedError(method)
            if request_id is not None:
                _write_response({"jsonrpc": "2.0", "id": request_id, "result": result})
        except Exception as exc:
            if request_id is not None:
                _write_response(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32000, "message": str(exc)},
                    }
                )


def _run_root(site_id: str, run_id: str) -> Path:
    return DATA_ROOT / "sites" / site_id / run_id


@mcp.tool()
def graph_stats(site_id: str, run_id: str) -> dict[str, Any]:
    """Return graph artifact and coverage counts for a scrape run."""
    return _graph_stats(_run_root(site_id, run_id))


@mcp.tool()
def search_pages(query: str, site_id: str, run_id: str, unit: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Lexically search graph page nodes and return concise markdown evidence pointers."""
    return _search_pages(_run_root(site_id, run_id), query, unit=unit, limit=limit)


@mcp.tool()
def get_page(page_id: str, site_id: str, run_id: str) -> dict[str, Any]:
    """Return a page node by page_id."""
    page = _get_page(_run_root(site_id, run_id), page_id)
    if not page:
        raise KeyError(page_id)
    return page


@mcp.tool()
def get_page_markdown(page_id: str, site_id: str, run_id: str) -> dict[str, Any]:
    """Return exact raw markdown text plus source path and URL for a page."""
    root = _run_root(site_id, run_id)
    page = _get_page(root, page_id)
    if not page:
        raise KeyError(page_id)
    return {
        "page_id": page_id,
        "title": page.get("title"),
        "source_url": page.get("source_url"),
        "path": page.get("path"),
        "markdown": _get_page_markdown(root, page_id),
    }


@mcp.tool()
def get_unit(unit_id: str, site_id: str, run_id: str) -> dict[str, Any]:
    """Return a deterministic university unit node."""
    unit = _get_unit(_run_root(site_id, run_id), unit_id)
    if not unit:
        raise KeyError(unit_id)
    return unit


@mcp.tool()
def list_units(site_id: str, run_id: str) -> list[dict[str, Any]]:
    """List deterministic university units with page counts."""
    return _list_units(_run_root(site_id, run_id))


@mcp.tool()
def get_unit_pages(unit_id: str, site_id: str, run_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return pages tagged to a university unit."""
    return _get_unit_pages(_run_root(site_id, run_id), unit_id, limit=limit)


@mcp.tool()
def traverse_from_page(page_id: str, site_id: str, run_id: str, depth: int = 1) -> dict[str, Any]:
    """Traverse graph edges outward from a page."""
    return _traverse_from_page(_run_root(site_id, run_id), page_id, depth=depth)


@mcp.tool()
def shortest_path(from_id: str, to_id: str, site_id: str, run_id: str) -> dict[str, Any]:
    """Find a shortest directed graph path between two nodes."""
    return _shortest_path(_run_root(site_id, run_id), from_id, to_id)


@mcp.tool()
def answer_context(
    question: str,
    site_id: str,
    run_id: str,
    unit: str | None = None,
    budget_chars: int = 12000,
) -> dict[str, Any]:
    """Return exact markdown evidence for an LLM to answer from; does not invent an answer."""
    return _answer_context(_run_root(site_id, run_id), question, unit=unit, budget_chars=budget_chars)


if __name__ == "__main__":
    mcp.run()
