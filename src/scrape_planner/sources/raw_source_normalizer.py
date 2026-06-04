from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.site_layout import ensure_layout_for_site_root
from .source_quality import SourceQualityRecord, assess_source_quality, write_quality_report
from .source_registry import (
    RegistryMergeResult,
    build_source_row,
    checksum_text,
    merge_registry_rows,
    read_registry_rows,
    stable_source_id,
    utc_now_iso,
    write_registry_rows,
)
from ..core.storage import read_json, read_jsonl, write_json


MAX_PDF_RAW_MARKDOWN_CHARS = 20_000


@dataclass(frozen=True)
class NormalizationReport:
    counts: dict[str, int]
    registry_path: str
    report_path: str
    sources: list[dict[str, Any]]


def normalize_scraped_markdown(site_root: Path, run_root: Path, *, now: str | None = None) -> NormalizationReport:
    timestamp = now or utc_now_iso()
    layout = ensure_layout_for_site_root(site_root)
    manifest = read_json(Path(run_root) / "scrape_manifest.json", [])
    rows: list[dict[str, Any]] = []
    quality_records: list[SourceQualityRecord] = []
    seen_checksums: set[str] = set()

    for item in manifest if isinstance(manifest, list) else []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        fetch_mode = str(item.get("fetch_mode") or "").lower()
        metadata = _manifest_item_metadata(item, Path(run_root))
        if fetch_mode != "pdf" and _manifest_fetch_mode(metadata) == "pdf":
            fetch_mode = "pdf"
        if _is_pdf_manifest_item(item, metadata):
            pdf_path = _manifest_pdf_path(item, metadata)
            if str(item.get("status") or "") != "success":
                rows.append(
                    _failed_row(
                        layout.site_root,
                        source_kind="pdf",
                        title=_title_from_identity(url or "PDF source"),
                        identity=url or pdf_path or str(item.get("raw_html_path") or ""),
                        original_url=url,
                        original_path=pdf_path,
                        parser="scrape_worker.pdf",
                        error_reason=_pdf_manifest_error_reason(item, metadata),
                        now=timestamp,
                        provenance={
                            "run_root": str(run_root),
                            "scrape_manifest_path": str(Path(run_root) / "scrape_manifest.json"),
                        },
                    )
                )
            continue
        if str(item.get("status") or "") != "success":
            continue
        raw_markdown_path = str(item.get("markdown_path") or "").strip()
        if not raw_markdown_path:
            continue
        markdown_path = _manifest_path(raw_markdown_path, Path(run_root))
        path_error = _manifest_markdown_path_error(markdown_path, Path(run_root))
        if path_error:
            rows.append(
                _failed_row(
                    layout.site_root,
                    source_kind="web",
                    title=_title_from_identity(url or str(markdown_path)),
                    identity=url or str(markdown_path),
                    original_url=url,
                    original_path=str(markdown_path),
                    parser="scrape_worker.markdown",
                    error_reason=path_error,
                    now=timestamp,
                    provenance={
                        "run_root": str(run_root),
                        "scrape_manifest_path": str(Path(run_root) / "scrape_manifest.json"),
                    },
                )
            )
            continue

        try:
            markdown = markdown_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            rows.append(
                _failed_row(
                    layout.site_root,
                    source_kind="web",
                    title=_title_from_identity(url or str(markdown_path)),
                    identity=url or str(markdown_path),
                    original_url=url,
                    original_path=str(markdown_path),
                    parser="scrape_worker.markdown",
                    error_reason=f"Markdown path is not readable: {exc}",
                    now=timestamp,
                    provenance={
                        "run_root": str(run_root),
                        "scrape_manifest_path": str(Path(run_root) / "scrape_manifest.json"),
                    },
                )
            )
            continue
        source_id = stable_source_id("web", url or str(markdown_path))
        checksum = checksum_text(markdown)
        quality = assess_source_quality(
            markdown,
            source_id=source_id,
            parser_kind="scrape_worker.markdown",
            original_path=str(markdown_path),
            original_url=url,
            seen_checksums=seen_checksums,
        )
        quality_records.append(quality)
        seen_checksums.add(checksum)

        quality_report_rel = _site_relative(_quality_record_path(layout.site_root, source_id), layout.site_root)
        if quality.action == "quarantined":
            diagnostic_path = _write_quality_diagnostic(layout.site_root, quality, now=timestamp)
            metadata_path = layout.raw_reports_dir / f"{source_id}.metadata.json"
            write_json(
                metadata_path,
                {
                    "source_kind": "web",
                    "source_id": source_id,
                    "status": "failed",
                    "quality_action": quality.action,
                    "quality_reasons": quality.reasons,
                    "normalized_at": timestamp,
                },
            )
            rows.append(
                build_source_row(
                    source_id=source_id,
                    source_kind="web",
                    title=_extract_markdown_title(markdown, _title_from_identity(url or markdown_path.name)),
                    original_url=url,
                    original_path=str(markdown_path),
                    markdown_path="",
                    metadata_path=_site_relative(metadata_path, layout.site_root),
                    checksum=checksum,
                    parser="scrape_worker.markdown",
                    status="failed",
                    now=timestamp,
                    error_reason=", ".join(quality.reasons) or "Source quarantined by quality gate",
                    diagnostic_path=_site_relative(diagnostic_path, layout.site_root),
                    provenance={
                        "run_root": str(run_root),
                        "scrape_manifest_path": str(Path(run_root) / "scrape_manifest.json"),
                        "quality_action": quality.action,
                        "quality_report_path": quality_report_rel,
                    },
                )
            )
            continue

        stored_markdown = quality.cleaned_text if quality.action == "cleaned" else markdown
        checksum = checksum_text(stored_markdown)
        raw_path = layout.raw_web_dir / f"{source_id}-{checksum[:12]}.md"
        metadata_path = layout.raw_web_dir / f"{source_id}-{checksum[:12]}.metadata.json"
        raw_path.write_text(stored_markdown, encoding="utf-8")
        write_json(
            metadata_path,
            {
                "source_kind": "web",
                "source_id": source_id,
                "url": url,
                "run_root": str(run_root),
                "scrape_markdown_path": str(markdown_path),
                "scrape_metadata_path": str(item.get("metadata_path") or ""),
                "fetch_mode": str(item.get("fetch_mode") or ""),
                "quality_action": quality.action,
                "quality_reasons": quality.reasons,
                "quality_report_path": quality_report_rel,
                "original_checksum": quality.checksum,
                "cleaned": quality.action == "cleaned",
                "normalized_at": timestamp,
            },
        )
        rows.append(
            build_source_row(
                source_id=source_id,
                source_kind="web",
                title=_extract_markdown_title(markdown, _title_from_identity(url or markdown_path.name)),
                original_url=url,
                original_path=str(markdown_path),
                markdown_path=_site_relative(raw_path, layout.site_root),
                metadata_path=_site_relative(metadata_path, layout.site_root),
                checksum=checksum,
                parser="scrape_worker.markdown",
                status="needs-review" if quality.action == "needs_review" else "ready",
                now=timestamp,
                error_reason=", ".join(quality.reasons) if quality.action == "needs_review" else "",
                provenance={
                    "run_root": str(run_root),
                    "scrape_manifest_path": str(Path(run_root) / "scrape_manifest.json"),
                    "quality_action": quality.action,
                    "quality_report_path": quality_report_rel,
                },
            )
        )

    merge = merge_registry_rows(layout.registry_path, rows, now=timestamp)
    return _write_report(layout.site_root, "web", merge, rows, timestamp, quality_records=quality_records)


