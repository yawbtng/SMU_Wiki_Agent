from __future__ import annotations

from src.scrape_planner.wiki.leadership import extract_leadership_from_evidence, leadership_text_boost


def test_extract_leadership_from_faculty_carousel_snippet() -> None:
    evidence = [
        {
            "title": "M.S. Network Engineering",
            "snippet": "M. Scott Kingsley, Eng.D. — Director of Graduate Network Engineering Program",
            "path": "wiki/pages/programs/ms-network-engineering.md",
            "source_id": "web_ms_net",
        }
    ]
    match = extract_leadership_from_evidence("Who is the director of SMU networking?", evidence)

    assert match is not None
    assert "Kingsley" in match.name
    assert "Network Engineering" in match.role
    assert "Director" in match.answer


def test_extract_chairperson_from_endowed_faculty_snippet() -> None:
    evidence = [
        {
            "title": "Department Faculty",
            "snippet": (
                "Avery Morgan, Ph.D. Distinguished University Chairperson of the "
                "Department of Data Science Riley Patel, Ph.D. Associate Chair of Data Science"
            ),
            "path": "raw_sources/web/faculty.md",
            "source_id": "faculty",
        }
    ]
    match = extract_leadership_from_evidence("Who leads the Department of Data Science?", evidence)

    assert match is not None
    assert match.name == "Avery Morgan"
    assert "Chairperson" in match.answer
    assert "Department of Data Science" in match.role


def test_social_networking_page_is_penalized() -> None:
    boost, reasons = leadership_text_boost(
        "director networking",
        "Networking Social Events",
        "Career networking happy hour for alumni.",
    )

    assert boost < 0
    assert "social_networking_penalty" in reasons
