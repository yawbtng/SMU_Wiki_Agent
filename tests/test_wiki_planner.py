from __future__ import annotations

import json
from pathlib import Path

from src.scrape_planner.claude_manifest import build_claude_manifest
from src.scrape_planner.ui_navigation import WORKFLOW_TABS
from src.scrape_planner.wiki_planner import normalize_corpus_sources, suggest_wiki_topics


def test_normalize_corpus_sources_prefers_cleaned_markdown_and_includes_document_ingest(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    cleaned_path = run_root / "cleaned" / "finance.md"
    cleaned_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned_path.write_text("Tuition and financial aid deadlines for students.", encoding="utf-8")

    scrape_path = run_root / "markdown" / "finance-raw.md"
    scrape_path.parent.mkdir(parents=True, exist_ok=True)
    scrape_path.write_text("Older scrape markdown that should be ignored when cleaned markdown exists.", encoding="utf-8")

    doc_path = run_root / "document_ingest" / "converted_markdown" / "admissions-handbook.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text("Admissions application requirements and scholarship rules.", encoding="utf-8")

    (run_root / "cleanup_manifest.json").write_text(
        json.dumps(
            [
                {
                    "url": "https://example.edu/tuition",
                    "status": "cleaned",
                    "title": "Tuition",
                    "cleaned_markdown_path": str(cleaned_path),
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_root / "scrape_manifest.json").write_text(
        json.dumps(
            [
                {
                    "url": "https://example.edu/tuition",
                    "status": "success",
                    "markdown_path": str(scrape_path),
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_root / "document_ingest" / "manifest.json").write_text(
        json.dumps(
            [
                {
                    "status": "converted",
                    "title": "Admissions Handbook",
                    "source_path": str(run_root / "sources" / "admissions-handbook.pdf"),
                    "converted_markdown_path": str(doc_path),
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    sources = normalize_corpus_sources(run_root)

    assert [(row["source_type"], row["path"]) for row in sources] == [
        ("cleaned_markdown", str(cleaned_path)),
        ("document_markdown", str(doc_path)),
    ]
    assert sources[0]["url"] == "https://example.edu/tuition"
    assert "financial aid" in sources[0]["text"].lower()
    assert sources[1]["title"] == "Admissions Handbook"


def test_suggest_wiki_topics_uses_normalized_corpus_sources(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    finance_path = run_root / "cleaned" / "finance.md"
    finance_path.parent.mkdir(parents=True, exist_ok=True)
    finance_path.write_text("Tuition payment deadlines and billing support for students.", encoding="utf-8")

    admissions_path = run_root / "document_ingest" / "converted_markdown" / "admissions.md"
    admissions_path.parent.mkdir(parents=True, exist_ok=True)
    admissions_path.write_text("Admissions application requirements and deadline checklist.", encoding="utf-8")

    (run_root / "cleanup_manifest.json").write_text(
        json.dumps(
            [
                {
                    "url": "https://example.edu/tuition",
                    "status": "cleaned",
                    "cleaned_markdown_path": str(finance_path),
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_root / "document_ingest" / "manifest.json").write_text(
        json.dumps(
            [
                {
                    "status": "converted",
                    "title": "Admissions",
                    "converted_markdown_path": str(admissions_path),
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    result = suggest_wiki_topics(run_root)

    assert result["source_count"] == 2
    topics = {row["topic"]: row for row in result["topics"]}
    assert topics["Finance Wiki"]["selected"] is True
    assert topics["Admissions Wiki"]["selected"] is True


def test_build_claude_manifest_uses_normalized_corpus_sources(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    cleaned_path = run_root / "cleaned" / "finance.md"
    cleaned_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned_path.write_text("Tuition and financial aid", encoding="utf-8")

    doc_path = run_root / "document_ingest" / "converted_markdown" / "catalog.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text("Admissions and scholarship catalog", encoding="utf-8")

    (run_root / "cleanup_manifest.json").write_text(
        json.dumps(
            [
                {
                    "url": "https://example.edu/tuition",
                    "status": "cleaned",
                    "title": "Finance",
                    "cleaned_markdown_path": str(cleaned_path),
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_root / "document_ingest" / "manifest.json").write_text(
        json.dumps(
            [
                {
                    "status": "converted",
                    "title": "Catalog",
                    "source_path": str(run_root / "sources" / "catalog.pdf"),
                    "converted_markdown_path": str(doc_path),
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_root / "failures.json").write_text(json.dumps([{"url": "https://example.edu/broken"}], indent=2), encoding="utf-8")

    manifest = build_claude_manifest(run_root, "https://example.edu", "run-123")

    assert manifest["counts"] == {"success": 2, "failed": 1}
    assert [(row["source_type"], row["markdown_path"]) for row in manifest["successful_pages"]] == [
        ("cleaned_markdown", str(cleaned_path)),
        ("document_markdown", str(doc_path)),
    ]


def test_workflow_tabs_include_corpus_stage() -> None:
    assert "Corpus" in WORKFLOW_TABS
    assert "Choose URLs" not in WORKFLOW_TABS
    assert WORKFLOW_TABS == ["Setup", "Discover", "Scrape", "Corpus", "Graph", "Settings"]
