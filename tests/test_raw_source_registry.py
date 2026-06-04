from __future__ import annotations

from pathlib import Path

from src.scrape_planner.core.site_layout import ensure_site_layout
from src.scrape_planner.sources.source_registry import (
    build_source_row,
    checksum_text,
    merge_registry_rows,
    read_registry_rows,
    stable_source_id,
    write_registry_rows,
)


NOW = "2026-05-21T00:00:00+00:00"
LATER = "2026-05-21T01:00:00+00:00"


def test_site_layout_creates_raw_wiki_and_index_conventions(tmp_path: Path) -> None:
    layout = ensure_site_layout(tmp_path, "site-1")

    assert layout.site_root == tmp_path / "sites" / "site-1"
    assert layout.raw_sources_dir.is_dir()
    assert layout.raw_web_dir.is_dir()
    assert layout.raw_pdf_dir.is_dir()
    assert layout.raw_excel_dir.is_dir()
    assert layout.raw_reports_dir.is_dir()
    assert layout.wiki_dir.is_dir()
    assert layout.indexes_dir.is_dir()
    assert layout.registry_path == layout.raw_sources_dir / "registry.jsonl"


def test_registry_insert_writes_deterministic_row(tmp_path: Path) -> None:
    registry = tmp_path / "raw_sources" / "registry.jsonl"
    row = build_source_row(
        source_kind="web",
        title="Example Home",
        original_url="https://example.edu/",
        original_path="",
        markdown_path="raw_sources/web/example.md",
        metadata_path="raw_sources/web/example.metadata.json",
        checksum=checksum_text("# Example\n"),
        parser="scrape_worker.markdown",
        status="ready",
        now=NOW,
    )

    report = merge_registry_rows(registry, [row], now=NOW)

    rows = read_registry_rows(registry)
    assert report.counts["new"] == 1
    assert report.counts["ready"] == 1
    assert len(rows) == 1
    assert rows[0]["source_id"] == stable_source_id("web", "https://example.edu/")
    assert rows[0]["wiki_status"] == "pending"
    assert rows[0]["first_seen_at"] == NOW
    assert rows[0]["last_changed_at"] == NOW


def test_registry_unchanged_source_preserves_existing_integration_state(tmp_path: Path) -> None:
    registry = tmp_path / "raw_sources" / "registry.jsonl"
    row = build_source_row(
        source_kind="web",
        title="Example Home",
        original_url="https://example.edu/",
        original_path="",
        markdown_path="raw_sources/web/example.md",
        metadata_path="raw_sources/web/example.metadata.json",
        checksum=checksum_text("# Example\n"),
        parser="scrape_worker.markdown",
        status="ready",
        now=NOW,
    )
    row["wiki_status"] = "integrated"
    row["wiki_integrated_at"] = NOW
    write_registry_rows(registry, [row])

    incoming = dict(row)
    incoming["last_seen_at"] = LATER
    incoming["wiki_status"] = "pending"
    report = merge_registry_rows(registry, [incoming], now=LATER)

    [stored] = read_registry_rows(registry)
    assert report.counts["unchanged"] == 1
    assert stored["change_state"] == "unchanged"
    assert stored["wiki_status"] == "integrated"
    assert stored["wiki_integrated_at"] == NOW
    assert stored["first_seen_at"] == NOW


def test_registry_changed_checksum_marks_source_for_wiki_integration(tmp_path: Path) -> None:
    registry = tmp_path / "raw_sources" / "registry.jsonl"
    original = build_source_row(
        source_kind="pdf",
        title="Catalog",
        original_url="",
        original_path="/tmp/catalog.pdf",
        markdown_path="raw_sources/pdf/catalog.md",
        metadata_path="raw_sources/pdf/catalog.metadata.json",
        checksum=checksum_text("old"),
        parser="docling",
        status="ready",
        now=NOW,
    )
    original["wiki_status"] = "integrated"
    write_registry_rows(registry, [original])
    changed = build_source_row(
        source_kind="pdf",
        title="Catalog",
        original_url="",
        original_path="/tmp/catalog.pdf",
        markdown_path="raw_sources/pdf/catalog.md",
        metadata_path="raw_sources/pdf/catalog.metadata.json",
        checksum=checksum_text("new"),
        parser="docling",
        status="ready",
        now=LATER,
    )

    report = merge_registry_rows(registry, [changed], now=LATER)

    [stored] = read_registry_rows(registry)
    assert report.counts["changed"] == 1
    assert stored["change_state"] == "changed"
    assert stored["wiki_status"] == "pending"
    assert stored["first_seen_at"] == NOW
    assert stored["last_changed_at"] == LATER


