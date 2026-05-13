from src.scrape_planner.sitemap_discovery import apply_manual_urls


def test_manual_urls_accept_same_root_subdomains():
    rows = apply_manual_urls("https://www.example.edu", ["https://admissions.example.edu/apply"])

    assert len(rows) == 1
    assert rows[0].excluded_reason is None
    assert rows[0].selected is True


def test_manual_urls_exclude_unrelated_domains():
    rows = apply_manual_urls("https://example.edu", ["https://example.com/apply"])

    assert len(rows) == 1
    assert rows[0].excluded_reason == "off_domain"
    assert rows[0].selected is False
