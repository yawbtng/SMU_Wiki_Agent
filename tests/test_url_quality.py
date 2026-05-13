from src.scrape_planner.url_quality import UrlCriteria, score_and_filter_rows, score_url_row


def test_student_pages_score_above_spammy_archives():
    useful = score_url_row({"url": "https://www.smu.edu/admission/apply", "lastmod": "2026-04-01T00:00:00Z"})
    spammy = score_url_row({"url": "https://www.smu.edu/news/2019/04/old-story?page=2"})

    assert useful["score"] > spammy["score"]
    assert useful["score"] >= 70
    assert spammy["spammy"] is True


def test_manual_pdfs_are_kept_as_high_value_sources():
    scored = score_url_row({"url": "https://www.smu.edu/catalog/graduate.pdf", "source_sitemap": "manual"})

    assert scored["is_pdf"] is True
    assert scored["score"] >= 70


def test_filter_criteria_applies_include_exclude_and_cap():
    rows = [
        {"url": "https://www.smu.edu/admission/apply"},
        {"url": "https://www.smu.edu/registrar/transcripts"},
        {"url": "https://www.smu.edu/alumni/giving"},
    ]
    scored, counts = score_and_filter_rows(
        rows,
        UrlCriteria(include_text="admission, registrar", exclude_text="alumni", max_urls=1, threshold=60),
    )

    selected = [row for row in scored if row["selected"]]
    assert counts["total"] == 3
    assert counts["selected"] == 1
    assert len(selected) == 1
    assert selected[0]["url"] == "https://www.smu.edu/admission/apply"
