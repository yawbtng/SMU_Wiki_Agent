from __future__ import annotations

import json
from pathlib import Path

from src.scrape_planner.sources.source_registry import build_source_row, checksum_text, write_registry_rows

NOW = "2026-05-21T12:00:00+00:00"
LATER = "2026-05-21T13:00:00+00:00"


def _write_source(
    site_root: Path,
    *,
    source_id: str,
    source_kind: str = "web",
    title: str,
    body: str,
    checksum: str | None = None,
) -> dict:
    raw_dir = site_root / "raw_sources" / source_kind
    raw_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = raw_dir / f"{source_id}.md"
    markdown_path.write_text(body, encoding="utf-8")
    metadata_path = raw_dir / f"{source_id}.metadata.json"
    metadata_path.write_text(json.dumps({"parser_detail": "fixture"}), encoding="utf-8")
    return build_source_row(
        source_id=source_id,
        source_kind=source_kind,
        title=title,
        original_url=f"https://example.edu/{source_id}",
        original_path="",
        markdown_path=str(markdown_path.relative_to(site_root)),
        metadata_path=str(metadata_path.relative_to(site_root)),
        checksum=checksum or checksum_text(body),
        parser="fixture-parser",
        status="ready",
        now=NOW,
        wiki_status="integrated",
    )


def _frontmatter_list(key: str, values: list[str]) -> list[str]:
    if not values:
        return []
    return [f"{key}:", *[f"  - {value}" for value in values]]


def _write_wiki_page(
    site_root: Path,
    *,
    name: str,
    title: str,
    tags: list[str],
    source_ids: list[str],
    body: str,
    updated_at: str = NOW,
    audiences: list[str] | None = None,
    roles: list[str] | None = None,
    intents: list[str] | None = None,
    academic_interests: list[str] | None = None,
) -> Path:
    pages_dir = site_root / "wiki" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    page_path = pages_dir / f"{name}.md"
    frontmatter = [
        "---",
        f"title: {title}",
        "tags:",
        *[f"  - {tag}" for tag in tags],
        "source_ids:",
        *[f"  - {source_id}" for source_id in source_ids],
        *(_frontmatter_list("audiences", audiences or [])),
        *(_frontmatter_list("roles", roles or [])),
        *(_frontmatter_list("intents", intents or [])),
        *(_frontmatter_list("academic_interests", academic_interests or [])),
        f"updated_at: {updated_at}",
        "---",
        "",
    ]
    page_path.write_text("\n".join(frontmatter) + body, encoding="utf-8")
    return page_path


def _fixture_site(tmp_path: Path) -> Path:
    site_root = tmp_path / "site"
    rows = [
        _write_source(
            site_root,
            source_id="web_admissions",
            title="Admissions Raw",
            body="# Admissions Raw\n\nThe final application deadline is February 1. Transcripts are required.\n",
        ),
        _write_source(
            site_root,
            source_id="pdf_catalog",
            source_kind="pdf",
            title="Catalog Tuition Raw",
            body="# Catalog Tuition Raw\n\nTuition for the graduate catalog is 100 credits per term.\n",
        ),
    ]
    rows[0]["wiki_page_paths"] = ["wiki/pages/admissions.md"]
    write_registry_rows(site_root / "raw_sources" / "registry.jsonl", rows)
    _write_wiki_page(
        site_root,
        name="admissions",
        title="Admissions",
        tags=["admissions"],
        source_ids=["web_admissions"],
        body="# Admissions\n\nThe admissions wiki says the final application deadline is February 1.\n",
    )
    return site_root
