from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    if os.getenv("LLM_WIKI_FORCE_STDIO_FALLBACK"):
        raise ImportError("forced stdio fallback")
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


from src.scrape_planner.wiki.llm_wiki_index import (  # noqa: E402
    generate_mcp_config_snippet,
    index_info as _index_info,
    query_mcp_wiki_index,
    search_source_index,
)
from src.scrape_planner.wiki.self_improving import (  # noqa: E402
    answer_question as _answer_question,
    ingest_url as _ingest_url,
)


mcp = FastMCP("llm-wiki-query")
SITE_ROOT = Path(os.getenv("LLM_WIKI_SITE_ROOT", ".")).resolve()
DATA_ROOT = Path(os.getenv("LLM_WIKI_DATA_ROOT", "")).resolve() if os.getenv("LLM_WIKI_DATA_ROOT") else None


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


def _token(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _site_has_markdown_pages(site_root: Path) -> bool:
    wiki_dir = site_root / "wiki"
    if (wiki_dir / "index.md").exists():
        return True
    pages_dir = wiki_dir / "pages"
    return pages_dir.exists() and any(pages_dir.rglob("*.md"))


def _site_has_query_index(site_root: Path) -> bool:
    return any(
        path.exists()
        for path in (
            site_root / "indexes" / "llm_wiki_documents.jsonl",
            site_root / "indexes" / "llm_wiki_manifest.json",
            site_root / "wiki" / "index" / "llm_wiki_documents.jsonl",
            site_root / "wiki" / "index" / "llm_wiki_manifest.json",
        )
    )


def _university_registry() -> list[dict[str, Any]]:
    if DATA_ROOT is None:
        return [
            {
                "site_id": SITE_ROOT.name,
                "name": SITE_ROOT.name,
                "url": "",
                "domain": SITE_ROOT.name,
                "site_root": str(SITE_ROOT),
                "wiki_ready": _site_has_markdown_pages(SITE_ROOT),
                "index_ready": _site_has_query_index(SITE_ROOT),
                "mcp_enabled": True,
            }
        ]
    sites_root = DATA_ROOT / "sites"
    rows: list[dict[str, Any]] = []
    if not sites_root.exists():
        return rows
    for site_root in sorted(sites_root.iterdir(), key=lambda item: item.name):
        if not site_root.is_dir():
            continue
        summary = _read_json(site_root / "discovery_summary.json", {})
        url = str(summary.get("site_url") or "") if isinstance(summary, dict) else ""
        domain = urlparse(url).netloc or site_root.name
        wiki_ready = _site_has_markdown_pages(site_root)
        index_ready = _site_has_query_index(site_root)
        rows.append(
            {
                "site_id": site_root.name,
                "name": str(summary.get("name") or site_root.name) if isinstance(summary, dict) else site_root.name,
                "url": url,
                "domain": domain,
                "site_root": str(site_root),
                "wiki_ready": wiki_ready,
                "index_ready": index_ready,
                "mcp_enabled": wiki_ready or index_ready,
            }
        )
    return rows


def _resolve_site_root(site_id: str = "", university_hint: str = "") -> tuple[Path | None, str, list[dict[str, Any]]]:
    rows = _university_registry()
    if DATA_ROOT is None:
        return SITE_ROOT, "", []
    explicit = str(site_id or "").strip()
    if explicit:
        for row in rows:
            if row["site_id"] == explicit:
                return Path(str(row["site_root"])).resolve(), "", []
        return None, "site_not_found", []
    hint = _token(university_hint)
    if hint:
        matches = []
        for row in rows:
            haystack = {_token(row.get("site_id")), _token(row.get("name")), _token(row.get("domain")), _token(row.get("url"))}
            if any(hint and (hint == item or hint in item or item in hint) for item in haystack if item):
                matches.append(row)
        if len(matches) == 1:
            return Path(str(matches[0]["site_root"])).resolve(), "", []
        if len(matches) > 1:
            return None, "ambiguous_university", matches
        return None, "site_not_found", []
    enabled = [row for row in rows if row.get("mcp_enabled")]
    if len(enabled) == 1:
        return Path(str(enabled[0]["site_root"])).resolve(), "", []
    return None, "site_required", enabled[:10]


def _site_error(error: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {"ok": False, "error": error, "candidates": [{k: row.get(k) for k in ("site_id", "name", "domain", "wiki_ready", "index_ready")} for row in candidates]}


def _safe_site_path(rel_path: str, *, site_root: Path | None = None, must_be_under: Path | None = None) -> tuple[Path | None, str]:
    root = (site_root or SITE_ROOT).resolve()
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


def _resolve_wiki_page_reference(value: str, *, site_root: Path | None = None) -> str:
    root = site_root or SITE_ROOT
    if not value:
        return ""
    if value.endswith(".md") or value.startswith("wiki/"):
        return value
    manifest_path = root / "wiki" / "navigation_manifest.json"
    if not manifest_path.exists():
        return value
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return value
    pages = manifest.get("pages") if isinstance(manifest, dict) else []
    if not isinstance(pages, list):
        return value
    normalized = _page_ref_token(value)
    for page in pages:
        if not isinstance(page, dict):
            continue
        candidates = [page.get("page_id"), page.get("title"), page.get("path")]
        if normalized in {_page_ref_token(candidate) for candidate in candidates if candidate}:
            return str(page.get("path") or value)
    return value


def _page_ref_token(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def _response_from_query(payload: dict[str, Any]) -> dict[str, Any]:
    ok = payload.get("status") == "ok"
    metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
    return {
        "ok": ok,
        "error": "" if ok else str(payload.get("status") or "query_failed"),
        "query": payload.get("query"),
        "evidence": payload.get("evidence", []),
        "next_pages": metadata.get("next_pages", []),
        "metadata": metadata,
    }


@mcp.tool()
def list_universities() -> dict[str, Any]:
    """List universities available to the global MCP gateway with wiki/index readiness."""
    rows = _university_registry()
    return {
        "ok": True,
        "universities": rows,
        "count": len(rows),
        "ready_count": sum(1 for row in rows if row.get("mcp_enabled")),
        "mode": "global" if DATA_ROOT is not None else "single-site",
    }


@mcp.tool()
def find_university(query: str) -> dict[str, Any]:
    """Find candidate universities by site id, name, URL, or domain."""
    _, error, candidates = _resolve_site_root(university_hint=query)
    if error and candidates:
        return _site_error(error, candidates)
    if error:
        return {"ok": False, "error": error, "candidates": []}
    site_root, _, _ = _resolve_site_root(university_hint=query)
    rows = [row for row in _university_registry() if Path(str(row.get("site_root"))).resolve() == site_root]
    return {"ok": True, "universities": rows, "count": len(rows)}


@mcp.tool()
def query_wiki(question: str, max_results: int = 5, site_id: str = "", university_hint: str = "") -> dict[str, Any]:
    """Query one university wiki. In global mode pass site_id or university_hint to choose the university."""
    site_root, error, candidates = _resolve_site_root(site_id, university_hint)
    if error or site_root is None:
        return _site_error(error, candidates)
    response = _response_from_query(query_mcp_wiki_index(site_root, question, max_evidence=max_results))
    response["site_id"] = site_root.name
    return response


@mcp.tool()
def answer_question(question: str, max_results: int = 5, site_id: str = "", university_hint: str = "") -> dict[str, Any]:
    """Answer for one university with local evidence; low confidence can queue quality-gated ingest."""
    site_root, error, candidates = _resolve_site_root(site_id, university_hint)
    if error or site_root is None:
        return _site_error(error, candidates)
    response = _answer_question(site_root, question, max_evidence=max_results)
    response["site_id"] = site_root.name
    return response


@mcp.tool()
def ingest_url(url: str, question: str = "", site_id: str = "", university_hint: str = "") -> dict[str, Any]:
    """Queue quality-gated ingestion for one URL into a selected university workspace."""
    site_root, error, candidates = _resolve_site_root(site_id, university_hint)
    if error or site_root is None:
        return _site_error(error, candidates)
    response = _ingest_url(site_root, url, question=question)
    response["site_id"] = site_root.name
    return response


@mcp.tool()
def search_sources(query: str, max_results: int = 5, site_id: str = "", university_hint: str = "") -> dict[str, Any]:
    """Search raw source evidence for one selected university."""
    site_root, error, candidates = _resolve_site_root(site_id, university_hint)
    if error or site_root is None:
        return _site_error(error, candidates)
    response = _response_from_query(search_source_index(site_root, query, max_evidence=max_results))
    response["site_id"] = site_root.name
    return response


@mcp.tool()
def get_wiki_page(path: str, site_id: str = "", university_hint: str = "") -> dict[str, Any]:
    """Return exact generated wiki page markdown for one selected university."""
    site_root, error, candidates = _resolve_site_root(site_id, university_hint)
    if error or site_root is None:
        return _site_error(error, candidates)
    requested = str(path or "").strip()
    resolved_path = _resolve_wiki_page_reference(requested, site_root=site_root)
    wiki_root = (site_root / "wiki").resolve()
    target, path_error = _safe_site_path(resolved_path or requested, site_root=site_root, must_be_under=wiki_root)
    if path_error:
        return {"ok": False, "error": path_error, "path": path, "site_id": site_root.name}
    assert target is not None
    pages_root = (wiki_root / "pages").resolve()
    allowed_index = target == wiki_root / "index.md"
    allowed_page = False
    if target.suffix == ".md":
        try:
            target.relative_to(pages_root)
            allowed_page = True
        except ValueError:
            allowed_page = False
    if not allowed_index and not allowed_page:
        return {"ok": False, "error": "path_outside_allowed_subtree", "path": path, "site_id": site_root.name}
    if not target.exists() or not target.is_file():
        return {"ok": False, "error": "page_not_found", "path": path, "site_id": site_root.name}
    try:
        rel = str(target.relative_to(site_root.resolve()))
    except ValueError:
        rel = str(target)
    return {
        "ok": True,
        "error": "",
        "site_id": site_root.name,
        "path": rel,
        "markdown": target.read_text(encoding="utf-8", errors="replace"),
    }


@mcp.tool()
def index_info(site_id: str = "", university_hint: str = "") -> dict[str, Any]:
    """Return index health for one university, or registry summary in global mode when no site is selected."""
    site_root, error, candidates = _resolve_site_root(site_id, university_hint)
    if error or site_root is None:
        if error == "site_required":
            return {"ok": True, **list_universities()}
        return _site_error(error, candidates)
    info = _index_info(site_root)
    info["site_id"] = site_root.name
    if "config_snippet" not in info:
        info["config_snippet"] = generate_mcp_config_snippet(site_root)
    return info


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MCP server for local LLM Wiki indexes.")
    parser.add_argument("--site-root", default=os.getenv("LLM_WIKI_SITE_ROOT", "."), help="Legacy single-site root.")
    parser.add_argument("--data-root", default=os.getenv("LLM_WIKI_DATA_ROOT", ""), help="Global data root containing sites/*.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    global DATA_ROOT, SITE_ROOT
    args = _parse_args(argv)
    if args.data_root:
        DATA_ROOT = Path(args.data_root).resolve()
        SITE_ROOT = DATA_ROOT
    else:
        DATA_ROOT = None
        SITE_ROOT = Path(args.site_root).resolve()
    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
