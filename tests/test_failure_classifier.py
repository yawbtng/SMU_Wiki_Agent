from src.scrape_planner.scrape.failure_classifier import classify_failure


def test_http_blocked():
    reason = classify_failure(http_status=403, content_type="text/html", text_length=1000, link_density=0.01)
    assert reason == "blocked"


def test_non_html():
    reason = classify_failure(http_status=200, content_type="application/pdf", text_length=1000, link_density=0.01)
    assert reason == "non_html"

