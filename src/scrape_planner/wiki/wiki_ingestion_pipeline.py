from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from .llm_wiki_builder import assert_no_concurrent_wiki_build, build_wiki
from .llm_wiki_index import build_llm_wiki_index, query_mcp_wiki_index
from ..sources.raw_source_normalizer import (
    NormalizationReport,
    normalize_pdf_pages,
    normalize_scraped_markdown,
    normalize_tabular_sources,
)
from ..core.site_layout import ensure_layout_for_site_root
from ..sources.source_registry import read_registry_rows, utc_now_iso
from ..core.storage import write_json
NORMALIZATION_KINDS = {"web", "pdf", "excel"}
INGEST_REPORT_NAME = "wiki-ingest-latest.json"
STAGE_ORDER = ("ingest", "clean", "standardize", "lint", "build_wiki", "build_index", "verify")


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
    write_report: bool = True,
) -> dict[str, Any]:
    """Run normalization, wiki build, index build, and optional query smoke test."""
    timestamp = now or utc_now_iso()
    layout = ensure_layout_for_site_root(Path(site_root))
    tabular = [Path(path) for path in (tabular_paths or [])]
    selected_kinds = _resolve_kinds(kinds, run_root=run_root, tabular_paths=tabular)
    stage_timeline: dict[str, dict[str, Any]] = {}

    normalization: dict[str, Any] = {
        "skipped": bool(skip_normalize),
        "kinds": selected_kinds,
        "reports": {},
        "counts": _empty_counts(),
        "status": "skipped" if skip_normalize else "pending",
    }
    if not skip_normalize:
        stage_timeline["ingest"] = {"started_at": timestamp}
        try:
            normalization = _run_normalization(
                layout.site_root,
                selected_kinds,
                run_root=run_root,
                tabular_paths=tabular,
                now=timestamp,
            )
            normalization["status"] = "complete"
            stage_timeline["ingest"]["finished_at"] = utc_now_iso()
            stage_timeline["ingest"]["status"] = "complete"
        except Exception as exc:
            normalization["status"] = "failed"
            normalization["error"] = str(exc)
            stage_timeline["ingest"]["finished_at"] = utc_now_iso()
            stage_timeline["ingest"]["status"] = "failed"
            stage_timeline["ingest"]["error"] = str(exc)
            result = _failed_result(
                layout=layout,
                timestamp=timestamp,
                normalization=normalization,
                stage_timeline=stage_timeline,
                failed_stage="ingest",
            )
            if write_report:
                _write_ingest_report(layout, result)
            return result
    else:
        stage_timeline["ingest"] = {"status": "skipped", "started_at": timestamp, "finished_at": timestamp}

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
        assert_no_concurrent_wiki_build(layout.site_root)
        stage_timeline["build_wiki"] = {"started_at": utc_now_iso()}
        result["wiki"] = build_wiki(
            layout.site_root,
            no_input=True,
            resume=bool(resume and not rebuild),
            rebuild=bool(rebuild),
            now=timestamp,
        )
        wiki_status = str(result["wiki"].get("status") or "unknown").lower()
        stage_timeline["build_wiki"]["finished_at"] = utc_now_iso()
        stage_timeline["build_wiki"]["status"] = wiki_status
        if wiki_status in {"failed", "error"}:
            result["status"] = "failed"
            result["failed_stage"] = "build_wiki"
            result["index"] = {"skipped": True}
            result["query"] = None
            stage_timeline["build_index"] = {"status": "skipped"}
            stage_timeline["verify"] = {"status": "skipped"}
            result["stages"] = _stage_summary(result, stage_timeline=stage_timeline)
            if write_report:
                _write_ingest_report(layout, result)
            return result
    else:
        stage_timeline["build_wiki"] = {"status": "skipped"}

    if not skip_index:
        stage_timeline["build_index"] = {"started_at": utc_now_iso()}
        result["index"] = build_llm_wiki_index(layout.site_root, now=timestamp)
        index_status = str(result["index"].get("status") or "unknown").lower()
        stage_timeline["build_index"]["finished_at"] = utc_now_iso()
        stage_timeline["build_index"]["status"] = index_status
        if index_status in {"failed", "error"}:
            result["status"] = "failed"
            result["failed_stage"] = "build_index"
            result["query"] = None
            stage_timeline["verify"] = {"status": "skipped"}
            result["stages"] = _stage_summary(result, stage_timeline=stage_timeline)
            if write_report:
                _write_ingest_report(layout, result)
            return result
    else:
        stage_timeline["build_index"] = {"status": "skipped"}

    if query:
        stage_timeline["verify"] = {"started_at": utc_now_iso()}
        result["query"] = query_mcp_wiki_index(layout.site_root, query, max_evidence=5)
        query_status = str(result["query"].get("status") or "unknown").lower()
        stage_timeline["verify"]["finished_at"] = utc_now_iso()
        stage_timeline["verify"]["status"] = query_status
        if query_status not in {"ok", "complete", "skipped"}:
            result["status"] = "failed"
            result["failed_stage"] = "verify"
    else:
        stage_timeline["verify"] = {"status": "skipped"}

    result["stages"] = _stage_summary(result, stage_timeline=stage_timeline)
    if write_report:
        _write_ingest_report(layout, result)
    return result


def _failed_result(
    *,
    layout,
    timestamp: str,
    normalization: dict[str, Any],
    stage_timeline: dict[str, dict[str, Any]],
    failed_stage: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "failed",
        "failed_stage": failed_stage,
        "site_root": str(layout.site_root),
        "generated_at": timestamp,
        "normalization": normalization,
        "registry": {
            "path": str(layout.registry_path),
            "source_count": 0,
            "ready_source_count": 0,
        },
        "wiki": {"skipped": True},
        "index": {"skipped": True},
        "query": None,
    }
    result["stages"] = _stage_summary(result, stage_timeline=stage_timeline)
    return result


