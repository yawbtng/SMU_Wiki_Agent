from score_urls import detect_dated_archive, score_url


def test_recent_lastmod_does_not_rescue_old_article():
    row = score_url(
        {
            "url": "https://www.smu.edu/cox/coxtoday-magazine/2018-10-01-the-cost-of-financial-protectionism",
            "lastmod": "2025-07-01T00:00:00Z",
        }
    )

    assert row["score"] < 70
    assert row["freshness"] <= 35
    assert "old dated article" in row["reason"]


def test_old_recipient_child_page_is_demoted_below_threshold():
    row = score_url(
        {
            "url": "https://www.smu.edu/admission/apply/transfer/scholarships/ntcc-scholarships/2023-ntcc-scholars",
            "lastmod": "2025-10-01T00:00:00Z",
        }
    )

    assert row["score"] < 70
    assert row["freshness"] <= 35
    assert "dated archive page" in row["reason"]


def test_evergreen_dining_story_can_still_score_high_enough():
    row = score_url(
        {
            "url": "https://www.smu.edu/stories/campus-dining",
            "lastmod": "2025-10-01T00:00:00Z",
        }
    )

    assert detect_dated_archive(row["url"]) == ""
    assert row["score"] >= 70

