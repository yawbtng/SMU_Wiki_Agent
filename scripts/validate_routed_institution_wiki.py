from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.scrape_planner.wiki.llm_wiki_builder import build_wiki
from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index
from src.scrape_planner.sources.raw_source_normalizer import normalize_pdf_pages, normalize_scraped_markdown
from src.scrape_planner.core.site_layout import ensure_site_layout
from src.scrape_planner.sources.source_registry import build_source_row, checksum_text, read_registry_rows, write_registry_rows
from src.scrape_planner.core.storage import write_json


NOW = "2026-05-22T00:00:00+00:00"


def run_validation(*, output_path: Path, smu_site_root: Path | None = None, smu_limit: int = 5) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="routed-wiki-fixture-") as tmp:
        tmp_path = Path(tmp)
        site_root, run_root = _build_noisy_fixture(tmp_path)
        web_report = normalize_scraped_markdown(site_root, run_root, now=NOW)
        pdf_report = normalize_pdf_pages(site_root, now=NOW)
        wiki_report = build_wiki(site_root, no_input=True, rebuild=True, now=NOW)
        index_report = build_llm_wiki_index(site_root, now=NOW)
        query_report = query_llm_wiki_index(
            site_root,
            "What is the computer science application deadline?",
            profile={"education_level": "graduate", "role": "applicant", "intent": "apply", "academic_interest": "computer"},
            max_evidence=4,
        )
        unrelated_report = query_llm_wiki_index(site_root, "xylophonicquarkzz", max_evidence=3)
        fixture = {
            "site_root": str(site_root),
            "web_quality": _quality_counts(web_report.report_path),
            "pdf_counts": pdf_report.counts,
            "wiki_required_files": {
                rel: (site_root / rel).exists()
                for rel in [
                    "wiki/index.md",
                    "wiki/routing/audience.md",
                    "wiki/routing/intent.md",
                    "wiki/routing/topics.md",
                    "wiki/source-notes/index.md",
                    "wiki/review_queue.md",
                ]
            },
            "wiki_pages": [row["path"] for row in wiki_report.get("pages", [])],
            "index": {
                "raw_index_count": index_report.get("raw_index_count"),
                "wiki_index_count": index_report.get("wiki_index_count"),
            },
            "query": {
                "status": query_report.get("status"),
                "top_path": (query_report.get("evidence") or [{}])[0].get("path"),
                "routing": (query_report.get("metadata") or {}).get("routing"),
            },
            "unrelated_query_status": unrelated_report.get("status"),
        }

        smu = _run_bounded_smu_sample(smu_site_root, tmp_path / "smu-sample", limit=smu_limit) if smu_site_root else {}
        report = {"status": "complete", "fixture": fixture, "smu_limited": smu}
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report


def _build_noisy_fixture(root: Path) -> tuple[Path, Path]:
    layout = ensure_site_layout(root, "fixture-university")
    site_root = layout.site_root
    run_root = site_root / "run-001"
    markdown_dir = run_root / "markdown"
    markdown_dir.mkdir(parents=True, exist_ok=True)
    pages = {
        "program.md": "\n".join(
            [
                "Home",
                "Admissions",
                "Search",
                "# Computer Science Graduate Program",
                "Graduate applicants apply by March 1. Computer science tuition is 100 credits.",
                "The department chair is Jane Rivera.",
                "Privacy",
            ]
        ),
        "costs.md": "# Tuition And Fees\n\nTuition, fees, and financial aid dates apply to graduate students.\n",
        "redirect.md": "You are being redirected. Click here if you are not redirected.",
        "binary.md": "%PDF-1.4\n1 0 obj\nstream\n",
        "tiny.md": "Welcome.",
    }
    manifest = []
    for name, body in pages.items():
        path = markdown_dir / name
        path.write_text(body, encoding="utf-8")
        manifest.append({"url": f"https://fixture.edu/{name}", "status": "success", "markdown_path": str(path)})
    write_json(run_root / "scrape_manifest.json", manifest)

    page_dir = site_root / "sources" / "pdf_pages" / "catalog"
    page_dir.mkdir(parents=True, exist_ok=True)
    pdf_page = page_dir / "page-0001.md"
    pdf_page.write_text(
        "# Graduate Catalog\n\n## Aid Table\n\n| Program | Aid |\n| --- | --- |\n| Computer Science | Fellowship |\n",
        encoding="utf-8",
    )
    write_json(
        page_dir / "pages.json",
        [
            {
                "pdf_source_id": "catalog",
                "source_path": "/uploads/catalog.pdf",
                "page_number": 1,
                "parser": "docling",
                "markdown_path": str(pdf_page),
            }
        ],
    )
    return site_root, run_root


