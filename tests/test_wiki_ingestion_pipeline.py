from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.scrape_planner.site_layout import ensure_site_layout
from src.scrape_planner.storage import write_json
from src.scrape_planner.wiki_ingestion_pipeline import run_wiki_ingestion_pipeline


NOW = "2026-05-21T12:00:00+00:00"


def test_wiki_ingestion_pipeline_runs_normalize_wiki_index_and_query(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    run_root = site_root / "run-001"
    markdown = run_root / "markdown" / "admissions.md"
    metadata = run_root / "metadata" / "admissions.json"
    markdown.parent.mkdir(parents=True)
    metadata.parent.mkdir(parents=True)
    markdown.write_text(
        "# Admissions Deadline\n\nStudents should apply by February 1. Admission requirements include transcripts.\n",
        encoding="utf-8",
    )
    write_json(metadata, {"url": "https://example.edu/admissions", "http_status": 200})
    write_json(
        run_root / "scrape_manifest.json",
        [
            {
                "url": "https://example.edu/admissions",
                "status": "success",
                "markdown_path": str(markdown),
                "metadata_path": str(metadata),
                "fetch_mode": "fixture",
            }
        ],
    )

    result = run_wiki_ingestion_pipeline(
        site_root=site_root,
        run_root=run_root,
        kinds=["web"],
        rebuild=True,
        query="application deadline",
        now=NOW,
    )

    assert result["status"] == "complete"
    assert result["normalization"]["counts"]["ready"] == 1
    assert result["registry"]["ready_source_count"] == 1
    assert result["wiki"]["integrated_sources"] == 1
    assert result["index"]["raw_index_count"] >= 1
    assert result["index"]["wiki_index_count"] >= 1
    assert result["query"]["status"] == "ok"
    assert (site_root / "wiki" / "index.md").exists()
    assert (site_root / "indexes" / "llm_wiki_manifest.json").exists()


def test_wiki_ingestion_pipeline_rejects_web_without_run_root(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root

    with pytest.raises(ValueError, match="web normalization requires run_root"):
        run_wiki_ingestion_pipeline(site_root=site_root, kinds=["web"], now=NOW)


def test_wiki_ingestion_pipeline_skip_normalize_reuses_registry(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    raw_path = site_root / "raw_sources" / "web" / "admissions.md"
    metadata_path = site_root / "raw_sources" / "web" / "admissions.metadata.json"
    raw_path.write_text("# Admissions\n\nApply by February 1.\n", encoding="utf-8")
    metadata_path.write_text("{}", encoding="utf-8")
    registry_row = {
        "source_id": "web_fixture_admissions",
        "source_kind": "web",
        "title": "Admissions",
        "original_url": "https://example.edu/admissions",
        "original_path": str(raw_path),
        "markdown_path": "raw_sources/web/admissions.md",
        "metadata_path": "raw_sources/web/admissions.metadata.json",
        "checksum": "fixture-checksum",
        "parser": "fixture",
        "status": "ready",
        "change_state": "new",
        "wiki_status": "",
        "provenance": {},
    }
    registry = site_root / "raw_sources" / "registry.jsonl"
    registry.write_text(json.dumps(registry_row) + "\n", encoding="utf-8")

    result = run_wiki_ingestion_pipeline(site_root=site_root, skip_normalize=True, rebuild=True, now=NOW)

    assert result["normalization"]["skipped"] is True
    assert result["registry"]["ready_source_count"] == 1
    assert result["wiki"]["integrated_sources"] == 1
    assert result["index"]["wiki_index_count"] >= 1
