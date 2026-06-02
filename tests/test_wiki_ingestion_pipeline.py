from __future__ import annotations

import json
from pathlib import Path

from src.scrape_planner.core.site_layout import ensure_site_layout
from src.scrape_planner.core.storage import write_json
from src.scrape_planner.wiki.wiki_ingestion_pipeline import run_wiki_ingestion_pipeline


NOW = "2026-05-21T12:00:00+00:00"


def _fake_pi_compile(site_root: Path, *, rebuild: bool = False) -> None:
    del rebuild
    registry = site_root / "raw_sources" / "registry.jsonl"
    rows = [json.loads(line) for line in registry.read_text(encoding="utf-8").splitlines() if line.strip()] if registry.exists() else []
    ready = [row for row in rows if str(row.get("status") or "").lower() == "ready"]
    source_id = str(ready[0].get("source_id") or "source") if ready else "source"
    wiki = site_root / "wiki" / "pages"
    wiki.mkdir(parents=True, exist_ok=True)
    page = wiki / "admissions.md"
    rel_page = str(page.relative_to(site_root))
    page.write_text(
        f"---\ntitle: Admissions\nsource_ids:\n  - {source_id}\nsource_paths:\n  - raw_sources/web/admissions.md\n---\n\n# Admissions\n\nApply by February 1.\n\n## Sources\n- `{source_id}`\n",
        encoding="utf-8",
    )
    (site_root / "wiki" / "index.md").write_text(f"# Wiki Index\n\n- [Admissions](wiki/pages/admissions.md)\n", encoding="utf-8")
    for row in ready:
        row["wiki_status"] = "integrated"
        row["wiki_page_paths"] = [rel_page]
    if rows:
        registry.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_wiki_ingestion_pipeline_runs_normalize_wiki_index_and_query(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("src.scrape_planner.wiki.llm_wiki_builder._run_pi_compile", _fake_pi_compile)
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
    assert result["index"]["wiki_index_count"] >= 1
    assert result["query"]["status"] == "ok"
    assert (site_root / "wiki" / "index.md").exists()
    assert (site_root / "indexes" / "llm_wiki_manifest.json").exists()


def test_wiki_ingestion_pipeline_rejects_web_without_run_root(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root

    result = run_wiki_ingestion_pipeline(site_root=site_root, kinds=["web"], now=NOW)

    assert result["status"] == "failed"
    assert result["failed_stage"] == "ingest"
    assert "web normalization requires run_root" in str(result["normalization"]["error"])


def test_wiki_ingestion_pipeline_skip_normalize_reuses_registry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("src.scrape_planner.wiki.llm_wiki_builder._run_pi_compile", _fake_pi_compile)
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
