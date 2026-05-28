from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_llm_wiki_index import NOW, _fixture_site


def _read_json_line(proc: subprocess.Popen[str]) -> dict:
    assert proc.stdout is not None
    line = proc.stdout.readline()
    assert line, "MCP server did not emit a response"
    return json.loads(line)


def test_mcp_tool_handlers_query_index_and_block_path_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import mcp_servers.llm_wiki_mcp as server
    from src.scrape_planner.llm_wiki_index import build_llm_wiki_index

    site_root = _fixture_site(tmp_path)
    build_llm_wiki_index(site_root, now=NOW)
    monkeypatch.setattr(server, "SITE_ROOT", site_root)

    info = server.index_info()
    assert info["ok"] is True
    assert info["site_root"] == str(site_root.resolve())
    assert info["raw_index_count"] >= 2
    assert info["wiki_index_count"] == 1
    assert info["config_snippet"]["mcpServers"]

    query = server.query_wiki("admissions deadline", max_results=2)
    assert query["ok"] is True
    assert query["evidence"][0]["source_kind"] == "wiki"
    assert query["evidence"][0]["path"] == "wiki/pages/admissions.md"

    sources = server.search_sources("catalog tuition", max_results=2)
    assert sources["ok"] is True
    assert sources["evidence"][0]["source_kind"] == "pdf"

    page = server.get_wiki_page("wiki/pages/admissions.md")
    assert page["ok"] is True
    assert page["path"] == "wiki/pages/admissions.md"
    assert "February 1" in page["markdown"]

    nested_dir = site_root / "wiki" / "pages" / "schools" / "cox"
    nested_dir.mkdir(parents=True, exist_ok=True)
    (nested_dir / "graduate.md").write_text("# Cox Graduate\n", encoding="utf-8")
    nested_page = server.get_wiki_page("wiki/pages/schools/cox/graduate.md")
    assert nested_page["ok"] is True
    assert nested_page["path"] == "wiki/pages/schools/cox/graduate.md"
    assert "Cox Graduate" in nested_page["markdown"]

    (site_root / "wiki" / "log.md").write_text("# Build Log\n", encoding="utf-8")
    log_page = server.get_wiki_page("wiki/log.md")
    assert log_page["ok"] is False
    assert log_page["error"] == "path_outside_allowed_subtree"

    escaped = server.get_wiki_page("../outside.md")
    assert escaped["ok"] is False
    assert escaped["error"] == "path_escapes_site_root"


def test_stdio_fallback_reports_malformed_json_without_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    import mcp_servers.llm_wiki_mcp as server

    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO("{not-json\n"))
    monkeypatch.setattr(sys, "stdout", stdout)

    server._run_stdio_mcp_server("llm-wiki-query", {})

    response = json.loads(stdout.getvalue())
    assert response["jsonrpc"] == "2.0"
    assert response["id"] is None
    assert response["error"]["code"] == -32700


def test_mcp_stdio_startup_index_info_query_and_missing_index(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_index import build_llm_wiki_index

    site_root = _fixture_site(tmp_path)
    build_llm_wiki_index(site_root, now=NOW)
    env = {**os.environ, "PYTHONPATH": str(Path.cwd())}
    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_servers.llm_wiki_mcp", "--site-root", str(site_root)],
        cwd=str(Path.cwd()),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n")
        proc.stdin.flush()
        init_response = _read_json_line(proc)
        assert init_response["result"]["serverInfo"]["name"] == "llm-wiki-query"

        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n")
        proc.stdin.flush()
        tools_response = _read_json_line(proc)
        tool_names = {tool["name"] for tool in tools_response["result"]["tools"]}
        assert {"query_wiki", "search_sources", "get_wiki_page", "index_info"} <= tool_names

        proc.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "index_info", "arguments": {}},
                }
            )
            + "\n"
        )
        proc.stdin.flush()
        info_response = _read_json_line(proc)
        info = json.loads(info_response["result"]["content"][0]["text"])
        assert info["ok"] is True
        assert info["ready"] is True

        proc.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "query_wiki", "arguments": {"question": "admissions deadline", "max_results": 1}},
                }
            )
            + "\n"
        )
        proc.stdin.flush()
        query_response = _read_json_line(proc)
        query = json.loads(query_response["result"]["content"][0]["text"])
        assert query["ok"] is True
        assert query["evidence"][0]["source_kind"] == "wiki"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    missing_site = tmp_path / "missing-site"
    missing = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; import mcp_servers.llm_wiki_mcp as s; s.SITE_ROOT=__import__('pathlib').Path(__import__('sys').argv[1]); print(json.dumps(s.index_info()))",
            str(missing_site),
        ],
        cwd=str(Path.cwd()),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(missing.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "missing_index"
    assert not missing_site.exists()


def test_mcp_read_paths_do_not_create_missing_site_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import mcp_servers.llm_wiki_mcp as server

    missing_site = tmp_path / "missing-site"
    monkeypatch.setattr(server, "SITE_ROOT", missing_site)

    info = server.index_info()
    query = server.query_wiki("anything", max_results=1)
    sources = server.search_sources("anything", max_results=1)

    assert info["ok"] is False
    assert info["error"] == "missing_index"
    assert query["ok"] is False
    assert query["error"] == "missing_index"
    assert sources["ok"] is False
    assert sources["error"] == "missing_index"
    assert not missing_site.exists()
