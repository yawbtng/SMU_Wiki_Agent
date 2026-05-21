import json
from pathlib import Path

from src.scrape_planner.ui_scrape_realtime import (
    build_scraped_page_preview_href,
    derive_run_summary,
    is_safe_page_slug,
    is_safe_route_part,
    latest_pages_by_status,
    page_slug,
    resolve_scraped_markdown_preview,
)


def test_page_slug_hashes_url_to_stable_short_slug() -> None:
    assert page_slug("https://example.com/path?a=1") == "635d6a6279df"


def test_build_scraped_page_preview_href_includes_preview_query_params() -> None:
    href = build_scraped_page_preview_href(
        site_id="site-a",
        run_id="run-1",
        url="https://example.com/a page",
    )

    assert href.startswith("?view=scraped_page&")
    assert "site_id=site-a" in href
    assert "run_id=run-1" in href
    assert "page_slug=" in href


def test_build_scraped_page_preview_href_has_stable_slug() -> None:
    first = build_scraped_page_preview_href(site_id="site-a", run_id="run-1", url="https://example.com/a")
    second = build_scraped_page_preview_href(site_id="site-a", run_id="run-1", url="https://example.com/a")

    assert first == second
    assert page_slug("https://example.com/a") in first


def test_is_safe_route_part_accepts_route_identifiers() -> None:
    assert is_safe_route_part("site-a") is True
    assert is_safe_route_part("20260520T120000Z-abc123") is True


def test_is_safe_route_part_rejects_path_like_values() -> None:
    assert is_safe_route_part("../site") is False
    assert is_safe_route_part("site/a") is False
    assert is_safe_route_part("site\\a") is False
    assert is_safe_route_part("") is False


def test_is_safe_page_slug_accepts_generated_sha1_slug() -> None:
    assert is_safe_page_slug("635d6a6279df") is True


def test_is_safe_page_slug_rejects_non_generated_slug_values() -> None:
    assert is_safe_page_slug("635D6A6279DF") is False
    assert is_safe_page_slug("nothexslugzz") is False
    assert is_safe_page_slug("635d6a6279df0") is False


def test_resolve_scraped_markdown_preview_loads_markdown_and_metadata(tmp_path: Path) -> None:
    slug = "abc123def456"
    markdown_dir = tmp_path / "markdown"
    metadata_dir = tmp_path / "metadata"
    markdown_dir.mkdir()
    metadata_dir.mkdir()
    (markdown_dir / f"{slug}.md").write_text("# Title\n\nBody", encoding="utf-8")
    (metadata_dir / f"{slug}.json").write_text(
        json.dumps(
            {
                "url": "https://example.com/page",
                "http_status": 200,
                "fetch_mode": "dynamic",
                "text_length": 1234,
            }
        ),
        encoding="utf-8",
    )

    preview = resolve_scraped_markdown_preview(tmp_path, slug)

    assert preview.ready is True
    assert preview.markdown == "# Title\n\nBody"
    assert preview.url == "https://example.com/page"
    assert preview.http_status == 200
    assert preview.fetch_mode == "dynamic"
    assert preview.text_length == 1234


def test_resolve_scraped_markdown_preview_returns_not_ready_for_missing_markdown(tmp_path: Path) -> None:
    preview = resolve_scraped_markdown_preview(tmp_path, "abc123def456")

    assert preview.ready is False
    assert preview.markdown == ""
    assert preview.message == "Scraped markdown is not ready yet."


def test_resolve_scraped_markdown_preview_handles_deleted_markdown(tmp_path: Path, monkeypatch) -> None:
    slug = "abc123def456"
    markdown_dir = tmp_path / "markdown"
    markdown_dir.mkdir()
    markdown_path = markdown_dir / f"{slug}.md"
    markdown_path.write_text("# Title", encoding="utf-8")
    original_read_text = Path.read_text

    def raise_for_markdown(path: Path, *args, **kwargs) -> str:
        if path == markdown_path:
            raise FileNotFoundError
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", raise_for_markdown)

    preview = resolve_scraped_markdown_preview(tmp_path, slug)

    assert preview.ready is False
    assert preview.markdown == ""
    assert preview.message == "Scraped markdown is not ready yet."