def _write_ingest_report(layout, result: dict[str, Any]) -> Path:
    report_dir = layout.wiki_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / INGEST_REPORT_NAME
    payload = {
        "status": result.get("status"),
        "failed_stage": result.get("failed_stage"),
        "site_root": result.get("site_root"),
        "generated_at": result.get("generated_at"),
        "stages": result.get("stages") or {},
        "registry": result.get("registry") or {},
        "wiki_report_path": (result.get("wiki") or {}).get("report_path"),
        "index_manifest_path": (result.get("index") or {}).get("manifest_path"),
        "query_status": (result.get("query") or {}).get("status") if result.get("query") else "skipped",
    }
    write_json(report_path, payload)
    result["ingest_report_path"] = str(report_path)
    return report_path


def _stage_summary(
    result: dict[str, Any],
    *,
    stage_timeline: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalization = result.get("normalization") if isinstance(result.get("normalization"), dict) else {}
    wiki = result.get("wiki") if isinstance(result.get("wiki"), dict) else {}
    index = result.get("index") if isinstance(result.get("index"), dict) else {}
    query = result.get("query") if isinstance(result.get("query"), dict) else None
    lint = wiki.get("lint") if isinstance(wiki.get("lint"), dict) else {}
    timeline = stage_timeline or {}

    def _merge(stage_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        merged = dict(payload)
        timing = timeline.get(stage_key) if isinstance(timeline.get(stage_key), dict) else {}
        for field in ("started_at", "finished_at", "status", "error"):
            if field in timing and timing[field] is not None:
                merged[field] = timing[field]
        return merged

    ingest_status = str(normalization.get("status") or ("skipped" if normalization.get("skipped") else "complete"))
    return {
        "ingest": _merge(
            "ingest",
            {
                "status": ingest_status,
                "counts": normalization.get("counts") or {},
                "kinds": normalization.get("kinds") or [],
                "error": normalization.get("error"),
            },
        ),
        "clean": _merge(
            "clean",
            {
                "status": "complete" if not wiki.get("skipped") else "skipped",
                "excluded_source_count": int(wiki.get("excluded_source_count") or 0),
            },
        ),
        "standardize": _merge(
            "standardize",
            {
                "status": "complete" if not wiki.get("skipped") else "skipped",
                "sources_considered": int(wiki.get("sources_considered") or 0),
            },
        ),
        "lint": _merge(
            "lint",
            {
                "status": str(lint.get("status") or ("pending" if not wiki.get("skipped") else "skipped")),
                "quality_flags": lint.get("quality_flags") or {},
            },
        ),
        "build_wiki": _merge(
            "build_wiki",
            {
                "status": str(wiki.get("status") or ("skipped" if wiki.get("skipped") else "unknown")),
                "pages_created": int(wiki.get("pages_created") or 0),
                "pages_updated": int(wiki.get("pages_updated") or 0),
                "integrated_sources": int(wiki.get("integrated_sources") or 0),
                "report_path": wiki.get("report_path"),
            },
        ),
        "build_index": _merge(
            "build_index",
            {
                "status": str(index.get("status") or ("skipped" if index.get("skipped") else "unknown")),
                "raw_index_count": int(index.get("raw_index_count") or 0),
                "wiki_index_count": int(index.get("wiki_index_count") or 0),
                "manifest_path": index.get("manifest_path"),
            },
        ),
        "verify": _merge(
            "verify",
            {
                "status": str(query.get("status") if query else "skipped"),
                "evidence_count": len(query.get("evidence") or []) if query else 0,
            },
        ),
    }


def _compact_result(result: dict[str, Any]) -> dict[str, Any]:
    wiki = result.get("wiki") if isinstance(result.get("wiki"), dict) else {}
    index = result.get("index") if isinstance(result.get("index"), dict) else {}
    query = result.get("query") if isinstance(result.get("query"), dict) else None
    return {
        "status": result.get("status"),
        "site_root": result.get("site_root"),
        "generated_at": result.get("generated_at"),
        "stages": result.get("stages") or {},
        "registry": result.get("registry") or {},
        "wiki": {
            "status": wiki.get("status"),
            "no_op": wiki.get("no_op"),
            "sources_considered": wiki.get("sources_considered"),
            "pages_created": wiki.get("pages_created"),
            "pages_updated": wiki.get("pages_updated"),
            "integrated_sources": wiki.get("integrated_sources"),
            "excluded_source_count": wiki.get("excluded_source_count"),
            "review_queue_count": wiki.get("review_queue_count"),
            "report_path": wiki.get("report_path"),
        },
        "index": {
            "status": index.get("status"),
            "raw_index_count": index.get("raw_index_count"),
            "wiki_index_count": index.get("wiki_index_count"),
            "changed_raw_count": index.get("changed_raw_count"),
            "changed_wiki_count": index.get("changed_wiki_count"),
            "manifest_path": index.get("manifest_path"),
        },
        "query": {
            "status": query.get("status"),
            "evidence_count": len(query.get("evidence") or []),
            "top_paths": [str(item.get("path") or "") for item in (query.get("evidence") or [])[:5]],
        }
        if query
        else None,
    }


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
    parser.add_argument("--compact-output", action="store_true", help="Print a compact operator summary instead of the full nested report.")
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
    output = _compact_result(result) if args.compact_output else result
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
