from src.scrape_planner.core.models import DiscoveredURL
from src.scrape_planner.scrape.scrape_url_selection import filter_urls_for_scrape, urls_for_site_scrape
from src.scrape_planner.scrape.sitemap_discovery import apply_manual_urls, discover_site_urls


def test_apply_manual_urls_rejects_donor_page():
    items = apply_manual_urls("https://www.smu.edu", ["https://www.smu.edu/giving/donate"])

    assert len(items) == 1
    assert items[0].selected is False
    assert items[0].excluded_reason == "donor_advancement_or_alumni"


def test_filter_urls_for_scrape_skips_legacy_selected_donor_url():
    urls = [
        DiscoveredURL(url="https://www.smu.edu/giving/donate", source_sitemap="manual", selected=True),
        DiscoveredURL(
            url="https://www.smu.edu/enrollment-services/registrar/academic-calendar/final-exam-schedules",
            source_sitemap="manual",
            selected=True,
        ),
    ]

    selected = filter_urls_for_scrape(urls)

    assert len(selected) == 1
    assert "final-exam-schedules" in selected[0].url


def test_urls_for_site_scrape_prefers_approved_urls(tmp_path):
    site_root = tmp_path / "www.smu.edu"
    site_root.mkdir(parents=True)
    (site_root / "discovered_urls.json").write_text(
        """
        [
          {"url": "https://www.smu.edu/giving/donate", "source_sitemap": "sitemap", "selected": true},
          {"url": "https://www.smu.edu/registrar/calendar", "source_sitemap": "sitemap", "selected": true},
          {"url": "https://www.smu.edu/admission/apply", "source_sitemap": "sitemap", "selected": true}
        ]
        """.strip(),
        encoding="utf-8",
    )
    (site_root / "approved_urls.md").write_text(
        "# Approved URLs\n\n- [x] https://www.smu.edu/admission/apply\n",
        encoding="utf-8",
    )

    urls = urls_for_site_scrape(site_root, prefer_approved=True)

    assert len(urls) == 1
    assert urls[0].url == "https://www.smu.edu/admission/apply"


def test_discover_site_urls_applies_policy(monkeypatch):
    sitemap_xml = """<?xml version='1.0' encoding='UTF-8'?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://www.example.edu/registrar/calendar</loc></url>
      <url><loc>https://www.example.edu/giving/donate</loc></url>
    </urlset>
    """

    class _Resp:
        status_code = 200
        text = sitemap_xml

    monkeypatch.setattr("src.scrape_planner.scrape.sitemap_discovery.requests.get", lambda *args, **kwargs: _Resp())
    monkeypatch.setattr(
        "src.scrape_planner.scrape.sitemap_discovery._extract_sitemap_from_robots",
        lambda *args, **kwargs: (["https://www.example.edu/sitemap.xml"], None),
    )

    result = discover_site_urls("https://www.example.edu")

    by_url = {item.url: item for item in result.urls}
    assert by_url["https://www.example.edu/registrar/calendar"].selected is True
    assert by_url["https://www.example.edu/giving/donate"].selected is False
    assert by_url["https://www.example.edu/giving/donate"].excluded_reason == "donor_advancement_or_alumni"


def test_record_confidence_gap_writes_refresh_recommendation(tmp_path):
    from src.scrape_planner.wiki.self_improving import read_confidence_gaps, record_confidence_gap

    site_root = tmp_path / "demo.edu"
    site_root.mkdir()
    (site_root / "indexes").mkdir()
    (site_root / "config").mkdir()

    record_confidence_gap(
        site_root,
        question="When is the fall 2026 course schedule published?",
        confidence={"confident": False, "decision": "not_confident"},
        evidence=[{"url": "https://demo.edu/registrar/calendar"}],
    )

    gaps = read_confidence_gaps(site_root)
    assert len(gaps) == 1
    assert gaps[0]["recommended_action"] == "re_discovery_and_rebuild"
    assert "/registrar" in gaps[0]["suggested_groups"][0]