def test_resolve_scraped_markdown_preview_rejects_path_like_slug(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    preview = resolve_scraped_markdown_preview(run_root, "../../secret")

    assert preview.ready is False
    assert preview.message == "Scraped markdown is not ready yet."
    assert preview.path is None


def test_resolve_scraped_markdown_preview_ignores_corrupt_metadata(tmp_path: Path) -> None:
    slug = "abc123def456"
    markdown_dir = tmp_path / "markdown"
    metadata_dir = tmp_path / "metadata"
    markdown_dir.mkdir()
    metadata_dir.mkdir()
    (markdown_dir / f"{slug}.md").write_text("# Title", encoding="utf-8")
    (metadata_dir / f"{slug}.json").write_text("{not json", encoding="utf-8")

    preview = resolve_scraped_markdown_preview(tmp_path, slug)

    assert preview.ready is True
    assert preview.markdown == "# Title"
    assert preview.url == ""
    assert preview.http_status is None
    assert preview.fetch_mode == ""


def test_resolve_scraped_markdown_preview_ignores_list_metadata(tmp_path: Path) -> None:
    slug = "abc123def456"
    markdown_dir = tmp_path / "markdown"
    metadata_dir = tmp_path / "metadata"
    markdown_dir.mkdir()
    metadata_dir.mkdir()
    (markdown_dir / f"{slug}.md").write_text("# Title", encoding="utf-8")
    (metadata_dir / f"{slug}.json").write_text("[]", encoding="utf-8")

    preview = resolve_scraped_markdown_preview(tmp_path, slug)

    assert preview.ready is True
    assert preview.markdown == "# Title"
    assert preview.url == ""
    assert preview.http_status is None
    assert preview.fetch_mode == ""


def test_resolve_scraped_markdown_preview_ignores_bad_text_length(tmp_path: Path) -> None:
    slug = "abc123def456"
    markdown_dir = tmp_path / "markdown"
    metadata_dir = tmp_path / "metadata"
    markdown_dir.mkdir()
    metadata_dir.mkdir()
    (markdown_dir / f"{slug}.md").write_text("# Title", encoding="utf-8")
    (metadata_dir / f"{slug}.json").write_text(json.dumps({"text_length": "not-a-number"}), encoding="utf-8")

    preview = resolve_scraped_markdown_preview(tmp_path, slug)

    assert preview.ready is True
    assert preview.markdown == "# Title"
    assert preview.text_length is None


def test_derive_run_summary_uses_status_counts_and_progress() -> None:
    summary = derive_run_summary(
        status={"state": "running", "total": 4, "running": 1, "success": 1, "failed": 1},
        pages=[
            {"status": "success"},
            {"status": "failed"},
            {"status": "running"},
        ],
        selected_count=4,
    )

    assert summary.state == "running"
    assert summary.total == 4
    assert summary.success == 1
    assert summary.failed == 1
    assert summary.running == 1
    assert summary.remaining == 2
    assert summary.progress_label == "2 / 4"


def test_derive_run_summary_respects_explicit_zero_status_counts() -> None:
    summary = derive_run_summary(
        status={"state": "running", "total": 0, "running": 0, "success": 0, "failed": 0},
        pages=[
            {"status": "success"},
            {"status": "failed"},
            {"status": "running"},
        ],
        selected_count=3,
    )

    assert summary.total == 0
    assert summary.success == 0
    assert summary.failed == 0
    assert summary.running == 0
    assert summary.remaining == 0
    assert summary.progress_label == "0 / 0"


def test_derive_run_summary_ready_state_from_selected_count() -> None:
    summary = derive_run_summary(status={}, pages=[], selected_count=7)

    assert summary.state == "ready"
    assert summary.total == 7
    assert summary.queued == 7
    assert summary.remaining == 7
    assert summary.progress_label == "0 / 7"


def test_derive_run_summary_paused_state_keeps_remaining_count() -> None:
    summary = derive_run_summary(
        status={"state": "paused", "total": 5, "success": 2, "failed": 0, "cancelled": 0, "running": 0, "queued": 3},
        pages=[],
        selected_count=5,
    )

    assert summary.state == "paused"
    assert summary.remaining == 3
    assert summary.queued == 3


def test_latest_pages_by_status_filters_and_sorts_newest_first() -> None:
    pages = [
        {"url": "https://example.com/old", "status": "success", "finished_at": "2026-01-01T00:00:00Z"},
        {"url": "https://example.com/failed", "status": "failed", "finished_at": "2026-01-03T00:00:00Z"},
        {"url": "https://example.com/new", "status": "success", "finished_at": "2026-01-02T00:00:00Z"},
        {"url": "https://example.com/running", "status": "success", "started_at": "2026-01-04T00:00:00Z"},
    ]

    latest = latest_pages_by_status(pages, "success", limit=2)

    assert [page["url"] for page in latest] == [
        "https://example.com/running",
        "https://example.com/new",
    ]