def normalize_pdf_pages(site_root: Path, *, now: str | None = None) -> NormalizationReport:
    timestamp = now or utc_now_iso()
    layout = ensure_layout_for_site_root(site_root)
    rows: list[dict[str, Any]] = []
    pages_root = layout.site_root / "sources" / "pdf_pages"
    pdf_url_index = _scrape_pdf_url_index(layout.site_root)

    page_groups: dict[str, list[dict[str, Any]]] = {}
    if pages_root.exists():
        for index_path in sorted(pages_root.glob("*/pages.json")):
            payload = read_json(index_path, [])
            for item in payload if isinstance(payload, list) else []:
                if isinstance(item, dict):
                    source_id = str(item.get("pdf_source_id") or index_path.parent.name)
                    page_groups.setdefault(source_id, []).append({**item, "_pages_index_path": str(index_path)})

    for pdf_source_id, page_rows in sorted(page_groups.items()):
        rows.extend(_normalize_pdf_page_group(layout.site_root, pdf_source_id, page_rows, timestamp))

    rows.extend(
        _normalize_pdf_chunk_fallbacks(
            layout.site_root,
            timestamp,
            skip_pdf_source_ids=set(page_groups),
            skip_source_ids={str(row.get("source_id") or "") for row in rows},
            pdf_url_index=pdf_url_index,
        )
    )

    _prune_replaced_pdf_page_rows(
        layout.registry_path,
        affected_pdf_source_ids=set(page_groups),
        incoming_source_ids={str(row.get("source_id") or "") for row in rows},
    )
    merge = merge_registry_rows(layout.registry_path, rows, now=timestamp)
    return _write_report(layout.site_root, "pdf", merge, rows, timestamp)


def normalize_tabular_sources(site_root: Path, paths: list[str | Path], *, now: str | None = None) -> NormalizationReport:
    timestamp = now or utc_now_iso()
    layout = ensure_layout_for_site_root(site_root)
    rows: list[dict[str, Any]] = []

    for raw_path in paths:
        path = Path(raw_path)
        normalized_path = _stable_path_string(path)
        if not path.exists() or not path.is_file():
            rows.append(
                _failed_row(
                    layout.site_root,
                    source_kind="excel",
                    title=path.name or "missing tabular source",
                    identity=normalized_path,
                    original_url="",
                    original_path=normalized_path,
                    parser=_tabular_parser_name(path),
                    error_reason="File does not exist",
                    now=timestamp,
                )
            )
            continue
        try:
            markdown, metadata, parser = _tabular_to_markdown(path)
        except Exception as exc:
            rows.append(
                _failed_row(
                    layout.site_root,
                    source_kind="excel",
                    title=path.name,
                    identity=normalized_path,
                    original_url="",
                    original_path=normalized_path,
                    parser=_tabular_parser_name(path),
                    error_reason=str(exc),
                    now=timestamp,
                )
            )
            continue

        source_id = stable_source_id("excel", normalized_path)
        checksum = checksum_text(markdown)
        raw_markdown_path = layout.raw_excel_dir / f"{source_id}-{checksum[:12]}.md"
        metadata_path = layout.raw_excel_dir / f"{source_id}-{checksum[:12]}.metadata.json"
        raw_markdown_path.write_text(markdown, encoding="utf-8")
        write_json(
            metadata_path,
            {
                "source_kind": "excel",
                "source_id": source_id,
                "original_path": normalized_path,
                "parser": parser,
                "normalized_at": timestamp,
                **metadata,
            },
        )
        error_reason = _tabular_review_reason(metadata, markdown)
        status = "needs-review" if error_reason else "ready"
        diagnostic_path = ""
        if error_reason:
            diagnostic_path = _site_relative(
                _write_diagnostic(
                    layout.site_root,
                    source_kind="excel",
                    source_id=source_id,
                    original_url="",
                    original_path=normalized_path,
                    parser=parser,
                    error_reason=error_reason,
                    now=timestamp,
                    metadata={"tables": metadata.get("tables", [])},
                ),
                layout.site_root,
            )
        rows.append(
            build_source_row(
                source_id=source_id,
                source_kind="excel",
                title=path.name,
                original_url="",
                original_path=normalized_path,
                markdown_path=_site_relative(raw_markdown_path, layout.site_root),
                metadata_path=_site_relative(metadata_path, layout.site_root),
                checksum=checksum,
                parser=parser,
                status=status,
                now=timestamp,
                provenance={"input_path": normalized_path},
                error_reason=error_reason,
                diagnostic_path=diagnostic_path,
            )
        )

    merge = merge_registry_rows(layout.registry_path, rows, now=timestamp)
    return _write_report(layout.site_root, "excel", merge, rows, timestamp)


