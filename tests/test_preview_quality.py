from __future__ import annotations

from src.scrape_planner.ui_preview_quality import (
    build_chunk_quality_summary,
    classify_chunk_sample,
)


def test_short_headingless_chunk_is_flagged_as_low_quality() -> None:
    result = classify_chunk_sample(
        text="Apply now",
        source_title="Admissions",
        section_path=[],
        previous_text="",
        next_text="",
    )

    assert result.quality == "poor"
    assert "too_short" in result.flags
    assert "missing_section_context" in result.flags


def test_pdf_header_fragment_is_flagged_as_boilerplate() -> None:
    result = classify_chunk_sample(
        text="Southern Methodist University Undergraduate Catalog 2024-2025 Page 17",
        source_title="Catalog",
        section_path=["Catalog"],
        previous_text="",
        next_text="",
    )

    assert result.quality in {"poor", "needs_review"}
    assert "boilerplate" in result.flags


def test_good_chunk_includes_reason_and_context() -> None:
    result = classify_chunk_sample(
        text=(
            "Students applying to the Cox School of Business must complete the university "
            "application, submit official transcripts, and meet program-specific prerequisites."
        ),
        source_title="Cox Admissions",
        section_path=["Admissions", "Undergraduate Requirements"],
        previous_text="Admission overview",
        next_text="Application deadlines",
    )

    assert result.quality == "good"
    assert result.reason
    assert result.context_label == "Admissions > Undergraduate Requirements"


def test_quality_summary_blocks_ready_state_when_bad_samples_dominate() -> None:
    summary = build_chunk_quality_summary(
        [
            {"text": "Apply now", "source_title": "Admissions", "section_path": []},
            {"text": "Page 17", "source_title": "Catalog", "section_path": ["Catalog"]},
            {
                "text": "Financial aid applications require FAFSA submission and school-specific forms.",
                "source_title": "Financial Aid",
                "section_path": ["Financial Aid"],
            },
        ]
    )

    assert summary.readiness == "needs_review"
    assert summary.poor_count == 2
    assert summary.ready_for_retrieval is False
