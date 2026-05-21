from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SiteLayout:
    site_root: Path
    raw_sources_dir: Path
    raw_web_dir: Path
    raw_pdf_dir: Path
    raw_excel_dir: Path
    raw_reports_dir: Path
    registry_path: Path
    wiki_dir: Path
    indexes_dir: Path


def site_root_for(data_root: Path, site_id: str) -> Path:
    return Path(data_root) / "sites" / str(site_id)


def site_layout(site_root: Path) -> SiteLayout:
    raw_sources = Path(site_root) / "raw_sources"
    return SiteLayout(
        site_root=Path(site_root),
        raw_sources_dir=raw_sources,
        raw_web_dir=raw_sources / "web",
        raw_pdf_dir=raw_sources / "pdf",
        raw_excel_dir=raw_sources / "excel",
        raw_reports_dir=raw_sources / "reports",
        registry_path=raw_sources / "registry.jsonl",
        wiki_dir=Path(site_root) / "wiki",
        indexes_dir=Path(site_root) / "indexes",
    )


def ensure_site_layout(data_root: Path, site_id: str) -> SiteLayout:
    layout = site_layout(site_root_for(data_root, site_id))
    for path in (
        layout.raw_sources_dir,
        layout.raw_web_dir,
        layout.raw_pdf_dir,
        layout.raw_excel_dir,
        layout.raw_reports_dir,
        layout.wiki_dir,
        layout.indexes_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return layout


def ensure_layout_for_site_root(site_root: Path) -> SiteLayout:
    layout = site_layout(site_root)
    for path in (
        layout.raw_sources_dir,
        layout.raw_web_dir,
        layout.raw_pdf_dir,
        layout.raw_excel_dir,
        layout.raw_reports_dir,
        layout.wiki_dir,
        layout.indexes_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return layout