def run_normalization_command(
    *,
    site_root: Path,
    kind: str,
    run_root: Path | None = None,
    tabular_paths: list[str | Path] | None = None,
    no_input: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    mode = str(kind or "all").lower()
    reports: list[NormalizationReport] = []
    if mode in {"all", "web"}:
        if run_root is None:
            raise ValueError("--run-root is required for web normalization")
        reports.append(normalize_scraped_markdown(Path(site_root), Path(run_root), now=now))
    if mode in {"all", "pdf"}:
        reports.append(normalize_pdf_pages(Path(site_root), now=now))
    if mode in {"all", "excel", "csv", "tabular"}:
        reports.append(normalize_tabular_sources(Path(site_root), list(tabular_paths or []), now=now))
    if not reports:
        raise ValueError(f"Unsupported normalization kind: {kind}")
    counts = {key: 0 for key in ("new", "unchanged", "changed", "ready", "failed", "needs-review")}
    for report in reports:
        for key, value in report.counts.items():
            counts[key] = counts.get(key, 0) + int(value or 0)
    return {
        "mode": mode,
        "no_input": bool(no_input),
        "site_root": str(site_root),
        "registry_path": reports[-1].registry_path,
        "report_paths": [report.report_path for report in reports],
        "counts": counts,
    }


def _normalize_pdf_page_group(site_root: Path, pdf_source_id: str, page_rows: list[dict[str, Any]], now: str) -> list[dict[str, Any]]:
    layout = ensure_layout_for_site_root(site_root)
    source_path = str(next((row.get("source_path") for row in page_rows if row.get("source_path")), ""))
    original_url = _first_text(page_rows, "original_url", "url", "source_url")
    source_identity = _pdf_identity(original_url, source_path, pdf_source_id)
    parser_values = sorted({str(row.get("parser") or "") for row in page_rows if row.get("parser")})
    parser = parser_values[0] if len(parser_values) == 1 else ("mixed" if parser_values else "pdf_pages")
    document_title = Path(source_path).name or pdf_source_id
    normalized_rows: list[dict[str, Any]] = []
    page_entries: list[dict[str, Any]] = []

    for row in sorted(page_rows, key=lambda item: int(item.get("page_number") or 0)):
        md_path = Path(str(row.get("markdown_path") or ""))
        if not md_path.exists():
            continue
        text = md_path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            continue
        raw_page_number = int(row.get("page_number") or 0)
        parts = _split_pdf_markdown_for_raw_sources(text)
        part_count = len(parts)
        for part_index, part_text in enumerate(parts, start=1):
            page_number = raw_page_number if raw_page_number > 0 else part_index
            section_path = _section_path_from_markdown(part_text)
            page_tables = _markdown_tables(part_text, page_number=page_number, section_path=section_path)
            page_entries.append(
                {
                    "text": part_text,
                    "page_number": page_number,
                    "raw_page_number": raw_page_number,
                    "part_index": part_index if part_count > 1 else 0,
                    "part_count": part_count,
                    "section_path": section_path,
                    "tables": page_tables,
                    "source_markdown_path": str(md_path),
                    "pages_index_path": str(row.get("_pages_index_path") or ""),
                }
            )

    if not page_entries:
        return [
            _failed_row(
                layout.site_root,
                source_kind="pdf",
                title=document_title,
                identity=source_identity,
                original_url=original_url,
                original_path=source_path,
                parser=parser,
                error_reason="No PDF page markdown was readable",
                now=now,
                provenance={"pdf_source_id": pdf_source_id},
            )
        ]

    document_page_numbers = sorted({int(entry["raw_page_number"] or entry["page_number"] or 0) for entry in page_entries})
    document_page_count = len(document_page_numbers)
    for entry in page_entries:
        page_number = int(entry["page_number"] or 0)
        raw_page_number = int(entry["raw_page_number"] or 0)
        part_index = int(entry["part_index"] or 0)
        part_count = int(entry["part_count"] or 1)
        page_identity = f"{source_identity}#page={raw_page_number or page_number:04d}"
        if part_index:
            page_identity = f"{page_identity}-part={part_index:03d}"
        source_id = stable_source_id("pdf", page_identity)
        markdown = str(entry["text"]).strip() + "\n"
        checksum = checksum_text(markdown)
        raw_path = layout.raw_pdf_dir / f"{source_id}-{checksum[:12]}.md"
        metadata_path = layout.raw_pdf_dir / f"{source_id}-{checksum[:12]}.metadata.json"
        sidecar_path = layout.raw_pdf_dir / f"{source_id}-{checksum[:12]}.tables.json"
        tables = list(entry["tables"])
        source_pages = [
            {
                "page_number": page_number,
                "page_start": page_number,
                "page_end": page_number,
                "raw_page_number": raw_page_number,
                "part_index": part_index,
                "part_count": part_count,
                "section_path": str(entry["section_path"]),
                "table_ids": [str(table["table_id"]) for table in tables],
                "char_count": len(markdown),
                "markdown_path": str(entry["source_markdown_path"]),
                "pages_index_path": str(entry["pages_index_path"]),
            }
        ]
        page_label = f"p. {raw_page_number or page_number}"
        if part_index:
            page_label = f"{page_label} part {part_index}"
        title = f"{document_title} {page_label}"
        raw_path.write_text(markdown, encoding="utf-8")
        if tables:
            write_json(sidecar_path, {"source_id": source_id, "tables": tables, "generated_at": now})
        write_json(
            metadata_path,
            {
                "source_kind": "pdf",
                "source_id": source_id,
                "source_type": "document-page",
                "pdf_source_id": pdf_source_id,
                "title": title,
                "original_url": original_url,
                "source_path": source_path,
                "parser": parser,
                "parser_version": parser,
                "page_count": 1,
                "document_page_count": document_page_count,
                "page_number": page_number,
                "page_start": page_number,
                "page_end": page_number,
                "part_index": part_index,
                "part_count": part_count,
                "source_pages": source_pages,
                "sections": _unique_section_paths(source_pages),
                "tables": tables,
                "tables_path": _site_relative(sidecar_path, layout.site_root) if tables else "",
                "extraction_warnings": [],
                "document_quality": _document_quality(markdown, source_pages, tables),
                "normalized_at": now,
            },
        )
        normalized_rows.append(
            build_source_row(
                source_id=source_id,
                source_kind="pdf",
                title=title,
                original_url=original_url,
                original_path=source_path,
                markdown_path=_site_relative(raw_path, layout.site_root),
                metadata_path=_site_relative(metadata_path, layout.site_root),
                checksum=checksum,
                parser=parser,
                status="ready",
                now=now,
                provenance={
                    "pdf_source_id": pdf_source_id,
                    "page_number": page_number,
                    "raw_page_number": raw_page_number,
                    "part_index": part_index,
                    "part_count": part_count,
                },
            )
        )
    return normalized_rows


def _split_pdf_markdown_for_raw_sources(text: str) -> list[str]:
    cleaned = str(text or "").strip()
    if len(cleaned) <= MAX_PDF_RAW_MARKDOWN_CHARS:
        return [cleaned] if cleaned else []
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for block in re.split(r"\n{2,}", cleaned):
        block = block.strip()
        if not block:
            continue
        if len(block) > MAX_PDF_RAW_MARKDOWN_CHARS:
            if current:
                chunks.append("\n\n".join(current).strip())
                current = []
                current_len = 0
            for start in range(0, len(block), MAX_PDF_RAW_MARKDOWN_CHARS):
                chunks.append(block[start : start + MAX_PDF_RAW_MARKDOWN_CHARS].strip())
            continue
        projected = current_len + len(block) + (2 if current else 0)
        if current and projected > MAX_PDF_RAW_MARKDOWN_CHARS:
            chunks.append("\n\n".join(current).strip())
            current = [block]
            current_len = len(block)
        else:
            current.append(block)
            current_len = projected
    if current:
        chunks.append("\n\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def _prune_replaced_pdf_page_rows(registry_path: Path, *, affected_pdf_source_ids: set[str], incoming_source_ids: set[str]) -> None:
    if not affected_pdf_source_ids:
        return
    rows = read_registry_rows(registry_path)
    kept: list[dict[str, Any]] = []
    changed = False
    for row in rows:
        provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
        pdf_source_id = str(provenance.get("pdf_source_id") or "")
        source_id = str(row.get("source_id") or "")
        if (
            str(row.get("source_kind") or "") == "pdf"
            and pdf_source_id in affected_pdf_source_ids
            and source_id not in incoming_source_ids
        ):
            changed = True
            continue
        kept.append(row)
    if changed:
        write_registry_rows(registry_path, kept)


def _normalize_pdf_chunk_fallbacks(
    site_root: Path,
    now: str,
    *,
    skip_pdf_source_ids: set[str] | None = None,
    skip_source_ids: set[str] | None = None,
    pdf_url_index: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    layout = ensure_layout_for_site_root(site_root)
    skipped = skip_pdf_source_ids or set()
    protected_source_ids = {source_id for source_id in (skip_source_ids or set()) if source_id}
    rows_by_source_id: dict[str, dict[str, Any]] = {}
    url_index = pdf_url_index or _scrape_pdf_url_index(layout.site_root)
    site_ingest_dir = (layout.site_root / "sources" / "pdf_ingest").resolve()
    for artifact_dir in _pdf_ingest_artifact_dirs(layout.site_root):
        is_site_level_artifact = artifact_dir.resolve() == site_ingest_dir
        chunks_path = artifact_dir / "pdf_chunks.jsonl"
        sources_path = artifact_dir / "pdf_sources.jsonl"
        quarantine_path = artifact_dir / "pdf_quarantine.jsonl"
        source_rows = {str(row.get("pdf_source_id") or ""): row for row in read_jsonl(sources_path)}
        quarantine_rows = {str(row.get("pdf_source_id") or ""): row for row in read_jsonl(quarantine_path)}
        chunks_by_source: dict[str, list[dict[str, Any]]] = {}
        for row in read_jsonl(chunks_path):
            pdf_source_id = str(row.get("pdf_source_id") or "")
            if pdf_source_id:
                chunks_by_source.setdefault(pdf_source_id, []).append(row)

        pdf_source_ids = set(source_rows) | set(chunks_by_source) | set(quarantine_rows)
        for pdf_source_id in sorted(pdf_source_ids):
            if not pdf_source_id or pdf_source_id in skipped:
                continue
            chunks = chunks_by_source.get(pdf_source_id, [])
            source = source_rows.get(pdf_source_id, {})
            quarantine = quarantine_rows.get(pdf_source_id, {})
            source_path = str(
                source.get("source_path")
                or source.get("path")
                or quarantine.get("source_path")
                or quarantine.get("path")
                or (chunks[0].get("source_path") if chunks else "")
                or ""
            )
            original_url = _pdf_original_url(source, quarantine, chunks) or _lookup_scraped_pdf_url(url_index, source_path)
            source_identity = _pdf_identity(original_url, source_path, pdf_source_id)
            source_id = stable_source_id("pdf", source_identity)
            if source_id in protected_source_ids:
                continue
            parser_values = sorted(
                {
                    str(value)
                    for value in [source.get("parser"), quarantine.get("parser"), *(row.get("parser") for row in chunks)]
                    if value
                }
            )
            parser = parser_values[0] if len(parser_values) == 1 else ("mixed" if parser_values else "pdf_chunks")
            provenance = {
                "pdf_source_id": pdf_source_id,
                "pdf_sources_path": str(sources_path),
                "pdf_chunks_path": str(chunks_path),
                "pdf_quarantine_path": str(quarantine_path),
            }
            body = "\n\n".join(str(row.get("text") or "").strip() for row in chunks if str(row.get("text") or "").strip())
            if not body:
                row = _failed_row(
                    layout.site_root,
                    source_kind="pdf",
                    title=Path(source_path).name or pdf_source_id,
                    identity=source_identity,
                    original_url=original_url,
                    original_path=source_path,
                    parser=parser,
                    error_reason=_pdf_error_reason(quarantine, chunks),
                    now=now,
                    provenance=provenance,
                )
                rows_by_source_id[source_id] = row
                if is_site_level_artifact:
                    protected_source_ids.add(source_id)
                continue
            markdown = f"# {Path(source_path).name or pdf_source_id}\n\n{body.strip()}\n"
            checksum = checksum_text(markdown)
            raw_path = layout.raw_pdf_dir / f"{source_id}-{checksum[:12]}.md"
            metadata_path = layout.raw_pdf_dir / f"{source_id}-{checksum[:12]}.metadata.json"
            source_chunks = _source_chunks_metadata(chunks)
            tables = [
                table
                for chunk in chunks
                for table in _markdown_tables(
                    str(chunk.get("text") or ""),
                    page_number=int(chunk.get("page_number") or 0),
                    section_path=str(chunk.get("section_path") or ""),
                )
            ]
            sidecar_path = layout.raw_pdf_dir / f"{source_id}-{checksum[:12]}.tables.json"
            raw_path.write_text(markdown, encoding="utf-8")
            if tables:
                write_json(sidecar_path, {"source_id": source_id, "tables": tables, "generated_at": now})
            write_json(
                metadata_path,
                {
                    "source_kind": "pdf",
                    "source_id": source_id,
                    "source_type": "document",
                    "pdf_source_id": pdf_source_id,
                    "title": Path(source_path).name or pdf_source_id,
                    "original_url": original_url,
                    "source_path": source_path,
                    "parser": parser,
                    "parser_version": parser,
                    "chunk_count": len(chunks),
                    "source_chunks": source_chunks,
                    "sections": _unique_section_paths(source_chunks),
                    "tables": tables,
                    "tables_path": _site_relative(sidecar_path, layout.site_root) if tables else "",
                    "extraction_warnings": _pdf_extraction_warnings(source, quarantine, chunks),
                    "document_quality": _document_quality(markdown, source_chunks, tables),
                    "normalized_at": now,
                },
            )
            rows_by_source_id[source_id] = build_source_row(
                source_id=source_id,
                source_kind="pdf",
                title=Path(source_path).name or pdf_source_id,
                original_url=original_url,
                original_path=source_path,
                markdown_path=_site_relative(raw_path, layout.site_root),
                metadata_path=_site_relative(metadata_path, layout.site_root),
                checksum=checksum,
                parser=parser,
                status="ready",
                now=now,
                provenance=provenance,
            )
            if is_site_level_artifact:
                protected_source_ids.add(source_id)
    return [rows_by_source_id[source_id] for source_id in sorted(rows_by_source_id)]


def _pdf_ingest_artifact_dirs(site_root: Path) -> list[Path]:
    candidates = [site_root / "sources" / "pdf_ingest"]
    candidates.extend(sorted(path for path in site_root.glob("*/s05") if path.is_dir()))
    seen: set[Path] = set()
    dirs: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if any((path / name).exists() for name in ("pdf_sources.jsonl", "pdf_chunks.jsonl", "pdf_quarantine.jsonl")):
            dirs.append(path)
    return dirs


def _pdf_error_reason(quarantine: dict[str, Any], chunks: list[dict[str, Any]]) -> str:
    for key in ("error_reason", "error", "reason", "message"):
        value = str(quarantine.get(key) or "").strip()
        if value:
            return value
    if chunks:
        return "PDF source produced no usable markdown chunks"
    return "PDF source produced no usable markdown"


def _source_chunks_metadata(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in sorted(chunks, key=lambda item: (int(item.get("page_number") or 0), int(item.get("chunk_index") or 0))):
        page_number = int(row.get("page_number") or 0)
        text = str(row.get("text") or "")
        section_path = str(row.get("section_path") or "").strip() or _section_path_from_markdown(text)
        table_ids = [
            str(table["table_id"]) for table in _markdown_tables(text, page_number=page_number, section_path=section_path)
        ]
        rows.append(
            {
                "chunk_id": str(row.get("chunk_id") or ""),
                "page_number": page_number,
                "page_start": int(row.get("page_start") or page_number),
                "page_end": int(row.get("page_end") or page_number),
                "chunk_index": int(row.get("chunk_index") or 0),
                "section_path": section_path,
                "table_ids": table_ids,
                "char_count": int(row.get("char_count") or len(text)),
            }
        )
    return rows


def _section_path_from_markdown(text: str) -> str:
    headings: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}(#{1,4})\s+(.+?)\s*$", line)
        if not match:
            continue
        level = len(match.group(1))
        title = re.sub(r"\s+", " ", match.group(2)).strip()
        headings = headings[: max(0, level - 1)]
        headings.append(title)
        if len(headings) >= 3:
            break
    return " > ".join(headings)


def _markdown_tables(text: str, *, page_number: int, section_path: str) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    lines = text.splitlines()
    idx = 0
    while idx < len(lines) - 1:
        header = lines[idx].strip()
        separator = lines[idx + 1].strip()
        if _is_markdown_table_header(header, separator):
            table_lines = [header, separator]
            idx += 2
            while idx < len(lines) and lines[idx].strip().startswith("|"):
                table_lines.append(lines[idx].strip())
                idx += 1
            table_id = f"p{page_number:04d}-t{len(tables) + 1:03d}"
            tables.append(
                {
                    "table_id": table_id,
                    "page_number": page_number,
                    "section_path": section_path,
                    "row_count": max(0, len(table_lines) - 2),
                    "markdown": "\n".join(table_lines),
                }
            )
            continue
        idx += 1
    return tables


def _is_markdown_table_header(header: str, separator: str) -> bool:
    if not header.startswith("|") or not separator.startswith("|"):
        return False
    cells = [cell.strip() for cell in separator.strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def _unique_section_paths(rows: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for row in rows:
        value = str(row.get("section_path") or "").strip()
        if value and value not in values:
            values.append(value)
    return values


def _pdf_extraction_warnings(source: dict[str, Any], quarantine: dict[str, Any], chunks: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for row in [source, quarantine, *chunks]:
        for key in ("warning", "warnings", "extraction_warning", "extraction_warnings", "detail", "reason"):
            value = row.get(key)
            if isinstance(value, list):
                for item in value:
                    _append_warning(warnings, str(item))
            else:
                _append_warning(warnings, str(value or ""))
    return warnings


def _append_warning(warnings: list[str], value: str) -> None:
    text = value.strip()
    if text and text not in warnings:
        warnings.append(text)


def _document_quality(markdown: str, units: list[dict[str, Any]], tables: list[dict[str, Any]]) -> dict[str, Any]:
    page_numbers = [int(row.get("page_number") or row.get("page_start") or 0) for row in units]
    page_count = len(set(page_numbers)) if page_numbers else 0
    char_count = len(markdown)
    empty_sections = sum(1 for row in units if int(row.get("char_count") or 0) == 0)
    chars_per_page = round(char_count / page_count, 2) if page_count else 0.0
    repeated_header_footer = _repeated_header_footer_detected(markdown)
    warnings: list[str] = []
    if page_count and chars_per_page < 80:
        warnings.append("low_chars_per_page")
    if not tables:
        warnings.append("no_tables_detected")
    if repeated_header_footer:
        warnings.append("repeated_header_footer_detected")
    return {
        "page_coverage_count": page_count,
        "chars_per_page": chars_per_page,
        "table_count": len(tables),
        "table_preservation_warnings": [] if tables else ["no_tables_detected"],
        "ocr_required_pages": [],
        "repeated_header_footer_detected": repeated_header_footer,
        "empty_section_count": empty_sections,
        "warnings": warnings,
    }


def _repeated_header_footer_detected(markdown: str) -> bool:
    lines = [re.sub(r"\s+", " ", line.strip().lower()) for line in markdown.splitlines() if line.strip()]
    counts = Counter(lines)
    return any(count >= 3 and len(line.split()) <= 8 for line, count in counts.items())


def _tabular_to_markdown(path: Path) -> tuple[str, dict[str, Any], str]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows = _read_csv_rows(path)
        markdown = _rows_to_markdown(path.stem, rows)
        return (
            markdown,
            {
                "tables": [
                    {
                        "name": path.stem,
                        "rows": max(0, len(rows) - 1),
                        "meaningful_cell_count": _meaningful_cell_count(rows[1:]),
                    }
                ]
            },
            "pandas.csv",
        )

    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - depends on optional Excel install
        raise RuntimeError("pandas is required for Excel normalization") from exc

    sheets = pd.read_excel(path, sheet_name=None)
    sections: list[str] = []
    tables: list[dict[str, Any]] = []
    for sheet_name, df in sheets.items():
        headers = [str(col) for col in df.columns.tolist()]
        data_rows = [[_cell_to_text(value) for value in row] for row in df.fillna("").values.tolist()]
        rows = [headers] + data_rows
        sections.append(_rows_to_markdown(str(sheet_name), rows))
        tables.append(
            {
                "name": str(sheet_name),
                "rows": len(data_rows),
                "columns": headers,
                "meaningful_cell_count": _meaningful_cell_count(data_rows),
            }
        )
    return "\n\n".join(sections).strip() + "\n", {"tables": tables}, "pandas.excel"


def _read_csv_rows(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        return [[str(cell) for cell in row] for row in reader]


def _rows_to_markdown(title: str, rows: list[list[str]]) -> str:
    if not rows:
        return f"# {title}\n"
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    header = padded[0]
    body = padded[1:]
    lines = [f"# {title}", ""]
    lines.append("| " + " | ".join(_escape_cell(cell) for cell in header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in body:
        lines.append("| " + " | ".join(_escape_cell(cell) for cell in row) + " |")
    return "\n".join(lines).strip() + "\n"


def _tabular_review_reason(metadata: dict[str, Any], markdown: str) -> str:
    tables = metadata.get("tables")
    if not isinstance(tables, list) or not tables:
        return "Tabular source produced no tables"
    row_counts = [int(table.get("rows") or 0) for table in tables if isinstance(table, dict)]
    if not row_counts or sum(row_counts) <= 0:
        return "Tabular source produced no data rows"
    if not markdown.strip():
        return "Tabular source produced empty markdown"
    meaningful_cell_counts = [
        int(table.get("meaningful_cell_count") or 0) for table in tables if isinstance(table, dict)
    ]
    if not meaningful_cell_counts or sum(meaningful_cell_counts) <= 0:
        return "Tabular source produced no meaningful data cells"
    return ""


def _manifest_path(raw_path: str, run_root: Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return Path(run_root) / path


def _manifest_markdown_path_error(path: Path, run_root: Path) -> str:
    if not _is_relative_to(path, run_root):
        return "Markdown path resolves outside run root"
    try:
        if not path.exists():
            return "Markdown file does not exist"
        if not path.is_file():
            return "Markdown path is not a file"
    except OSError as exc:
        return f"Markdown path is not readable: {exc}"
    return ""


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _stable_path_string(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path.absolute())


def _first_text(rows: list[dict[str, Any]], *keys: str) -> str:
    for row in rows:
        for key in keys:
            value = str(row.get(key) or "").strip()
            if value:
                return value
    return ""


def _manifest_item_metadata(item: dict[str, Any], run_root: Path) -> dict[str, Any]:
    metadata_path = str(item.get("metadata_path") or "").strip()
    if not metadata_path:
        return {}
    payload = read_json(_manifest_path(metadata_path, run_root), {})
    return payload if isinstance(payload, dict) else {}


def _manifest_fetch_mode(metadata: dict[str, Any]) -> str:
    return str(metadata.get("fetch_mode") or "").lower()


def _manifest_pdf_path(item: dict[str, Any], metadata: dict[str, Any]) -> str:
    for value in (
        item.get("pdf_path"),
        item.get("raw_html_path"),
        metadata.get("pdf_path"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _is_pdf_manifest_item(item: dict[str, Any], metadata: dict[str, Any]) -> bool:
    fetch_mode = str(item.get("fetch_mode") or "").lower()
    if fetch_mode == "pdf" or _manifest_fetch_mode(metadata) == "pdf":
        return True
    url = str(item.get("url") or "").strip()
    return url.lower().endswith(".pdf")


def _pdf_manifest_error_reason(item: dict[str, Any], metadata: dict[str, Any]) -> str:
    for value in (
        item.get("failure_reason"),
        metadata.get("failure_reason"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    quarantine = metadata.get("pdf_quarantine")
    if isinstance(quarantine, list):
        for row in quarantine:
            if not isinstance(row, dict):
                continue
            for key in ("reason", "error_reason", "detail"):
                text = str(row.get(key) or "").strip()
                if text:
                    return text
    return "pdf_scrape_failed"


def _scrape_pdf_url_index(site_root: Path) -> dict[str, str]:
    index: dict[str, str] = {}
    for manifest_path in sorted(site_root.glob("*/scrape_manifest.json")):
        run_root = manifest_path.parent
        for item in read_json(manifest_path, []):
            if not isinstance(item, dict):
                continue
            metadata = _manifest_item_metadata(item, run_root)
            url = str(item.get("url") or metadata.get("url") or "").strip()
            if not url:
                continue
            index.setdefault(url, url)
            for path_value in (
                item.get("pdf_path"),
                item.get("raw_html_path"),
                metadata.get("pdf_path"),
            ):
                path_text = str(path_value or "").strip()
                if path_text:
                    index[_stable_path_string(Path(path_text))] = url
    return index


def _lookup_scraped_pdf_url(index: dict[str, str], source_path: str) -> str:
    raw = str(source_path or "").strip()
    if not raw:
        return ""
    return str(index.get(_stable_path_string(Path(raw))) or index.get(raw) or "").strip()


def _pdf_original_url(source: dict[str, Any], quarantine: dict[str, Any], chunks: list[dict[str, Any]]) -> str:
    for row in [source, quarantine, *chunks]:
        for key in ("original_url", "url", "source_url"):
            value = str(row.get(key) or "").strip()
            if value:
                return value
    return ""


def _pdf_identity(original_url: str, source_path: str, pdf_source_id: str) -> str:
    return str(original_url or source_path or pdf_source_id)


def _write_diagnostic(
    site_root: Path,
    *,
    source_kind: str,
    source_id: str,
    original_url: str,
    original_path: str,
    parser: str,
    error_reason: str,
    now: str,
    metadata: dict[str, Any] | None = None,
) -> Path:
    layout = ensure_layout_for_site_root(site_root)
    diagnostic_path = layout.raw_reports_dir / f"{source_id}.error.json"
    write_json(
        diagnostic_path,
        {
            "source_kind": source_kind,
            "source_id": source_id,
            "original_url": original_url,
            "original_path": original_path,
            "parser": parser,
            "error_reason": error_reason,
            "normalized_at": now,
            **(metadata or {}),
        },
    )
    return diagnostic_path


def _failed_row(
    site_root: Path,
    *,
    source_kind: str,
    title: str,
    identity: str,
    original_url: str,
    original_path: str,
    parser: str,
    error_reason: str,
    now: str,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    layout = ensure_layout_for_site_root(site_root)
    source_id = stable_source_id(source_kind, identity)
    diagnostic_path = _write_diagnostic(
        layout.site_root,
        source_kind=source_kind,
        source_id=source_id,
        original_url=original_url,
        original_path=original_path,
        parser=parser,
        error_reason=error_reason,
        now=now,
    )
    metadata_path = layout.raw_reports_dir / f"{source_id}.metadata.json"
    write_json(metadata_path, {"source_kind": source_kind, "source_id": source_id, "status": "failed", "normalized_at": now})
    return build_source_row(
        source_id=source_id,
        source_kind=source_kind,
        title=title,
        original_url=original_url,
        original_path=original_path,
        markdown_path="",
        metadata_path=_site_relative(metadata_path, layout.site_root),
        checksum="",
        parser=parser,
        status="failed",
        now=now,
        error_reason=error_reason,
        diagnostic_path=_site_relative(diagnostic_path, layout.site_root),
        provenance=provenance,
    )


def _write_report(
    site_root: Path,
    source_kind: str,
    merge: RegistryMergeResult,
    attempted_rows: list[dict[str, Any]],
    now: str,
    *,
    quality_records: list[SourceQualityRecord] | None = None,
) -> NormalizationReport:
    layout = ensure_layout_for_site_root(site_root)
    report_path = layout.raw_reports_dir / f"normalization-{source_kind}-{_safe_timestamp(now)}.json"
    quality_report_path = ""
    quality_summary: dict[str, Any] = {}
    if quality_records is not None:
        quality_report_file = _quality_report_path(layout.site_root, now)
        quality_report = write_quality_report(quality_report_file, generated_at=now, records=quality_records)
        quality_report_path = str(quality_report_file)
        quality_summary = quality_report.get("summary", {})
    report = {
        "source_kind": source_kind,
        "generated_at": now,
        "registry_path": str(layout.registry_path),
        "counts": merge.counts,
        "quality_report_path": quality_report_path,
        "quality_summary": quality_summary,
        "attempted_source_ids": [str(row.get("source_id") or "") for row in attempted_rows],
        "sources": attempted_rows,
    }
    write_json(report_path, report)
    return NormalizationReport(
        counts=merge.counts,
        registry_path=str(layout.registry_path),
        report_path=str(report_path),
        sources=attempted_rows,
    )


def _quality_report_path(site_root: Path, now: str) -> Path:
    layout = ensure_layout_for_site_root(site_root)
    return layout.raw_reports_dir / f"source-quality-{_safe_timestamp(now)}.json"


def _quality_record_path(site_root: Path, source_id: str) -> Path:
    layout = ensure_layout_for_site_root(site_root)
    return layout.raw_reports_dir / f"{source_id}.quality.json"


def _write_quality_diagnostic(site_root: Path, quality: SourceQualityRecord, *, now: str) -> Path:
    diagnostic_path = _write_diagnostic(
        site_root,
        source_kind="web",
        source_id=quality.source_id,
        original_url=quality.original_url,
        original_path=quality.original_path,
        parser=quality.parser_kind,
        error_reason=", ".join(quality.reasons) or "Source quarantined by quality gate",
        now=now,
        metadata={
            "quality": quality.to_dict(),
            "recommended_parser_route": quality.recommended_parser_route,
        },
    )
    _quality_record_path(site_root, quality.source_id).write_text(
        json.dumps(quality.to_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return diagnostic_path


def _site_relative(path: Path, site_root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(site_root).resolve()))
    except ValueError:
        return str(path)


def _extract_markdown_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines()[:80]:
        match = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()[:240]
    return fallback


def _title_from_identity(value: str) -> str:
    raw = str(value or "").rstrip("/")
    if not raw:
        return "Untitled source"
    return raw.rsplit("/", 1)[-1] or raw


def _tabular_parser_name(path: Path) -> str:
    return "pandas.csv" if path.suffix.lower() == ".csv" else "pandas.excel"


def _escape_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _cell_to_text(value: Any) -> str:
    return "" if value is None else str(value)


def _meaningful_cell_count(rows: list[list[str]]) -> int:
    return sum(1 for row in rows for cell in row if str(cell or "").strip())


def _safe_timestamp(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "-", value).strip("-") or "run"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize local source artifacts into raw_sources without prompts.")
    parser.add_argument("--site-root", required=True)
    parser.add_argument("--kind", choices=["all", "web", "pdf", "excel", "csv", "tabular"], default="all")
    parser.add_argument("--run-root")
    parser.add_argument("--tabular-path", action="append", default=[])
    parser.add_argument("--no-input", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run_normalization_command(
            site_root=Path(args.site_root),
            kind=args.kind,
            run_root=Path(args.run_root) if args.run_root else None,
            tabular_paths=[Path(path) for path in args.tabular_path],
            no_input=args.no_input,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
