from __future__ import annotations

from pathlib import Path

from src.scrape_planner.webapp.api import wiki_generation_payload, wiki_pages_payload


def _write_page(path: Path, frontmatter: str, body: str = "# Heading\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")


def test_wiki_pages_guides_view_hides_pdf_shards(tmp_path: Path, monkeypatch) -> None:
    site = tmp_path / "sites" / "demo.edu"
    wiki_pages = site / "wiki" / "pages"
    _write_page(wiki_pages / "school-guides.md", "title: SMU School Guides\npage_type: semantic")
    _write_page(
        wiki_pages / "admissions" / "2025-2026-gr-catalog-pdf-p-1001-pdf-abc.md",
        "title: Source: Catalog p. 1001\npage_type: source",
    )
    monkeypatch.setattr("src.scrape_planner.webapp.api.site_root", lambda _site_id: site)

    guides = wiki_pages_payload("demo.edu", view="guides")
    sources = wiki_pages_payload("demo.edu", view="sources")

    guide_titles = {row["title"] for row in guides["pages"]}
    assert "SMU School Guides" in guide_titles
    assert not any("Catalog p. 1001" in title for title in guide_titles)
    assert len(sources["pages"]) == 1
    assert sources["pages"][0]["title"] == "Heading"


def test_wiki_display_title_uses_heading_for_source_pages(tmp_path: Path, monkeypatch) -> None:
    site = tmp_path / "sites" / "demo.edu"
    path = site / "wiki" / "pages" / "admissions" / "shard.md"
    _write_page(
        path,
        "title: Source: Catalog p. 9\npage_type: source",
        "# Graduate Admission Requirements\n\nDetails here.\n",
    )
    monkeypatch.setattr("src.scrape_planner.webapp.api.site_root", lambda _site_id: site)

    payload = wiki_pages_payload("demo.edu", view="sources", limit=10)
    assert payload["pages"][0]["title"] == "Graduate Admission Requirements"


def test_wiki_generation_payload_counts_page_types(tmp_path: Path, monkeypatch) -> None:
    site = tmp_path / "sites" / "demo.edu"
    wiki_pages = site / "wiki" / "pages"
    _write_page(wiki_pages / "guide.md", "title: Guide\npage_type: semantic")
    _write_page(wiki_pages / "admissions" / "catalog-pdf-p-1-pdf-abc.md", "title: Source: x\npage_type: source")
    (site / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    monkeypatch.setattr("src.scrape_planner.webapp.api.site_root", lambda _site_id: site)

    status = wiki_generation_payload("demo.edu")
    assert status["semantic_page_count"] == 1
    assert status["source_page_count"] == 1
    assert status["total_page_count"] == 2
