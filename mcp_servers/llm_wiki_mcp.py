from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover - optional dependency fallback
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


from src.scrape_planner.llm_wiki_index import (  # noqa: E402
    generate_mcp_config_snippet,
    index_info as _index_info,
    query_llm_wiki_index,
    search_source_index,
)


mcp = FastMCP("llm-wiki-query")
SITE_ROOT = Path(os.getenv("LLM_WIKI_SITE_ROOT", ".")).resolve()


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
        request_id = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("invalid JSON-RPC request")
            request_id = request.get("id")
            method = request.get("method")
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
        except json.JSONDecodeError as exc:
            _write_response(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32700, "message": f"Parse error: {exc.msg}"},
                }
            )
        except Exception as exc:
            if request_id is not None:
                _write_response(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32000, "message": str(exc)},
                    }
                )


def _safe_site_path(rel_path: str, *, must_be_under: Path | None = None) -> tuple[Path | None, str]:
    root = SITE_ROOT.resolve()
    raw = Path(str(rel_path or ""))
    candidate = raw if raw.is_absolute() else root / raw
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root)
    except ValueError:
        return None, "path_escapes_site_root"
    if must_be_under is not None:
        try:
            resolved.relative_to(must_be_under.resolve())
        except ValueError:
            return None, "path_outside_allowed_subtree"
    return resolved, ""


def _response_from_query(payload: dict[str, Any]) -> dict[str, Any]:
    ok = payload.get("status") == "ok"
    return {
        "ok": ok,
        "error": "" if ok else str(payload.get("status") or "query_failed"),
        "query": payload.get("query"),
        "evidence": payload.get("evidence", []),
        "metadata": payload.get("metadata", {}),
    }


@mcp.tool()
def query_wiki(question: str, max_results: int = 5) -> dict[str, Any]:
    """Return reranked wiki/raw evidence for a question from existing local indexes."""
    return _response_from_query(query_llm_wiki_index(SITE_ROOT, question, max_evidence=max_results))


@mcp.tool()
def search_sources(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search raw source evidence only from existing local indexes."""
    return _response_from_query(search_source_index(SITE_ROOT, query, max_evidence=max_results))


@mcp.tool()
def get_wiki_page(path: str) -> dict[str, Any]:
    """Return exact generated wiki page markdown when the path stays inside the configured site root."""
    target, error = _safe_site_path(path, must_be_under=SITE_ROOT / "wiki")
    if error:
        return {"ok": False, "error": error, "path": path}
    assert target is not None
    wiki_root = (SITE_ROOT / "wiki").resolve()
    pages_root = (wiki_root / "pages").resolve()
    allowed_index = target == wiki_root / "index.md"
    allowed_page = target.parent == pages_root and target.suffix == ".md"
    if not allowed_index and not allowed_page:
        return {"ok": False, "error": "path_outside_allowed_subtree", "path": path}
    if not target.exists() or not target.is_file():
        return {"ok": False, "error": "page_not_found", "path": path}
    try:
        rel = str(target.relative_to(SITE_ROOT.resolve()))
    except ValueError:
        rel = str(target)
    return {
        "ok": True,
        "error": "",
        "path": rel,
        "markdown": target.read_text(encoding="utf-8", errors="replace"),
    }


@mcp.tool()
def index_info() -> dict[str, Any]:
    """Return LLM Wiki index health, counts, last build metadata, and Codex MCP config."""
    info = _index_info(SITE_ROOT)
    if "config_snippet" not in info:
        info["config_snippet"] = generate_mcp_config_snippet(SITE_ROOT)
    return info


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query-only MCP server for local LLM Wiki indexes.")
    parser.add_argument("--site-root", default=os.getenv("LLM_WIKI_SITE_ROOT", "."))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    global SITE_ROOT
    args = _parse_args(argv)
    SITE_ROOT = Path(args.site_root).resolve()
    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
