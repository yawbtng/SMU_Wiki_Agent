from src.scrape_planner.scrape.sitemap_discovery import apply_manual_urls, discover_site_urls


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


def test_discovery_keeps_specific_seed_url_path_when_sitemaps_are_empty(monkeypatch):
    class FakeResponse:
        status_code = 404
        text = ""

    def fake_get(url, timeout):
        return FakeResponse()

    monkeypatch.setattr("src.scrape_planner.scrape.sitemap_discovery.requests.get", fake_get)

    result = discover_site_urls("https://github.com/earendil-works/pi/tree/main/packages/agent")

    assert [row.url for row in result.urls] == ["https://github.com/earendil-works/pi/tree/main/packages/agent"]
    assert result.urls[0].source_sitemap == "seed"
    assert result.urls[0].selected is True
