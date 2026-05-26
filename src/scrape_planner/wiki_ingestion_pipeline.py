from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from .llm_wiki_builder import build_wiki
from .llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index
from .raw_source_normalizer import (
    NormalizationReport,
    normalize_pdf_pages,
    normalize_scraped_markdown,
    normalize_tabular_sources,
)
from .site_layout import ensure_layout_for_site_root
from .source_registry import read_registry_rows, utc_now_iso

NORMALIZATION_KINDS = {"web", "pdf", "excel"}


def run_wiki_ingestion_pipeline(
    *,
    site_root: Path,
    run_root: Path | None = None,
    tabular_paths: Iterable[str | Path] | None = None,
    kinds: Iterable[str] | None = None,
    skip_normalize: bool = False,
    skip_wiki: bool = False,
    skip_index: bool = False,
    resume: bool = True,
    rebuild: bool = False,
    query: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Run raw-source normalization, wiki build, index build, and optional query smoke test.

    This is the non-interactive end-to-end operator path. It intentionally reuses the
    individual durable pipeline stages rather than introducing a second artifact format.
    """
    timestamp = now or utc_now_iso()
    layout = ensure_layout_for_site_root(Path(site_root))
    tabular = [Path(path) for path in (tabular_paths or [])]
    selected_kinds = _resolve_kinds(kinds, run_root=run_root, tabular_paths=tabular)

    normalization: dict[str, Any] = {
        "skipped": bool(skip_normalize),
        "kinds": selected_kinds,
        "reports": {},
        "counts": _empty_counts(),
    }
    if not skip_normalize:
        normalization = _run_normalization(
            layout.site_root,
            selected_kinds,
            run_root=run_root,
            tabular_paths=tabular,
            now=timestamp,
        )

    registry_rows = read_registry_rows(layout.registry_path)
    ready_sources = [row for row in registry_rows if str(row.get("status") or "").lower() == "ready"]
    result: dict[str, Any] = {
        "status": "complete",
        "site_root": str(layout.site_root),
        "generated_at": timestamp,
        "normalization": normalization,
        "registry": {
            "path": str(layout.registry_path),
            "source_count": len(registry_rows),
            "ready_source_count": len(ready_sources),
        },
        "wiki": {"skipped": bool(skip_wiki)},
        "index": {"skipped": bool(skip_index)},
        "query": None,
    }

    if not skip_wiki:
        result["wiki"] = build_wiki(
            layout.site_root,
            no_input=True,
            resume=bool(resume and not rebuild),
            rebuild=bool(rebuild),
            now=timestamp,
        )

    if not skip_index:
        result["index"] = build_llm_wiki_index(layout.site_root, now=timestamp)

    if query:
        result["query"] = query_llm_wiki_index(layout.site_root, query, max_evidence=5)

    return result


def _resolve_kinds(
    kinds: Iterable[str] | None,
    *,
    run_root: Path | None,
    tabular_paths: list[Path],
) -> list[str]:
    requested = [str(kind).strip().lower() for kind in (kinds or []) if str(kind).strip()]
    if not requested or "auto" in requested:
        selected: list[str] = []
        if run_root is not None:
            selected.append("web")
        selected.append("pdf")
        if tabular_paths:
            selected.append("excel")
        return selected
    if "all" in requested:
        return ["web", "pdf", "excel"]
    aliases = {"csv": "excel", "tabular": "excel"}
    selected = []
    for kind in requested:
        normalized = aliases.get(kind, kind)
        if normalized not in NORMALIZATION_KINDS:
            raise ValueError(f"Unsupported normalization kind: {kind}")
        if normalized not in selected:
            selected.append(normalized)
    return selected


def _run_normalization(
    site_root: Path,
    kinds: list[str],
    *,
    run_root: Path | None,
    tabular_paths: list[Path],
    now: str,
) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    counts = _empty_counts()

    for kind in kinds:
        if kind == "web":
            if run_root is None:
                raise ValueError("web normalization requires run_root")
            report = normalize_scraped_markdown(site_root, Path(run_root), now=now)
        elif kind == "pdf":
            report = normalize_pdf_pages(site_root, now=now)
        elif kind == "excel":
            report = normalize_tabular_sources(site_root, tabular_paths, now=now)
        else:  # defensive; _resolve_kinds validates first
            raise ValueError(f"Unsupported normalization kind: {kind}")
        reports[kind] = _normalization_report_dict(report)
        for key, value in report.counts.items():
            counts[key] = counts.get(key, 0) + int(value or 0)

    return {
        "skipped": False,
        "kinds": kinds,
        "reports": reports,
        "counts": counts,
    }


def _empty_counts() -> dict[str, int]:
    return {key: 0 for key in ("new", "unchanged", "changed", "ready", "failed", "needs-review")}


def _normalization_report_dict(report: NormalizationReport) -> dict[str, Any]:
    return {
        "counts": dict(report.counts),
        "registry_path": report.registry_path,
        "report_path": report.report_path,
        "sources": list(report.sources),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the LLM Wiki ingestion pipeline end to end.")
    parser.add_argument("--site-root", required=True, type=Path)
    parser.add_argument("--run-root", type=Path, default=None, help="Scrape run root containing scrape_manifest.json for web sources.")
    parser.add_argument("--tabular-path", action="append", default=[], help="CSV/XLS/XLSX source to normalize; may be repeated.")
    parser.add_argument(
        "--kind",
        action="append",
        choices=["auto", "all", "web", "pdf", "excel", "csv", "tabular"],
        default=[],
        help="Normalization kind; default auto runs web when --run-root is provided, pdf always, and excel when --tabular-path is provided.",
    )
    parser.add_argument("--skip-normalize", action="store_true")
    parser.add_argument("--skip-wiki", action="store_true")
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--query", default="", help="Optional smoke query after index build.")
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)

    try:
        result = run_wiki_ingestion_pipeline(
            site_root=args.site_root,
            run_root=args.run_root,
            tabular_paths=args.tabular_path,
            kinds=args.kind,
            skip_normalize=args.skip_normalize,
            skip_wiki=args.skip_wiki,
            skip_index=args.skip_index,
            resume=args.resume,
            rebuild=args.rebuild,
            query=args.query or None,
            now=args.now,
        )
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
