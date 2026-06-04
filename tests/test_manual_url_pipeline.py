from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.scrape_planner.core.site_layout import ensure_site_layout


NOW = "2026-05-22T12:00:00+00:00"


class FakeResponse:
    status_code = 200
    encoding = "utf-8"
    headers = {"content-type": "text/html; charset=utf-8"}

    def __init__(self, html: str) -> None:
        self.content = html.encode("utf-8")
        self.text = html

    def iter_content(self, chunk_size: int = 65536):
        yield self.content


def test_manual_url_pipeline_scrapes_normalizes_builds_wiki_and_index(tmp_path: Path, monkeypatch) -> None:
    from src.scrape_planner.scrape.manual_url_pipeline import run_manual_url_pipeline

    monkeypatch.setenv("WIKI_SKIP_PI", "1")
    monkeypatch.setenv("LLM_WIKI_ALLOW_HASH_FALLBACK", "1")
    layout = ensure_site_layout(tmp_path, "example.edu")

    result = run_manual_url_pipeline(
        site_root=layout.site_root,
        site_url="https://example.edu",
        url="https://example.edu/admissions",
        now=NOW,
        fetcher=lambda url: FakeResponse(
            "<html><body><h1>Admissions Deadlines</h1>"
            "<p>Graduate applicants apply by February 1. Tuition details are listed.</p></body></html>"
        ),
    )

    assert result["status"] == "complete"
    assert result["url"] == "https://example.edu/admissions"
    assert result["run_id"].startswith("manual-")
    assert result["raw_report"]["counts"]["ready"] == 1
    assert result["wiki_report"]["status"] == "complete"
    assert result["index_report"]["index_health"] == "ready"
    assert (layout.site_root / result["run_root"] / "scrape_manifest.json").exists()
    assert (layout.site_root / "wiki" / "index.md").exists()
    assert (layout.site_root / "indexes" / "llm_wiki_manifest.json").exists()
    registry_rows = (layout.site_root / "raw_sources" / "registry.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(registry_rows) == 1
    assert json.loads(registry_rows[0])["source_kind"] == "web"


def test_manual_url_pipeline_rejects_off_domain_url(tmp_path: Path) -> None:
    from src.scrape_planner.scrape.manual_url_pipeline import run_manual_url_pipeline

    layout = ensure_site_layout(tmp_path, "example.edu")

    result = run_manual_url_pipeline(
        site_root=layout.site_root,
        site_url="https://example.edu",
        url="https://other.edu/admissions",
        now=NOW,
        fetcher=lambda _url: SimpleNamespace(status_code=200, headers={}, text="should not fetch"),
    )

    assert result["status"] == "rejected"
    assert result["reason"] == "off_domain"
    assert not (layout.site_root / "raw_sources" / "registry.jsonl").exists()
