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


def test_presidential_scholarship_is_allowed_but_president_office_is_rejected():
    scholarship = classify_url_for_student_wiki("https://www.smu.edu/admission/financial-aid/presidential-scholarship")
    office = classify_url_for_student_wiki("https://www.smu.edu/aboutsmu/office-of-the-president/messages")

    assert scholarship.selected is True
    assert scholarship.reason == "student_canonical_allowlist"
    assert office.selected is False
    assert office.reason == "governance_or_admin"


def test_student_development_allowed_but_development_giving_office_rejected():
    student_development = classify_url_for_student_wiki("https://www.smu.edu/student-life/student-development")
    giving_office = classify_url_for_student_wiki("https://www.smu.edu/development/ways-to-give")

    assert student_development.selected is True
    assert student_development.reason == "student_canonical_allowlist"
    assert giving_office.selected is False
    assert giving_office.reason == "donor_advancement_or_alumni"


def test_stale_course_schedule_on_allowlisted_path_is_rejected():
    decision = classify_url_for_student_wiki(
        "https://www.smu.edu/enrollment-services/registrar/course-schedule/fall-2023"
    )

    assert decision.selected is False
    assert decision.reason == "dated_archive_page"


def test_hr_and_alumni_noise_are_rejected_with_stable_reasons():
    hr = classify_url_for_student_wiki("https://www.smu.edu/human-resources/benefits/overview")
    alumni = classify_url_for_student_wiki("https://www.smu.edu/alumni/events/homecoming-2020")
    giving = classify_url_for_student_wiki("https://www.smu.edu/giving/ways-to-give")

    assert hr.selected is False
    assert hr.reason == "hr_or_employee"
    assert alumni.selected is False
    assert alumni.reason == "alumni_stories_or_events"
    assert giving.selected is False
    assert giving.reason == "donor_advancement_or_alumni"


def test_mailto_and_social_profiles_are_rejected():
    assert classify_url_for_student_wiki("mailto:admissions@smu.edu").reason == "mailto_link"
    assert classify_url_for_student_wiki("https://www.facebook.com/smu").reason == "social_or_external_profile"


def test_faculty_directory_is_rejected_but_program_page_stays_eligible():
    assert classify_url_for_student_wiki("https://www.smu.edu/dedman/faculty/directory").selected is False
    assert classify_url_for_student_wiki("https://www.smu.edu/dedman/academics/undergraduate-programs").selected is True


def test_academic_program_faculty_profile_is_allowed_but_generic_profile_is_rejected():
    program_profile = classify_url_for_student_wiki(
        "https://www.smu.edu/dedman/academics/departments/psychology/faculty/profiles/jane-doe"
    )
    academic_program_profile = classify_url_for_student_wiki(
        "https://www.smu.edu/academics/programs/biology/faculty/profile/jane-doe"
    )
    academic_program_profiles = classify_url_for_student_wiki(
        "https://www.smu.edu/academics/programs/biology/faculty/profiles/jane-doe"
    )
    generic_profile = classify_url_for_student_wiki("https://www.smu.edu/faculty/profiles/jane-doe")
    student_service_profile = classify_url_for_student_wiki("https://www.smu.edu/student-life/staff/profiles/jane-doe")

    assert program_profile.selected is True
    assert academic_program_profile.selected is True
    assert academic_program_profiles.selected is True
    assert generic_profile.selected is False
    assert generic_profile.reason == "staff_faculty_bio"
    assert student_service_profile.selected is False
    assert student_service_profile.reason == "staff_faculty_bio"


def test_direct_staff_and_faculty_person_slugs_are_rejected():
    faculty = classify_url_for_student_wiki("https://www.smu.edu/dedman/faculty/jane-doe")
    staff = classify_url_for_student_wiki("https://www.smu.edu/dedman/staff/jane-doe")

    assert faculty.selected is False
    assert faculty.reason == "staff_faculty_bio"
    assert staff.selected is False
    assert staff.reason == "staff_faculty_bio"


def test_gifted_academic_program_allowed_but_donor_gift_page_rejected():
    gifted_program = classify_url_for_student_wiki("https://www.smu.edu/academics/programs/gifted-education")
    gift_page = classify_url_for_student_wiki("https://www.smu.edu/giving/gift-planning/ways-to-give")

    assert gifted_program.selected is True
    assert gifted_program.reason == "student_canonical_allowlist"
    assert gift_page.selected is False
    assert gift_page.reason == "donor_advancement_or_alumni"


def test_financial_aid_benefits_allowed_but_employee_benefits_rejected():
    student_benefits = classify_url_for_student_wiki("https://www.smu.edu/financial-aid/benefits")
    employee_benefits = classify_url_for_student_wiki("https://www.smu.edu/human-resources/benefits")

    assert student_benefits.selected is True
    assert employee_benefits.selected is False
    assert employee_benefits.reason == "hr_or_employee"


def test_generic_news_archives_are_rejected():
    assert classify_url_for_student_wiki("https://www.smu.edu/news/archive").reason == "generic_news_archive"
    assert classify_url_for_student_wiki("https://www.smu.edu/news/articles/archive").reason == "generic_news_archive"


def test_search_and_calendar_listing_noise_are_rejected():
    assert classify_url_for_student_wiki("https://www.smu.edu/search?q=tuition").reason == "search_or_listing_noise"
    assert classify_url_for_student_wiki("https://www.smu.edu/search?utm_source=newsletter").reason == "search_or_listing_noise"
    assert classify_url_for_student_wiki("https://www.smu.edu/calendar/list/all").reason == "calendar_listing_noise"


def test_student_page_with_benign_query_is_not_rejected_for_query_alone():
    decision = classify_url_for_student_wiki("https://www.smu.edu/admission/apply?audience=first-year")

    assert decision.selected is True
    assert decision.reason == "student_canonical_allowlist"
