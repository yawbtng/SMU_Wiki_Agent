from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from src.scrape_planner.core.site_layout import site_layout
from src.scrape_planner.sources.source_registry import build_source_row, write_registry_rows
from src.scrape_planner.wiki.stepper_status import (
    latest_json_report,
    load_embedding_status,
    load_mcp_status,
    load_wiki_status,
    raw_source_status,
    wiki_ready,
)


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
