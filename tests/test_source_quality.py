from __future__ import annotations

import json
from pathlib import Path

from src.scrape_planner.source_quality import assess_source_quality, strip_repeated_chrome, write_quality_report


def test_pdf_signature_is_quarantined_with_pdf_parser_route() -> None:
    record = assess_source_quality("%PDF-1.7\n1 0 obj\nstream\nbinary", source_id="web_pdf", parser_kind="markdown")

    assert record.action == "quarantined"
    assert "starts_with_pdf_signature" in record.reasons
    assert record.recommended_parser_route == "pdf"


def test_nul_byte_is_quarantined() -> None:
    record = assess_source_quality("# Page\n\nGood text\x00bad text", source_id="web_nul")

    assert record.action == "quarantined"
    assert "contains_nul_byte" in record.reasons


def test_redirect_stub_is_quarantined() -> None:
    record = assess_source_quality("You are being redirected. Click here if you are not redirected.", source_id="web_redirect")

    assert record.action == "quarantined"
    assert "redirect_stub" in record.reasons


def test_low_content_without_structured_signal_needs_review() -> None:
    record = assess_source_quality("# Tiny\n\nWelcome.", source_id="web_tiny")

    assert record.action == "needs_review"
    assert "low_word_count" in record.reasons


def test_useful_short_contact_page_is_approved() -> None:
    text = "# Contact\n\nEmail admissions@example.edu or call 214-555-1212.\n"

    record = assess_source_quality(text, source_id="web_contact")

    assert record.action == "approved"


def test_repeated_chrome_is_stripped_and_marked_cleaned() -> None:
    text = "\n".join(
        [
            "Home",
            "Admissions",
            "Search",
            "# Program",
            "This program has application deadlines, tuition details, and requirements for students.",
            "This program has application deadlines, tuition details, and requirements for students.",
            "This program has application deadlines, tuition details, and requirements for students.",
            "Privacy",
            "Copyright",
        ]
    )

    record = assess_source_quality(text, source_id="web_noisy")
    cleaned = strip_repeated_chrome(text)

    assert record.action == "cleaned"
    assert "Home" not in cleaned
    assert "Privacy" not in cleaned
    assert "Program" in cleaned


def test_duplicate_checksum_is_reported() -> None:
    first = assess_source_quality("# Admissions\n\nApplication deadline and tuition details.", source_id="first")
    duplicate = assess_source_quality(
        "# Admissions\n\nApplication deadline and tuition details.",
        source_id="second",
        seen_checksums={first.checksum},
    )

    assert duplicate.duplicate_checksum is True
    assert "duplicate_checksum" in duplicate.reasons


def test_quality_report_contains_counts_and_examples(tmp_path: Path) -> None:
    rows = [
        assess_source_quality("# Contact\n\nEmail admissions@example.edu.", source_id="approved"),
        assess_source_quality("%PDF-1.4", source_id="bad"),
    ]

    report = write_quality_report(tmp_path / "quality.json", generated_at="2026-05-22T00:00:00+00:00", records=rows)

    stored = json.loads((tmp_path / "quality.json").read_text(encoding="utf-8"))
    assert report["summary"]["counts"]["approved"] == 1
    assert report["summary"]["counts"]["quarantined"] == 1
    assert stored["sources"][1]["source_id"] == "bad"
