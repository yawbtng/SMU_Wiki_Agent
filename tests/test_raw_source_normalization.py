from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.scrape_planner.sources.raw_source_normalizer import (
    normalize_pdf_pages,
    normalize_scraped_markdown,
    normalize_tabular_sources,
)
from src.scrape_planner.core.site_layout import ensure_site_layout
from src.scrape_planner.sources.source_registry import read_registry_rows, stable_source_id
from src.scrape_planner.core.storage import write_json


NOW = "2026-05-21T00:00:00+00:00"
LATER = "2026-05-21T01:00:00+00:00"


def test_web_scrape_markdown_is_copied_to_raw_sources_and_registered(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    run_root = site_root / "run-001"
    markdown = run_root / "markdown" / "home.md"
    metadata = run_root / "metadata" / "home.json"
    markdown.parent.mkdir(parents=True)
    metadata.parent.mkdir(parents=True)
    markdown.write_text("# Home\n\nAdmissions info.\n", encoding="utf-8")
    write_json(metadata, {"url": "https://example.edu/", "http_status": 200})
    write_json(
        run_root / "scrape_manifest.json",
        [
            {
                "url": "https://example.edu/",
                "status": "success",
                "markdown_path": str(markdown),
                "metadata_path": str(metadata),
                "fetch_mode": "fetcher",
            }
        ],
    )

    report = normalize_scraped_markdown(site_root, run_root, now=NOW)

    [row] = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    raw_markdown = site_root / row["markdown_path"]
    assert report.counts["ready"] == 1
    assert report.counts["new"] == 1
    assert row["source_kind"] == "web"
    assert row["original_url"] == "https://example.edu/"
    assert row["parser"] == "scrape_worker.markdown"
    assert raw_markdown.read_text(encoding="utf-8") == "# Home\n\nAdmissions info.\n"
    assert Path(report.report_path).exists()


def test_web_quality_gate_cleans_noisy_markdown_and_reports_counts(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    run_root = site_root / "run-001"
    markdown = run_root / "markdown" / "program.md"
    markdown.parent.mkdir(parents=True)
    markdown.write_text(
        "\n".join(
            [
                "Home",
                "Admissions",
                "Search",
                "# Program",
                "Application deadlines, tuition, and requirements are available for students.",
                "Application deadlines, tuition, and requirements are available for students.",
                "Application deadlines, tuition, and requirements are available for students.",
                "Privacy",
            ]
        ),
        encoding="utf-8",
    )
    write_json(
        run_root / "scrape_manifest.json",
        [{"url": "https://example.edu/program", "status": "success", "markdown_path": str(markdown)}],
    )

    report = normalize_scraped_markdown(site_root, run_root, now=NOW)

    [row] = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    raw_markdown = (site_root / row["markdown_path"]).read_text(encoding="utf-8")
    stored_report = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
    assert row["status"] == "ready"
    assert row["provenance"]["quality_action"] == "cleaned"
    assert "Home" not in raw_markdown
    assert stored_report["quality_summary"]["counts"]["cleaned"] == 1


def test_web_quality_gate_quarantines_pdf_markdown_with_diagnostic(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    run_root = site_root / "run-001"
    markdown = run_root / "markdown" / "catalog.md"
    markdown.parent.mkdir(parents=True)
    markdown.write_text("%PDF-1.4\n1 0 obj\nstream\n", encoding="utf-8")
    write_json(
        run_root / "scrape_manifest.json",
        [{"url": "https://example.edu/catalog", "status": "success", "markdown_path": str(markdown)}],
    )

    report = normalize_scraped_markdown(site_root, run_root, now=NOW)

    [row] = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    stored_report = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
    assert row["status"] == "failed"
    assert row["markdown_path"] == ""
    assert row["diagnostic_path"]
    assert (site_root / row["diagnostic_path"]).exists()
    assert stored_report["quality_summary"]["counts"]["quarantined"] == 1


def test_failed_pdf_manifest_with_web_successes_registers_pdf_failure(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    run_root = site_root / "run-mixed"
    run_root.mkdir(parents=True)
    for index in range(4):
        markdown = run_root / "markdown" / f"page{index}.md"
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(
            f"# Page {index}\n\nAdmissions, tuition, and enrollment requirements for students.\n",
            encoding="utf-8",
        )
    pdf_path = run_root / "pdf_downloads" / "handbook.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4")
    metadata = run_root / "metadata" / "handbook.json"
    metadata.parent.mkdir(parents=True)
    write_json(
        metadata,
        {
            "url": "https://example.edu/handbook.pdf",
            "fetch_mode": "pdf",
            "pdf_path": str(pdf_path),
            "pdf_quarantine": [{"reason": "low_text", "detail": "meaningful_chars=0 pages=1"}],
        },
    )
    write_json(
        run_root / "scrape_manifest.json",
        [
            {
                "url": f"https://example.edu/page{index}",
                "status": "success",
                "fetch_mode": "fetcher",
                "markdown_path": str(run_root / "markdown" / f"page{index}.md"),
            }
            for index in range(4)
        ]
        + [
            {
                "url": "https://example.edu/handbook.pdf",
                "status": "failed",
                "fetch_mode": "pdf",
                "failure_reason": "ocr_required",
                "metadata_path": str(metadata),
                "pdf_path": str(pdf_path),
                "raw_html_path": str(pdf_path),
            }
        ],
    )
    s05 = run_root / "s05"
    s05.mkdir(parents=True)
    (s05 / "pdf_sources.jsonl").write_text(
        json.dumps(
            {
                "pdf_source_id": "pdf-low-text",
                "path": str(pdf_path),
                "accepted": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (s05 / "pdf_quarantine.jsonl").write_text(
        json.dumps(
            {
                "pdf_source_id": "pdf-low-text",
                "path": str(pdf_path),
                "reason": "low_text",
                "detail": "meaningful_chars=0 pages=1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    web_report = normalize_scraped_markdown(site_root, run_root, now=NOW)
    pdf_report = normalize_pdf_pages(site_root, now=NOW)

    rows = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    web_rows = [row for row in rows if row["source_kind"] == "web"]
    pdf_rows = [row for row in rows if row["source_kind"] == "pdf"]

    assert web_report.counts["ready"] == 4
    assert len(web_rows) == 4
    assert len(pdf_rows) == 1
    assert pdf_report.counts["failed"] == 1
    assert pdf_rows[0]["status"] == "failed"
    assert pdf_rows[0]["original_url"] == "https://example.edu/handbook.pdf"
    assert pdf_rows[0]["error_reason"] in {"ocr_required", "low_text"}


def test_successful_pdf_scrape_without_markdown_path_is_skipped_by_web_normalizer(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    run_root = site_root / "run-001"
    metadata = run_root / "metadata" / "catalog.json"
    pdf_path = run_root / "pdf" / "catalog.pdf"
    metadata.parent.mkdir(parents=True)
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\n")
    write_json(metadata, {"url": "https://example.edu/catalog.pdf", "fetch_mode": "pdf"})
    write_json(
        run_root / "scrape_manifest.json",
        [
            {
                "url": "https://example.edu/catalog.pdf",
                "status": "success",
                "fetch_mode": "pdf",
                "metadata_path": str(metadata),
                "raw_html_path": str(pdf_path),
                "markdown_path": None,
            }
        ],
    )

    report = normalize_scraped_markdown(site_root, run_root, now=NOW)

    assert read_registry_rows(site_root / "raw_sources" / "registry.jsonl") == []
    assert report.sources == []
    assert report.counts["ready"] == 0
    assert report.counts["failed"] == 0
    assert Path(report.report_path).exists()


def test_scrape_manifest_markdown_path_escape_is_rejected_with_diagnostic(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    run_root = site_root / "run-001"
    escaped_markdown = tmp_path / "outside-run.md"
    escaped_markdown.write_text("# Outside\n\nDo not copy me.\n", encoding="utf-8")
    write_json(
        run_root / "scrape_manifest.json",
        [
            {
                "url": "https://example.edu/outside",
                "status": "success",
                "markdown_path": str(escaped_markdown),
            }
        ],
    )

    report = normalize_scraped_markdown(site_root, run_root, now=NOW)

    [row] = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    assert report.counts["failed"] == 1
    assert report.counts["ready"] == 0
    assert row["status"] == "failed"
    assert "outside run root" in row["error_reason"].lower()
    assert row["markdown_path"] == ""
    assert row["diagnostic_path"]
    assert (site_root / row["diagnostic_path"]).exists()
    assert not list((site_root / "raw_sources" / "web").glob("*.md"))


def test_pdf_page_markdown_is_normalized_as_page_level_raw_sources(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    page_dir = site_root / "sources" / "pdf_pages" / "pdf123"
    page_dir.mkdir(parents=True)
    page_1 = page_dir / "page-0001.md"
    page_2 = page_dir / "page-0002.md"
    page_1.write_text("# Catalog Page 1\n\nTuition.\n", encoding="utf-8")
    page_2.write_text("# Catalog Page 2\n\nFees.\n", encoding="utf-8")
    write_json(
        page_dir / "pages.json",
        [
            {
                "pdf_source_id": "pdf123",
                "source_path": "/uploads/catalog.pdf",
                "page_number": 1,
                "parser": "docling",
                "markdown_path": str(page_1),
            },
            {
                "pdf_source_id": "pdf123",
                "source_path": "/uploads/catalog.pdf",
                "page_number": 2,
                "parser": "docling",
                "markdown_path": str(page_2),
            },
        ],
    )

    report = normalize_pdf_pages(site_root, now=NOW)

    rows = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    assert report.counts["ready"] == 2
    assert len(rows) == 2
    assert {row["source_kind"] for row in rows} == {"pdf"}
    assert {row["original_path"] for row in rows} == {"/uploads/catalog.pdf"}
    assert {row["parser"] for row in rows} == {"docling"}
    raw_markdowns = [(site_root / row["markdown_path"]).read_text(encoding="utf-8") for row in rows]
    assert any("Catalog Page 1" in text for text in raw_markdowns)
    assert any("Catalog Page 2" in text for text in raw_markdowns)
    assert not any("Catalog Page 1" in text and "Catalog Page 2" in text for text in raw_markdowns)
    metadata = json.loads((site_root / rows[0]["metadata_path"]).read_text(encoding="utf-8"))
    assert metadata["source_type"] == "document-page"
    assert metadata["page_count"] == 1
    assert metadata["document_page_count"] == 2
    assert metadata["source_pages"][0]["page_number"] in {1, 2}


def test_pdf_page_normalization_preserves_sections_tables_and_quality(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    page_dir = site_root / "sources" / "pdf_pages" / "pdf-table"
    page_dir.mkdir(parents=True)
    page_1 = page_dir / "page-0001.md"
    page_1.write_text(
        "# Graduate Catalog\n\n## Tuition\n\n| Program | Cost |\n| --- | --- |\n| MBA | 100 |\n",
        encoding="utf-8",
    )
    write_json(
        page_dir / "pages.json",
        [
            {
                "pdf_source_id": "pdf-table",
                "source_path": "/uploads/catalog.pdf",
                "page_number": 1,
                "parser": "docling",
                "markdown_path": str(page_1),
            }
        ],
    )

    normalize_pdf_pages(site_root, now=NOW)

    [row] = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    metadata = json.loads((site_root / row["metadata_path"]).read_text(encoding="utf-8"))
    assert metadata["source_type"] == "document-page"
    assert metadata["source_pages"][0]["page_start"] == 1
    assert metadata["source_pages"][0]["section_path"] == "Graduate Catalog > Tuition"
    assert metadata["tables"][0]["table_id"] == "p0001-t001"
    assert metadata["tables_path"]
    assert metadata["document_quality"]["table_count"] == 1
    assert metadata["document_quality"]["page_coverage_count"] == 1


def test_pdf_chunk_fallback_preserves_chunk_provenance_warnings_and_tables(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    ingest_dir = site_root / "sources" / "pdf_ingest"
    ingest_dir.mkdir(parents=True)
    pdf_path = tmp_path / "catalog.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    (ingest_dir / "pdf_sources.jsonl").write_text(
        json.dumps(
            {
                "pdf_source_id": "pdf-chunks",
                "path": str(pdf_path),
                "parser": "docling",
                "warning": "table confidence low",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (ingest_dir / "pdf_chunks.jsonl").write_text(
        json.dumps(
            {
                "chunk_id": "chunk-1",
                "pdf_source_id": "pdf-chunks",
                "source_path": str(pdf_path),
                "parser": "docling",
                "page_number": 4,
                "chunk_index": 2,
                "section_path": "Catalog > Aid",
                "text": "| Aid | Amount |\n| --- | --- |\n| Grant | 10 |",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    normalize_pdf_pages(site_root, now=NOW)

    [row] = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    metadata = json.loads((site_root / row["metadata_path"]).read_text(encoding="utf-8"))
    assert row["source_kind"] == "pdf"
    assert metadata["source_chunks"][0]["page_start"] == 4
    assert metadata["source_chunks"][0]["section_path"] == "Catalog > Aid"
    assert metadata["tables"][0]["table_id"] == "p0004-t001"
    assert "table confidence low" in metadata["extraction_warnings"]


def test_csv_source_is_rendered_as_markdown_table(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    csv_path = tmp_path / "programs.csv"
    csv_path.write_text("Program,Tuition\nMBA,100\nMSCS,80\n", encoding="utf-8")

    report = normalize_tabular_sources(site_root, [csv_path], now=NOW)

    [row] = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    assert report.counts["ready"] == 1
    assert row["source_kind"] == "excel"
    assert row["parser"] == "pandas.csv"
    raw_markdown = (site_root / row["markdown_path"]).read_text(encoding="utf-8")
    assert "| Program | Tuition |" in raw_markdown
    assert "| MBA | 100 |" in raw_markdown


def test_empty_csv_is_registered_for_review_with_diagnostic(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("", encoding="utf-8")

    report = normalize_tabular_sources(site_root, [csv_path], now=NOW)

    [row] = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    assert report.counts["needs-review"] == 1
    assert row["status"] == "needs-review"
    assert row["error_reason"]
    assert row["diagnostic_path"]
    assert (site_root / row["diagnostic_path"]).exists()


def test_blank_cell_csv_rows_are_registered_for_review_with_diagnostic(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    csv_path = tmp_path / "blank-rows.csv"
    csv_path.write_text("Program,Tuition\n , \n\t,   \n", encoding="utf-8")

    report = normalize_tabular_sources(site_root, [csv_path], now=NOW)

    [row] = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    assert report.counts["needs-review"] == 1
    assert row["status"] == "needs-review"
    assert "meaningful" in row["error_reason"].lower()
    assert row["diagnostic_path"]
    assert (site_root / row["diagnostic_path"]).exists()


def test_excel_source_is_rendered_as_sheet_markdown(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    pd = pytest.importorskip("pandas")
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    xlsx_path = tmp_path / "programs.xlsx"
    pd.DataFrame([{"Program": "MBA", "Tuition": 100}]).to_excel(xlsx_path, index=False, sheet_name="Programs")

    report = normalize_tabular_sources(site_root, [xlsx_path], now=NOW)

    [row] = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    assert report.counts["ready"] == 1
    assert row["source_kind"] == "excel"
    assert row["parser"] == "pandas.excel"
    raw_markdown = (site_root / row["markdown_path"]).read_text(encoding="utf-8")
    assert "# Programs" in raw_markdown
    assert "| Program | Tuition |" in raw_markdown
    assert "| MBA | 100 |" in raw_markdown


def test_failed_tabular_normalization_writes_registry_and_diagnostic(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root

    report = normalize_tabular_sources(site_root, [tmp_path / "missing.csv"], now=NOW)

    [row] = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    assert report.counts["failed"] == 1
    assert row["status"] == "failed"
    assert row["error_reason"] == "File does not exist"
    assert (site_root / row["diagnostic_path"]).exists()


def test_quarantined_pdf_without_chunks_is_registered_with_diagnostic(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    ingest_dir = site_root / "sources" / "pdf_ingest"
    ingest_dir.mkdir(parents=True)
    pdf_path = tmp_path / "catalog.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 broken")
    (ingest_dir / "pdf_sources.jsonl").write_text(
        json.dumps(
            {
                "pdf_source_id": "pdf-empty",
                "path": str(pdf_path),
                "parser": "docling",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (ingest_dir / "pdf_chunks.jsonl").write_text("", encoding="utf-8")
    (ingest_dir / "pdf_quarantine.jsonl").write_text(
        json.dumps(
            {
                "pdf_source_id": "pdf-empty",
                "path": str(pdf_path),
                "parser": "docling",
                "error_reason": "No extractable text",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = normalize_pdf_pages(site_root, now=NOW)

    [row] = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    assert report.counts["failed"] == 1
    assert row["source_kind"] == "pdf"
    assert row["status"] == "failed"
    assert row["error_reason"]
    assert row["diagnostic_path"]
    assert (site_root / row["diagnostic_path"]).exists()


def test_run_local_quarantined_pdf_without_chunks_is_registered_with_diagnostic(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    s05_dir = site_root / "run-001" / "s05"
    s05_dir.mkdir(parents=True)
    pdf_path = tmp_path / "run-catalog.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 broken")
    (s05_dir / "pdf_sources.jsonl").write_text(
        json.dumps(
            {
                "pdf_source_id": "run-pdf-empty",
                "path": str(pdf_path),
                "parser": "docling",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (s05_dir / "pdf_quarantine.jsonl").write_text(
        json.dumps(
            {
                "pdf_source_id": "run-pdf-empty",
                "path": str(pdf_path),
                "parser": "docling",
                "error_reason": "Docling parse failed",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = normalize_pdf_pages(site_root, now=NOW)

    [row] = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    assert report.counts["failed"] == 1
    assert row["source_kind"] == "pdf"
    assert row["status"] == "failed"
    assert row["original_path"] == str(pdf_path)
    assert row["error_reason"] == "Docling parse failed"
    assert row["diagnostic_path"]
    assert (site_root / row["diagnostic_path"]).exists()
    assert row["provenance"]["pdf_quarantine_path"].endswith("run-001/s05/pdf_quarantine.jsonl")


def test_same_run_local_pdf_url_uses_one_stable_source_id_across_s05_runs(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    original_url = "https://example.edu/catalog.pdf"
    expected_source_id = stable_source_id("pdf", original_url)

    for run_name, local_name, chunk_text in (
        ("run-001", "catalog-a.pdf", "Catalog tuition and admission requirements version one."),
        ("run-002", "catalog-b.pdf", "Catalog tuition and admission requirements version two."),
    ):
        s05_dir = site_root / run_name / "s05"
        s05_dir.mkdir(parents=True)
        pdf_path = s05_dir / local_name
        pdf_path.write_bytes(b"%PDF-1.4\n")
        (s05_dir / "pdf_sources.jsonl").write_text(
            json.dumps(
                {
                    "pdf_source_id": f"{run_name}-pdf",
                    "path": str(pdf_path),
                    "url": original_url,
                    "parser": "docling",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (s05_dir / "pdf_chunks.jsonl").write_text(
            json.dumps(
                {
                    "chunk_id": f"{run_name}-chunk",
                    "pdf_source_id": f"{run_name}-pdf",
                    "source_path": str(pdf_path),
                    "url": original_url,
                    "parser": "docling",
                    "text": chunk_text,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    report = normalize_pdf_pages(site_root, now=NOW)
    [first_row] = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    first_raw_markdown = site_root / first_row["markdown_path"]

    run_002_chunk = site_root / "run-002" / "s05" / "pdf_chunks.jsonl"
    run_002_chunk.write_text(
        json.dumps(
            {
                "chunk_id": "run-002-chunk",
                "pdf_source_id": "run-002-pdf",
                "source_path": str(site_root / "run-002" / "s05" / "catalog-b.pdf"),
                "url": original_url,
                "parser": "docling",
                "text": "Catalog tuition and admission requirements version three.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    changed = normalize_pdf_pages(site_root, now=LATER)

    rows = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    assert report.counts["ready"] == 1
    assert [row["source_id"] for row in rows] == [expected_source_id]
    assert rows[0]["original_url"] == original_url
    assert rows[0]["source_kind"] == "pdf"
    assert "version two" in first_raw_markdown.read_text(encoding="utf-8")
    assert changed.counts["changed"] == 1
    assert rows[0]["change_state"] == "changed"
    assert rows[0]["checksum"] != first_row["checksum"]
    assert "version three" in (site_root / rows[0]["markdown_path"]).read_text(encoding="utf-8")


def test_tabular_relative_and_absolute_path_use_same_source_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    csv_path = tmp_path / "programs.csv"
    csv_path.write_text("Program,Tuition\nMBA,100\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    report = normalize_tabular_sources(site_root, [Path("programs.csv"), csv_path.resolve()], now=NOW)

    rows = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    assert report.counts["ready"] == 1
    assert len(rows) == 1
    assert rows[0]["source_id"] == stable_source_id("excel", str(csv_path.resolve()))
    assert rows[0]["original_path"] == str(csv_path.resolve())


def test_incremental_normalization_reports_unchanged_then_changed(tmp_path: Path) -> None:
    site_root = ensure_site_layout(tmp_path, "site-1").site_root
    run_root = site_root / "run-001"
    markdown = run_root / "markdown" / "home.md"
    markdown.parent.mkdir(parents=True)
    markdown.write_text("# Home\n\nVersion 1.\n", encoding="utf-8")
    write_json(
        run_root / "scrape_manifest.json",
        [{"url": "https://example.edu/", "status": "success", "markdown_path": str(markdown)}],
    )

    normalize_scraped_markdown(site_root, run_root, now=NOW)
    [first_row] = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    first_raw_path = site_root / first_row["markdown_path"]
    unchanged = normalize_scraped_markdown(site_root, run_root, now=LATER)
    markdown.write_text("# Home\n\nVersion 2.\n", encoding="utf-8")
    changed = normalize_scraped_markdown(site_root, run_root, now="2026-05-21T02:00:00+00:00")

    [row] = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    assert unchanged.counts["unchanged"] == 1
    assert changed.counts["changed"] == 1
    assert row["change_state"] == "changed"
    assert row["markdown_path"] != first_row["markdown_path"]
    assert first_raw_path.read_text(encoding="utf-8") == "# Home\n\nVersion 1.\n"
    assert (site_root / row["markdown_path"]).read_text(encoding="utf-8") == "# Home\n\nVersion 2.\n"


def test_raw_source_normalizer_cli_runs_without_input_and_writes_report(tmp_path: Path) -> None:
    site_root = tmp_path / "site"
    run_root = site_root / "run-001"
    markdown = run_root / "markdown" / "home.md"
    markdown.parent.mkdir(parents=True)
    markdown.write_text("# Home\n\nAdmissions info.\n", encoding="utf-8")
    (run_root / "scrape_manifest.json").write_text(
        json.dumps([{"url": "https://example.edu/", "status": "success", "markdown_path": str(markdown)}]),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.scrape_planner.sources.raw_source_normalizer",
            "--site-root",
            str(site_root),
            "--kind",
            "web",
            "--run-root",
            str(run_root),
            "--no-input",
        ],
        input="",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    assert (site_root / "raw_sources" / "registry.jsonl").exists()
    assert json.loads(result.stdout)["mode"] == "web"
    assert json.loads(result.stdout)["no_input"] is True
    assert "input(" not in result.stderr.lower()
