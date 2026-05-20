from src.scrape_planner.url_quality import UrlCriteria, UrlScoringProfile, score_and_filter_rows, score_url_row, suggest_scoring_profile_from_rows


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


def test_manual_github_package_url_is_selected_by_default():
    rows = [
        {
            "url": "https://github.com/earendil-works/pi/tree/main/packages/agent",
            "source_sitemap": "manual",
        }
    ]

    scored, counts = score_and_filter_rows(rows, UrlCriteria(threshold=70))

    assert counts["selected"] == 1
    assert scored[0]["selected"] is True
    assert scored[0]["url"] == "https://github.com/earendil-works/pi/tree/main/packages/agent"


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


def test_custom_university_profile_changes_selection_terms():
    profile = UrlScoringProfile.from_dict(
        {
            "high_value_terms": ["bursar", "student-accounts"],
            "spammy_terms": ["athletics"],
            "high_value_student_boost": 40,
            "spammy_student_penalty": 45,
        }
    )

    bursar = score_url_row({"url": "https://example.edu/bursar/payment-plans"}, profile=profile)
    athletics = score_url_row({"url": "https://example.edu/athletics/tickets"}, profile=profile)

    assert bursar["score"] > athletics["score"]
    assert bursar["score"] >= 70
    assert athletics["spammy"] is True


def test_score_and_filter_uses_custom_profile():
    rows = [
        {"url": "https://example.edu/bursar/payment-plans"},
        {"url": "https://example.edu/athletics/tickets"},
    ]
    profile = UrlScoringProfile.from_dict({"high_value_terms": ["bursar"], "spammy_terms": ["athletics"], "high_value_student_boost": 40})
    scored, counts = score_and_filter_rows(rows, UrlCriteria(threshold=70), profile=profile)

    assert counts["selected"] == 1
    assert [row["url"] for row in scored if row["selected"]] == ["https://example.edu/bursar/payment-plans"]


def test_scrape_first_selects_generic_pages_and_excludes_only_junk():
    rows = [
        {"url": "https://www.smu.edu/about/contact"},
        {"url": "https://www.smu.edu/search?q=tuition"},
        {"url": "https://www.smu.edu/calendar/2019/04/open-house"},
    ]
    scored, counts = score_and_filter_rows(rows, UrlCriteria(max_urls=50, threshold=95, scrape_first=True))

    selected_urls = [row["url"] for row in scored if row["selected"]]
    assert counts["selected"] == 1
    assert selected_urls == ["https://www.smu.edu/about/contact"]
    assert all(row["selection_source"] == "deterministic_exclusion" for row in scored if row["selected"])


def test_scrape_first_keeps_lower_priority_institutional_pages():
    rows = [
        {"url": "https://www.smu.edu/alumni/giving"},
        {"url": "https://www.smu.edu/trustees/annual-report.pdf"},
        {"url": "https://www.smu.edu/search?q=tuition"},
    ]
    scored, counts = score_and_filter_rows(rows, UrlCriteria(max_urls=50, scrape_first=True))

    selected_urls = {row["url"] for row in scored if row["selected"]}
    assert counts["selected"] == 2
    assert "https://www.smu.edu/alumni/giving" in selected_urls
    assert "https://www.smu.edu/trustees/annual-report.pdf" in selected_urls
    assert "https://www.smu.edu/search?q=tuition" not in selected_urls


def test_focus_terms_are_optional_in_scrape_first_mode():
    rows = [
        {"url": "https://www.smu.edu/about/contact"},
        {"url": "https://www.smu.edu/registrar/transcripts"},
    ]

    broad, _ = score_and_filter_rows(rows, UrlCriteria(scrape_first=True))
    focused, _ = score_and_filter_rows(rows, UrlCriteria(include_text="registrar", scrape_first=True))

    assert {row["url"] for row in broad if row["selected"]} == {
        "https://www.smu.edu/about/contact",
        "https://www.smu.edu/registrar/transcripts",
    }
    assert [row["url"] for row in focused if row["selected"]] == ["https://www.smu.edu/registrar/transcripts"]


def test_suggest_profile_uses_terms_seen_in_discovered_urls():
    rows = [
        {"url": "https://college.example.edu/student-accounts/payment-plans"},
        {"url": "https://college.example.edu/search?q=tuition"},
        {"url": "https://college.example.edu/tag/scholarships"},
    ]

    profile = suggest_scoring_profile_from_rows(rows, base_profile=UrlScoringProfile.from_dict({"high_value_terms": ["student-accounts"], "spammy_terms": []}))

    assert "student-accounts" in profile.high_value_terms
    assert "search" in profile.spammy_terms
    assert "tag/" in profile.spammy_terms


def test_suggest_profile_does_not_force_unseen_default_noise_terms():
    rows = [{"url": "https://college.example.edu/student-accounts/payment-plans"}]

    profile = suggest_scoring_profile_from_rows(rows, base_profile=UrlScoringProfile.from_dict({"spammy_terms": ["search", "alumni"]}))

    assert "search" not in profile.spammy_terms
    assert "alumni" not in profile.spammy_terms
