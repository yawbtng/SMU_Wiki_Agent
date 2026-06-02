from src.scrape_planner.scrape.url_policy import classify_url_for_student_wiki


def test_class_notes_are_hard_rejected_even_with_recent_lastmod():
    decision = classify_url_for_student_wiki(
        "https://www.smu.edu/cox/coxtoday-magazine/2023-01-31-smu-cox-class-notes-fall-2022",
        lastmod="2026-01-01T00:00:00Z",
    )

    assert decision.selected is False
    assert decision.reason == "class_or_alumni_notes"
    assert decision.severity == "hard_reject"


def test_old_dated_news_is_hard_rejected_even_with_recent_lastmod():
    decision = classify_url_for_student_wiki(
        "https://www.smu.edu/cox/coxtoday-magazine/2023-03-27-silicon-valley-bank-failure",
        lastmod="2026-01-01T00:00:00Z",
    )

    assert decision.selected is False
    assert decision.reason == "old_dated_news_or_article"


def test_compact_old_dated_story_is_rejected():
    decision = classify_url_for_student_wiki("https://www.smu.edu/cox/20200508-leading-in-unprecedented-times")

    assert decision.selected is False
    assert decision.reason == "old_year_specific_noncanonical_page"


def test_current_canonical_student_page_is_allowed():
    decision = classify_url_for_student_wiki("https://www.smu.edu/enrollment-services/registrar/academic-calendar/final-exam-schedules")

    assert decision.selected is True
    assert decision.reason == "student_canonical_allowlist"


def test_brand_marketing_pages_are_rejected():
    decision = classify_url_for_student_wiki("https://www.smu.edu/brand/logos")

    assert decision.selected is False
    assert decision.reason == "draft_test_or_template"


def test_donor_and_admin_pages_are_hard_rejected():
    assert classify_url_for_student_wiki("https://www.smu.edu/aboutsmu/annual-report/2024/letter-from-the-president").selected is False
    assert classify_url_for_student_wiki("https://www.smu.edu/aboutsmu/administration/board-of-trustees").selected is False


def test_stale_course_schedule_on_allowlisted_path_is_rejected():
    decision = classify_url_for_student_wiki(
        "https://www.smu.edu/enrollment-services/registrar/course-schedule/fall-2023"
    )

    assert decision.selected is False
    assert decision.reason == "dated_archive_page"
