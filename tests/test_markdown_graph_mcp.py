from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import mcp_servers.markdown_graph_mcp as server
from src.scrape_planner.markdown_graph import build_graph
from tests.test_markdown_graph import _write_fixture_run


def test_mcp_tool_handlers_return_graph_context(tmp_path: Path, monkeypatch) -> None:
    run_root, site_id, run_id = _write_fixture_run(tmp_path)
    data_root = tmp_path / "data"
    build_graph(run_root, site_id, run_id)
    monkeypatch.setattr(server, "DATA_ROOT", data_root)

    stats = server.graph_stats(site_id=site_id, run_id=run_id)
    assert stats["page_nodes"] == 6

    units = server.list_units(site_id=site_id, run_id=run_id)
    assert any(row["unit_key"] == "isss_international" for row in units)

    results = server.search_pages(
        query="I-20 international students",
        site_id=site_id,
        run_id=run_id,
        limit=3,
    )
    assert results
    page_id = results[0]["page_id"]
    page = server.get_page(page_id=page_id, site_id=site_id, run_id=run_id)
    assert page["id"] == page_id

    markdown = server.get_page_markdown(page_id=page_id, site_id=site_id, run_id=run_id)
    assert "markdown" in markdown
    assert markdown["path"].endswith(".md")

    context = server.answer_context(
        question="what do international students need for I-20?",
        site_id=site_id,
        run_id=run_id,
        budget_chars=4000,
    )
    assert context["evidence"]
    assert "i-20" in context["evidence"][0]["source_url"].lower()

    traversal = server.traverse_from_page(page_id="page:admission", site_id=site_id, run_id=run_id, depth=1)
    assert traversal["edges"]
    path = server.shortest_path(from_id="page:admission", to_id="page:isss", site_id=site_id, run_id=run_id)
    assert path["found"] is True


def _read_json_line(proc: subprocess.Popen[str]) -> dict:
    assert proc.stdout is not None
    line = proc.stdout.readline()
    assert line, "MCP server did not emit a response"
    return json.loads(line)


def test_mcp_server_starts_and_handles_stdio_calls(tmp_path: Path) -> None:
    run_root, site_id, run_id = _write_fixture_run(tmp_path)
    build_graph(run_root, site_id, run_id)
    env = {
        **os.environ,
        "MARKDOWN_GRAPH_DATA_ROOT": str(tmp_path / "data"),
        "PYTHONPATH": str(Path.cwd()),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_servers.markdown_graph_mcp"],
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
        assert init_response["result"]["serverInfo"]["name"] == "markdown-graph-query"

        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n")
        proc.stdin.flush()
        tools_response = _read_json_line(proc)
        tool_names = {tool["name"] for tool in tools_response["result"]["tools"]}
        assert "graph_stats" in tool_names
        assert "answer_context" in tool_names

        proc.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "graph_stats",
                        "arguments": {"site_id": site_id, "run_id": run_id},
                    },
                }
            )
            + "\n"
        )
        proc.stdin.flush()
        call_response = _read_json_line(proc)
        payload = json.loads(call_response["result"]["content"][0]["text"])
        assert payload["page_nodes"] == 6
        assert payload["counts_match"] is True
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