def test_registry_failed_source_status_is_explicit(tmp_path: Path) -> None:
    registry = tmp_path / "raw_sources" / "registry.jsonl"
    failed = build_source_row(
        source_kind="excel",
        title="missing.csv",
        original_url="",
        original_path="/tmp/missing.csv",
        markdown_path="",
        metadata_path="raw_sources/excel/missing.metadata.json",
        checksum="",
        parser="pandas",
        status="failed",
        now=NOW,
        error_reason="File does not exist",
        diagnostic_path="raw_sources/reports/missing.error.json",
    )

    report = merge_registry_rows(registry, [failed], now=NOW)

    [stored] = read_registry_rows(registry)
    assert report.counts["failed"] == 1
    assert stored["status"] == "failed"
    assert stored["change_state"] == "failed"
    assert stored["error_reason"] == "File does not exist"
    assert stored["diagnostic_path"] == "raw_sources/reports/missing.error.json"


def test_registry_merge_reports_corrupt_jsonl_lines(tmp_path: Path) -> None:
    registry = tmp_path / "raw_sources" / "registry.jsonl"
    registry.parent.mkdir(parents=True)
    registry.write_text("{not-json}\n\n", encoding="utf-8")
    row = build_source_row(
        source_kind="web",
        title="Example Home",
        original_url="https://example.edu/",
        original_path="",
        markdown_path="raw_sources/web/example.md",
        metadata_path="raw_sources/web/example.metadata.json",
        checksum=checksum_text("# Example\n"),
        parser="scrape_worker.markdown",
        status="ready",
        now=NOW,
    )

    report = merge_registry_rows(registry, [row], now=NOW)

    assert report.counts["registry_corrupt_lines"] == 1
    assert report.counts["ready"] == 1
    assert len(read_registry_rows(registry)) == 1


def test_registry_merge_quarantines_later_duplicate_checksum_in_batch(tmp_path: Path) -> None:
    registry = tmp_path / "raw_sources" / "registry.jsonl"
    checksum = checksum_text("# Same content\n")
    first = build_source_row(
        source_kind="web",
        title="First",
        original_url="https://example.edu/first",
        original_path="",
        markdown_path="raw_sources/web/first.md",
        metadata_path="raw_sources/web/first.metadata.json",
        checksum=checksum,
        parser="scrape_worker.markdown",
        status="ready",
        now=NOW,
    )
    duplicate = build_source_row(
        source_kind="web",
        title="Duplicate",
        original_url="https://example.edu/duplicate",
        original_path="",
        markdown_path="raw_sources/web/duplicate.md",
        metadata_path="raw_sources/web/duplicate.metadata.json",
        checksum=checksum,
        parser="scrape_worker.markdown",
        status="ready",
        now=NOW,
    )

    report = merge_registry_rows(registry, [first, duplicate], now=NOW)

    rows = read_registry_rows(registry)
    by_title = {row["title"]: row for row in rows}
    assert report.counts["ready"] == 1
    assert report.counts["needs-review"] == 1
    assert by_title["First"]["status"] == "ready"
    assert by_title["Duplicate"]["status"] == "needs-review"
    assert by_title["Duplicate"]["change_state"] == "needs-review"
    assert by_title["Duplicate"]["error_reason"] == f"duplicate_checksum:{first['source_id']}"
    assert by_title["Duplicate"]["provenance"]["duplicate_of_source_id"] == first["source_id"]