def _run_bounded_smu_sample(source_site_root: Path, output_root: Path, *, limit: int) -> dict[str, Any]:
    registry = source_site_root / "raw_sources" / "registry.jsonl"
    if not registry.exists():
        return {"status": "skipped", "reason": "missing_registry", "source_site_root": str(source_site_root)}
    rows = [row for row in read_registry_rows(registry) if str(row.get("status") or "") == "ready"][:limit]
    if not rows:
        return {"status": "skipped", "reason": "no_ready_rows", "source_site_root": str(source_site_root)}
    sample = ensure_site_layout(output_root, "smu-limited").site_root
    copied_rows = []
    for row in rows:
        source_path = source_site_root / str(row.get("markdown_path") or "")
        if not source_path.exists():
            continue
        target_dir = sample / "raw_sources" / str(row.get("source_kind") or "web")
        target_dir.mkdir(parents=True, exist_ok=True)
        body = source_path.read_text(encoding="utf-8", errors="replace")
        target = target_dir / source_path.name
        target.write_text(body, encoding="utf-8")
        copied = build_source_row(
            source_id=str(row.get("source_id") or target.stem),
            source_kind=str(row.get("source_kind") or "web"),
            title=str(row.get("title") or target.stem),
            original_url=str(row.get("original_url") or ""),
            original_path=str(row.get("original_path") or ""),
            markdown_path=str(target.relative_to(sample)),
            metadata_path="",
            checksum=checksum_text(body),
            parser=str(row.get("parser") or "sample-copy"),
            status="ready",
            now=NOW,
        )
        copied_rows.append(copied)
    write_registry_rows(sample / "raw_sources" / "registry.jsonl", copied_rows)
    wiki_report = build_wiki(sample, no_input=True, rebuild=True, now=NOW)
    index_report = build_llm_wiki_index(sample, now=NOW)
    query = query_llm_wiki_index(sample, "tuition admissions graduate catalog", max_evidence=3)
    return {
        "status": "complete",
        "source_site_root": str(source_site_root),
        "sample_site_root": str(sample),
        "sampled_sources": len(copied_rows),
        "generated_pages": [row["path"] for row in wiki_report.get("pages", [])],
        "raw_index_count": index_report.get("raw_index_count"),
        "wiki_index_count": index_report.get("wiki_index_count"),
        "query_status": query.get("status"),
        "quality_counts": "source quality already validated on fixture; sample uses existing ready registry rows",
    }


def _quality_counts(report_path: str) -> dict[str, Any]:
    payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
    return ((payload.get("quality_summary") or {}).get("counts") or {}) if isinstance(payload, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate routed institution wiki fixture and optional bounded SMU sample.")
    parser.add_argument("--output-path", default="docs/validation/routed-institution-wiki-validation.json")
    parser.add_argument("--smu-site-root", default="data/sites/www.smu.edu")
    parser.add_argument("--smu-limit", type=int, default=5)
    args = parser.parse_args(argv)
    report = run_validation(
        output_path=Path(args.output_path),
        smu_site_root=Path(args.smu_site_root) if args.smu_site_root else None,
        smu_limit=args.smu_limit,
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
