from __future__ import annotations

from src.scrape_planner.ui_preview_quality import (
    build_chunk_quality_summary,
    classify_chunk_row,
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


def test_real_pdf_chunk_metadata_counts_as_context_without_section_path() -> None:
    result = classify_chunk_row(
        {
            "source_path": "/tmp/catalogs/graduate-catalog.pdf",
            "page_number": 42,
            "markdown_path": "/tmp/catalogs/pages/page-0042.md",
            "pdf_source_id": "graduate-catalog",
            "source_title": "Graduate Catalog",
            "text": (
                "The Master of Science program requires students to complete core coursework, "
                "approved electives, and a culminating project under faculty supervision."
            ),
            "char_count": 148,
        }
    )

    assert result.quality == "good"
    assert "missing_section_context" not in result.flags
    assert "Graduate Catalog" in result.context_label
    assert "Page 42" in result.context_label


def test_quality_summary_marks_meaningful_real_pdf_chunks_ready() -> None:
    rows = [
        {
            "source_path": f"/tmp/catalogs/catalog-{idx}.pdf",
            "page_number": idx,
            "markdown_path": f"/tmp/catalogs/pages/page-{idx:04d}.md",
            "pdf_source_id": f"catalog-{idx}",
            "source_title": "Academic Catalog",
            "text": (
                "Students must complete the required credit hours, maintain satisfactory academic "
                "standing, and consult their advisor before filing a degree plan."
            ),
            "char_count": 146,
        }
        for idx in range(1, 5)
    ]

    summary = build_chunk_quality_summary(rows)

    assert summary.readiness == "ready"
    assert summary.ready_for_retrieval is True
    assert summary.good_count == 4
    assert summary.poor_count == 0
    assert "missing_section_context" not in summary.top_flags


def test_quality_summary_still_blocks_when_poor_real_pdf_chunks_dominate() -> None:
    rows = [
        {
            "source_path": "/tmp/catalogs/catalog.pdf",
            "page_number": 1,
            "markdown_path": "/tmp/catalogs/pages/page-0001.md",
            "pdf_source_id": "catalog",
            "source_title": "Academic Catalog",
            "text": "Apply now",
            "char_count": 9,
        },
        {
            "source_path": "/tmp/catalogs/catalog.pdf",
            "page_number": 2,
            "markdown_path": "/tmp/catalogs/pages/page-0002.md",
            "pdf_source_id": "catalog",
            "source_title": "Academic Catalog",
            "text": "Page 2",
            "char_count": 6,
        },
        {
            "source_path": "/tmp/catalogs/catalog.pdf",
            "page_number": 3,
            "markdown_path": "/tmp/catalogs/pages/page-0003.md",
            "pdf_source_id": "catalog",
            "source_title": "Academic Catalog",
            "text": (
                "Degree candidates complete a coherent set of courses and must satisfy all "
                "published academic policies before graduation."
            ),
            "char_count": 121,
        },
    ]

    summary = build_chunk_quality_summary(rows)

    assert summary.readiness == "needs_review"
    assert summary.ready_for_retrieval is False
    assert summary.poor_count == 2
