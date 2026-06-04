from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests

from ..runtime.run_persistence import _append_jsonl, _write_json_atomic
from ..runtime.agent_run_metrics import AgentRunMetricsRepository, build_embedding_metric_event
from ..runtime.openrouter_pricing import embedding_price_per_million_input_tokens, resolve_embedding_metric_cost
from ..core.site_layout import ensure_layout_for_site_root, site_layout
from ..sources.source_registry import checksum_file, checksum_text, read_registry_rows, utc_now_iso
from ..core.wiki_common import parse_markdown_frontmatter, site_relative, strip_markdown_frontmatter, timestamp_slug
from ..index.embedding_client import embed_text, embed_texts, embedding_config_from_env
from ..index.zvec_store import ZvecStoreUnavailable, query_zvec_documents, replace_zvec_documents, zvec_ready
from .confidence import assess_confidence
from .index_lock import site_index_write_lock
from .leadership import leadership_text_boost
from .query_intent import is_leadership_query, prepare_retrieval_query


INDEX_VERSION = "llm-wiki-hybrid-v2"
EMBEDDING_PROVIDER = "openrouter"
EMBEDDING_MODEL = os.getenv("OPENROUTER_EMBED_MODEL", "openai/text-embedding-3-small").strip() or "openai/text-embedding-3-small"
EMBEDDING_DIMENSIONS = int(os.getenv("OPENROUTER_EMBED_DIMENSIONS", "1536") or "1536")
EMBEDDING_TEXT_CHAR_LIMIT = 8000
EMBEDDING_SPACE_DENSE = "dense-openrouter"
EMBEDDING_SPACE_HASH = "hash-fallback"
FALLBACK_EMBEDDING_PROVIDER = "hash"
FALLBACK_EMBEDDING_MODEL = "sha256-keyword"
RERANK_PROVIDER = "openrouter"
RERANK_API_URL = "https://openrouter.ai/api/v1/rerank"
RERANK_MODEL = "cohere/rerank-4-pro"
TOKEN_RE = re.compile(r"[a-z0-9]+")
_DENSE_EMBEDDING_UNAVAILABLE = False
_EMBEDDING_DEGRADED = False
RAW_SUPPORT_SCORE_FACTOR = 0.05
RAW_SUPPORT_SCORE_CAP = 0.25
_LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[dict[str, Any]], None]

try:
    import bm25s as _BM25S_MODULE
except ImportError:
    _BM25S_MODULE = None

BM25_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "whom",
    "whose",
    "with",
}


@dataclass(frozen=True)
class IndexedDocument:
    id: str
    corpus: str
    source_kind: str
    source_id: str
    source_ids: list[str]
    path: str
    title: str
    checksum: str
    parser: str
    tags: list[str]
    updated_at: str
    text: str
    chunk_index: int
    metadata: dict[str, Any]


@dataclass(frozen=True)
class QueryProfile:
    education_level: str = ""
    role: str = ""
    intent: str = ""
    academic_interest: str = ""
    query: str = ""


class EmbeddingUnavailableError(RuntimeError):
    """Raised when required dense embeddings cannot be produced."""


def build_llm_wiki_index(
    site_root: Path,
    *,
    chunk_chars: int = 1600,
    overlap: int = 200,
    now: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Build a deterministic dual-corpus index for raw sources and wiki pages."""
    started = time.monotonic()
    timestamp = now or utc_now_iso()
    layout = ensure_layout_for_site_root(Path(site_root))
    index_dir = layout.indexes_dir
    docs_path = index_dir / "llm_wiki_documents.jsonl"
    postings_path = index_dir / "llm_wiki_postings.json"
    manifest_path = index_dir / "llm_wiki_manifest.json"

    with site_index_write_lock(layout.site_root):
        return _build_llm_wiki_index_locked(
            layout,
            docs_path=docs_path,
            postings_path=postings_path,
            manifest_path=manifest_path,
            chunk_chars=chunk_chars,
            overlap=overlap,
            timestamp=timestamp,
            started=started,
            progress_callback=progress_callback,
        )


def _build_llm_wiki_index_locked(
    layout: Any,
    *,
    docs_path: Path,
    postings_path: Path,
    manifest_path: Path,
    chunk_chars: int,
    overlap: int,
    timestamp: str,
    started: float,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    previous_docs = _read_documents(docs_path)
    previous_manifest = _read_manifest(manifest_path)
    _reset_embedding_backend_state()
    previous_by_id = {str(row.get("id") or ""): row for row in previous_docs}
    current_docs: list[dict[str, Any]] = []
    invalid_sources: list[dict[str, Any]] = []

    raw_docs, raw_invalid = _raw_documents(layout.site_root, chunk_chars=chunk_chars, overlap=overlap)
    wiki_docs, wiki_invalid = _wiki_documents(layout.site_root, chunk_chars=chunk_chars, overlap=overlap)
    invalid_sources.extend(raw_invalid)
    invalid_sources.extend(wiki_invalid)

    changed_raw = 0
    changed_wiki = 0
    skipped = 0
    ordered_doc_ids: list[str] = []
    reused_rows_by_id: dict[str, dict[str, Any]] = {}
    changed_docs: list[IndexedDocument] = []

    for doc in raw_docs + wiki_docs:
        old = previous_by_id.get(doc.id)
        if old and _document_row_current(old, doc, previous_manifest=previous_manifest):
            reused_rows_by_id[doc.id] = old
            ordered_doc_ids.append(doc.id)
            skipped += 1
            continue
        ordered_doc_ids.append(doc.id)
        changed_docs.append(doc)
        if doc.corpus == "raw":
            changed_raw += 1
        else:
            changed_wiki += 1
    progress_plan = _embedding_progress_plan(
        raw_docs=raw_docs,
        wiki_docs=wiki_docs,
        changed_docs=changed_docs,
        changed_raw=changed_raw,
        changed_wiki=changed_wiki,
        skipped=skipped,
    )
    _emit_progress(progress_callback, {"stage": "embedding_plan", **progress_plan})
    changed_rows = _document_rows(
        changed_docs,
        progress_callback=progress_callback,
        progress_context=progress_plan,
    )
    changed_rows_by_id = {str(row.get("id") or ""): row for row in changed_rows}
    for doc_id in ordered_doc_ids:
        row = reused_rows_by_id.get(doc_id) or changed_rows_by_id.get(doc_id)
        if row is not None:
            current_docs.append(row)

    raw_count = sum(1 for doc in current_docs if doc.get("corpus") == "raw")
    wiki_count = sum(1 for doc in current_docs if doc.get("corpus") == "wiki")
    index_embedding_space = _index_embedding_space(current_docs)
    degraded = _embedding_degraded() or index_embedding_space == EMBEDDING_SPACE_HASH
    postings = _build_postings(current_docs)
    _emit_progress(progress_callback, {"stage": "writing_artifacts", **progress_plan, "document_count": len(current_docs)})
    _write_documents_jsonl_atomic(docs_path, current_docs)
    _write_json_atomic(postings_path, postings)
    _emit_progress(progress_callback, {"stage": "documents_written", **progress_plan, "document_count": len(current_docs)})
    _emit_progress(progress_callback, {"stage": "zvec_building", **progress_plan, "document_count": len(current_docs)})
    zvec_report = _build_zvec_store(layout.site_root, current_docs, degraded=degraded)
    _emit_progress(
        progress_callback,
        {
            "stage": "zvec_ready" if zvec_report.get("ready") else "zvec_unavailable",
            **progress_plan,
            "document_count": len(current_docs),
            "vector_store": zvec_report,
        },
    )
    vector_leg_enabled = bool(current_docs) and bool(zvec_report.get("ready")) and not degraded

    manifest = {
        "version": INDEX_VERSION,
        "status": "ready" if current_docs else "empty",
        "site_root": str(layout.site_root.resolve()),
        "documents_path": str(docs_path),
        "postings_path": str(postings_path),
        "built_at": timestamp,
        "raw_index_count": raw_count,
        "wiki_index_count": wiki_count,
        "raw_documents": raw_count,
        "wiki_documents": wiki_count,
        "raw_count": raw_count,
        "wiki_count": wiki_count,
        "changed_raw_count": changed_raw,
        "changed_wiki_count": changed_wiki,
        "changed_document_count": changed_raw + changed_wiki,
        "skipped_document_count": skipped,
        "term_count": len(postings),
        "reranker_ready": _openrouter_rerank_ready(),
        "index_health": "ready" if current_docs else "empty",
        "embedding_space": index_embedding_space,
        "vector_leg_enabled": vector_leg_enabled,
        "vector_store": {
            "backend": "zvec",
            "ready": bool(zvec_report.get("ready")),
            "path": str(zvec_report.get("path") or ""),
            "collection": str(zvec_report.get("collection") or ""),
            "documents": int(zvec_report.get("documents") or 0),
            "vector_dimensions": int(zvec_report.get("vector_dimensions") or 0),
            "error": str(zvec_report.get("error") or ""),
        },
        "zvec": zvec_report,
        "query_modes_available": _query_modes_available(current_docs, vector_leg_enabled=vector_leg_enabled),
        "embedding": {
            "provider": EMBEDDING_PROVIDER,
            "model": EMBEDDING_MODEL,
            "vector_dimensions": EMBEDDING_DIMENSIONS,
            "degraded": degraded,
            "space": index_embedding_space,
        },
        "embedding_degraded": degraded,
        "estimated_input_tokens": progress_plan.get("estimated_input_tokens"),
        "estimated_embedding_cost_usd": progress_plan.get("estimated_embedding_cost_usd"),
        "embedding_price_per_million_input_tokens": progress_plan.get("embedding_price_per_million_input_tokens"),
        "embedding_price_source": progress_plan.get("embedding_price_source"),
        "reranker": {
            "provider": RERANK_PROVIDER if _openrouter_rerank_ready() else "",
            "model": _openrouter_rerank_model() if _openrouter_rerank_ready() else "",
            "api_url": RERANK_API_URL if _openrouter_rerank_ready() else "",
        },
        "invalid_sources": invalid_sources,
    }
    _write_json_atomic(manifest_path, manifest)
    reports_dir = layout.indexes_dir / "reports"
    report_path = reports_dir / f"embedding-{timestamp_slug(timestamp, fallback_hash=True)}.json"
    report = {**manifest, "report_path": str(report_path), "last_build_time": timestamp}
    _write_json_atomic(report_path, report)
    _write_json_atomic(layout.indexes_dir / "embedding_status.json", {**report, "report_path": str(layout.indexes_dir / "embedding_status.json")})
    _record_embedding_metrics(
        layout.site_root,
        timestamp=timestamp,
        raw_count=raw_count,
        wiki_count=wiki_count,
        changed_count=changed_raw + changed_wiki,
        skipped_count=skipped,
        duration_ms=int((time.monotonic() - started) * 1000),
        progress_plan=progress_plan,
    )
    _emit_progress(
        progress_callback,
        {
            "stage": "complete",
            **progress_plan,
            "document_count": len(current_docs),
            "raw_index_count": raw_count,
            "wiki_index_count": wiki_count,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        },
    )
    return report


def _build_zvec_store(site_root: Path, rows: list[dict[str, Any]], *, degraded: bool) -> dict[str, Any]:
    if degraded:
        return {
            "backend": "zvec",
            "ready": False,
            "path": str(zvec_ready(site_root).get("path") or ""),
            "collection": "",
            "documents": 0,
            "vector_dimensions": EMBEDDING_DIMENSIONS,
            "error": "embedding_degraded",
        }
    try:
        return replace_zvec_documents(site_root, rows, dimensions=EMBEDDING_DIMENSIONS)
    except ZvecStoreUnavailable as exc:
        raise EmbeddingUnavailableError(f"zvec vector store unavailable: {exc}") from exc


def _query_modes_available(rows: list[dict[str, Any]], *, vector_leg_enabled: bool) -> list[str]:
    if not rows:
        return ["page_only"]
    modes = ["lexical", "page_only"]
    if vector_leg_enabled:
        modes.insert(0, "vector")
    return modes


def _record_embedding_metrics(
    site_root: Path,
    *,
    timestamp: str,
    raw_count: int,
    wiki_count: int,
    changed_count: int,
    skipped_count: int,
    duration_ms: int,
    progress_plan: dict[str, Any] | None = None,
) -> None:
    run_id = os.environ.get("WIKI_AGENT_RUN_ID") or os.environ.get("RALPH_AGENT_RUN_ID")
    site_id = os.environ.get("WIKI_AGENT_SITE_ID") or site_root.name
    if not run_id:
        return
    try:
        data_root = Path(site_root).parents[1]
    except IndexError:
        return
    plan = progress_plan if isinstance(progress_plan, dict) else {}
    raw_tokens = plan.get("estimated_input_tokens")
    try:
        input_tokens = int(raw_tokens) if raw_tokens not in (None, "") else None
    except (TypeError, ValueError):
        input_tokens = None
    metric_cost = resolve_embedding_metric_cost(
        input_tokens=input_tokens,
        model=EMBEDDING_MODEL,
        estimated_cost_usd=plan.get("estimated_embedding_cost_usd"),
    )
    try:
        AgentRunMetricsRepository(data_root).append_event(
            build_embedding_metric_event(
                run_id=run_id,
                site_id=site_id,
                timestamp=timestamp,
                stage="embed",
                operation="build_llm_wiki_index",
                provider=EMBEDDING_PROVIDER,
                model=EMBEDDING_MODEL,
                input_tokens=input_tokens,
                document_count=raw_count + wiki_count,
                chunk_count=raw_count + wiki_count,
                vector_count=raw_count + wiki_count,
                reused_vector_count=skipped_count,
                skipped_chunk_count=skipped_count,
                failed_chunk_count=0,
                duration_ms=duration_ms,
                cost_usd=metric_cost.amount_usd,
                cost_source=metric_cost.source,
                raw_provider_usage={
                    "changed_document_count": changed_count,
                    "raw_index_count": raw_count,
                    "wiki_index_count": wiki_count,
                    "vector_dimensions": EMBEDDING_DIMENSIONS,
                    "embedding_price_source": plan.get("embedding_price_source"),
                },
            )
        )
    except (OSError, ValueError, TypeError) as exc:
        _LOGGER.warning("failed to record embedding metrics: %s", exc)
        return


def query_llm_wiki_index(
    site_root: Path,
    query: str,
    *,
    max_evidence: int = 5,
    max_candidates: int = 50,
    profile: QueryProfile | dict[str, Any] | None = None,
    retrieval_strategy: str = "auto",
) -> dict[str, Any]:
    layout = site_layout(Path(site_root))
    docs_path = layout.indexes_dir / "llm_wiki_documents.jsonl"
    postings_path = layout.indexes_dir / "llm_wiki_postings.json"
    manifest_path = layout.indexes_dir / "llm_wiki_manifest.json"
    if not docs_path.exists() or not postings_path.exists() or not manifest_path.exists():
        return {
            "status": "missing_index",
            "query": query,
            "evidence": [],
            "metadata": {"site_root": str(layout.site_root.resolve()), "reason": "index_artifacts_missing"},
        }
    try:
        docs = _read_documents(docs_path)
        postings = json.loads(postings_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "status": "missing_index",
            "query": query,
            "evidence": [],
            "metadata": {"site_root": str(layout.site_root.resolve()), "reason": "index_artifacts_malformed"},
        }
    embedding_error = _embedding_manifest_error(manifest)
    if embedding_error:
        return _embedding_error_response(query, layout.site_root, manifest=manifest, **embedding_error)

    query_plan = prepare_retrieval_query(query)
    retrieval_query = query_plan.effective
    query_profile = infer_query_profile(retrieval_query, profile)
    tokens = _tokenize(retrieval_query)
    if max_evidence <= 0 or not tokens:
        return {
            "status": "ok",
            "query": query,
            "evidence": [],
            "metadata": {"bounded": True, "reason": "empty_query_or_zero_limit"},
        }

    try:
        retrieval = _select_retrieval_candidates(
            docs,
            postings if isinstance(postings, dict) else {},
            retrieval_query,
            tokens,
            max_candidates=max_candidates,
            retrieval_strategy=retrieval_strategy,
            manifest=manifest,
            site_root=layout.site_root,
        )
        candidates = retrieval["candidates"]
        lexical_scores = retrieval["lexical_scores"]
        evidence = _dedupe_evidence_by_path(
            rerank_candidates(retrieval_query, candidates, lexical_scores, profile=query_profile, manifest=manifest)
        )[:max_evidence]
    except EmbeddingUnavailableError as exc:
        return _embedding_error_response(
            query,
            layout.site_root,
            manifest=manifest,
            reason="embedding_query_failed",
            message=str(exc),
        )
    expansion_meta = {
        "original": query_plan.original,
        "effective": query_plan.effective,
        "expansions": list(query_plan.expansions),
        "person_lookup": query_plan.person_lookup,
    }
    _apply_retrieval_annotations(evidence, retrieval)
    next_pages = _next_pages_from_navigation_manifest(layout.site_root, query, evidence)
    if not evidence:
        result = {
            "status": "insufficient_evidence",
            "query": query,
            "evidence": [],
            "metadata": {
                "bounded": True,
                "reason": "no_related_candidates",
                "routing": _profile_metadata(query_profile, candidate_count=len(candidates)),
                "retrieval": _retrieval_metadata(retrieval),
                "site_root": str(layout.site_root.resolve()),
                "next_pages": next_pages,
                "embedding_degraded": bool(manifest.get("embedding_degraded")),
                "vector_leg_enabled": bool(manifest.get("vector_leg_enabled", not manifest.get("embedding_degraded"))),
                "embedding_space": str(manifest.get("embedding_space") or ""),
            },
        }
        result["metadata"]["query_expansion"] = expansion_meta
        result["metadata"]["confidence"] = assess_confidence(result, question=query)
        return result
    result = {
        "status": "ok",
        "query": query,
        "evidence": evidence,
        "metadata": {
            "bounded": True,
            "max_evidence": max_evidence,
            "max_candidates": max_candidates,
            "candidate_count": len(candidates),
            "index_version": manifest.get("version"),
            "site_root": str(layout.site_root.resolve()),
            "routing": _profile_metadata(query_profile, evidence=evidence, candidate_count=len(candidates)),
            "retrieval": _retrieval_metadata(retrieval),
            "next_pages": next_pages,
            "embedding_degraded": bool(manifest.get("embedding_degraded")),
            "vector_leg_enabled": bool(manifest.get("vector_leg_enabled", not manifest.get("embedding_degraded"))),
            "embedding_space": str(manifest.get("embedding_space") or ""),
            "query_expansion": expansion_meta,
        },
    }
    result["metadata"]["confidence"] = assess_confidence(result, question=query)
    return result


def _next_pages_from_navigation_manifest(site_root: Path, query: str, evidence: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, str]]:
    manifest_path = Path(site_root) / "wiki" / "navigation_manifest.json"
    if not manifest_path.exists():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    pages = manifest.get("pages") if isinstance(manifest, dict) else []
    if not isinstance(pages, list):
        return []
    evidence_paths = {str(item.get("path") or "") for item in evidence if isinstance(item, dict)}
    query_tokens = set(_content_tokens(query))
    school_terms = {
        "cox-school-of-business": ("cox", "business", "mba"),
        "lyle-school-of-engineering": ("lyle", "engineering"),
        "meadows-school-of-the-arts": ("meadows", "arts", "music", "theatre", "dance"),
        "simmons-school-of-education": ("simmons", "education"),
        "perkins-school-of-theology": ("perkins", "theology"),
        "dedman-school-of-law": ("law", "dedman law"),
        "dedman-college": ("dedman college", "humanities", "sciences"),
    }
    query_lower = str(query or "").lower()
    wanted_schools = {slug for slug, terms in school_terms.items() if any(term in query_lower for term in terms)}
    scored: list[tuple[float, dict[str, Any]]] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        path = str(page.get("path") or "")
        if path in evidence_paths:
            continue
        haystack = " ".join(
            [
                str(page.get("title") or ""),
                str(page.get("summary") or ""),
                " ".join(str(value) for value in page.get("tags", []) if value),
                " ".join(str(value) for value in page.get("entities", []) if value),
            ]
        ).lower()
        token_hits = sum(1 for token in query_tokens if token in haystack)
        priority = float(page.get("priority") or 0) / 100.0
        page_type = str(page.get("page_type") or "")
        type_bonus = 5.0 if page_type in {"semantic", "navigation", "concept", "entity", "workflow", "process"} else 0.0
        school_bonus = 8.0 if any(slug in str(page.get("path") or "") for slug in wanted_schools) else 0.0
        score = token_hits + priority + type_bonus + school_bonus
        if score <= 0:
            continue
        scored.append((score, page))
    next_pages = []
    for _score, page in sorted(scored, key=lambda item: (-item[0], str(item[1].get("title") or "")))[:limit]:
        next_pages.append(
            {
                "title": str(page.get("title") or ""),
                "path": str(page.get("path") or ""),
                "page_type": str(page.get("page_type") or ""),
                "why": str(page.get("summary") or "Relevant linked/navigation page")[:240],
            }
        )
    return next_pages


def query_mcp_wiki_index(
    site_root: Path,
    query: str,
    *,
    max_evidence: int = 5,
    max_candidates: int = 50,
    profile: QueryProfile | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Query the wiki for MCP with factual BM25-first and reasoning vector routing."""
    return query_llm_wiki_index(
        site_root,
        query,
        max_evidence=max_evidence,
        max_candidates=max_candidates,
        profile=profile,
        retrieval_strategy="mcp_auto",
    )


def _embedding_manifest_error(manifest: dict[str, Any]) -> dict[str, str] | None:
    if _allow_hash_embedding_fallback():
        return None
    version = str(manifest.get("version") or "")
    space = str(manifest.get("embedding_space") or "")
    embedding = manifest.get("embedding") if isinstance(manifest.get("embedding"), dict) else {}
    vector_store = manifest.get("vector_store") if isinstance(manifest.get("vector_store"), dict) else {}
    if version and version != INDEX_VERSION:
        return {
            "reason": "index_version_mismatch",
            "message": f"Index version is {version}; expected {INDEX_VERSION}. Rebuild the index.",
        }
    if bool(manifest.get("embedding_degraded")):
        return {
            "reason": "embedding_degraded",
            "message": "Index was built with degraded embeddings. Rebuild the index after OpenRouter embeddings are available.",
        }
    dimensions = int(embedding.get("vector_dimensions") or 0) if embedding else 0
    if dimensions and dimensions != EMBEDDING_DIMENSIONS:
        return {
            "reason": "embedding_dimension_mismatch",
            "message": f"Index vector dimensions are {dimensions}; expected {EMBEDDING_DIMENSIONS}. Rebuild the index.",
        }
    if space and space != EMBEDDING_SPACE_DENSE:
        return {
            "reason": "embedding_space_mismatch",
            "message": f"Index embedding space is {space}; expected {EMBEDDING_SPACE_DENSE}. Rebuild the index.",
        }
    if not vector_store and str(manifest.get("status") or "") == "ready":
        return {
            "reason": "vector_store_unavailable",
            "message": "Index manifest does not declare a zvec vector store. Rebuild the index.",
        }
    if manifest.get("vector_leg_enabled") is False and str(manifest.get("status") or "") == "ready":
        return {
            "reason": "vector_store_unavailable",
            "message": str(vector_store.get("error") or "Zvec vector store is not ready. Rebuild the index after zvec is available."),
        }
    if vector_store and not bool(vector_store.get("ready")) and str(manifest.get("status") or "") == "ready":
        return {
            "reason": "vector_store_unavailable",
            "message": str(vector_store.get("error") or "Zvec vector store is not ready. Rebuild the index."),
        }
    return None


def _embedding_error_response(
    query: str,
    site_root: Path,
    *,
    manifest: dict[str, Any] | None,
    reason: str,
    message: str,
) -> dict[str, Any]:
    manifest = manifest or {}
    return {
        "status": "embedding_unavailable",
        "query": query,
        "evidence": [],
        "metadata": {
            "bounded": True,
            "reason": reason,
            "message": message,
            "site_root": str(Path(site_root).resolve()),
            "index_version": manifest.get("version"),
            "embedding_degraded": bool(manifest.get("embedding_degraded")),
            "embedding_space": str(manifest.get("embedding_space") or ""),
            "vector_leg_enabled": False,
            "vector_store": manifest.get("vector_store") if isinstance(manifest.get("vector_store"), dict) else {},
        },
    }


def search_source_index(site_root: Path, query: str, *, max_evidence: int = 5, max_candidates: int = 50) -> dict[str, Any]:
    layout = site_layout(Path(site_root))
    docs_path = layout.indexes_dir / "llm_wiki_documents.jsonl"
    postings_path = layout.indexes_dir / "llm_wiki_postings.json"
    manifest_path = layout.indexes_dir / "llm_wiki_manifest.json"
    if not docs_path.exists() or not postings_path.exists() or not manifest_path.exists():
        return {
            "status": "missing_index",
            "query": query,
            "evidence": [],
            "metadata": {"site_root": str(layout.site_root.resolve()), "reason": "index_artifacts_missing", "source_only": True},
        }
    try:
        docs = _read_documents(docs_path)
        postings = json.loads(postings_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "status": "missing_index",
            "query": query,
            "evidence": [],
            "metadata": {"site_root": str(layout.site_root.resolve()), "reason": "index_artifacts_malformed", "source_only": True},
        }
    embedding_error = _embedding_manifest_error(manifest)
    if embedding_error:
        response = _embedding_error_response(query, layout.site_root, manifest=manifest, **embedding_error)
        response["metadata"]["source_only"] = True
        return response
    tokens = _tokenize(query)
    if max_evidence <= 0 or not tokens:
        return {
            "status": "ok",
            "query": query,
            "evidence": [],
            "metadata": {"bounded": True, "reason": "empty_query_or_zero_limit", "source_only": True},
        }
    candidates, lexical_scores = _retrieve_candidates_for_corpus(
        docs,
        postings if isinstance(postings, dict) else {},
        tokens,
        corpus="raw",
        max_candidates=max_candidates,
    )
    try:
        evidence = rerank_candidates(query, candidates, lexical_scores, manifest=manifest)[:max_evidence]
    except EmbeddingUnavailableError as exc:
        response = _embedding_error_response(
            query,
            layout.site_root,
            manifest=manifest,
            reason="embedding_query_failed",
            message=str(exc),
        )
        response["metadata"]["source_only"] = True
        return response
    return {
        "status": "ok",
        "query": query,
        "evidence": evidence,
        "metadata": {
            "bounded": True,
            "max_evidence": max_evidence,
            "max_candidates": max_candidates,
            "candidate_count": len(candidates),
            "index_version": manifest.get("version"),
            "site_root": str(layout.site_root.resolve()),
            "source_only": True,
        },
    }


def _dedupe_evidence_by_path(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in evidence:
        key = str(item.get("path") or item.get("id") or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def rerank_candidates(
    query: str,
    candidates: list[dict[str, Any]],
    lexical_scores: dict[str, float],
    *,
    profile: QueryProfile | None = None,
    manifest: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    tokens = _tokenize(query)
    vector_leg_enabled = _vector_leg_enabled(manifest)
    query_vector, query_space = _embedding_vector_and_space(query, manifest=manifest)
    query_type, _classifier_reason = _classify_query_type(query)
    raw_candidate_ids = {str(row.get("source_id") or "") for row in candidates if row.get("corpus") == "raw"}
    wiki_cited_ids = {
        str(source_id)
        for row in candidates
        if row.get("corpus") == "wiki"
        for source_id in row.get("source_ids", []) or []
    }
    best_wiki_lexical = max(
        [float(lexical_scores.get(str(row.get("id") or ""), 0.0)) for row in candidates if row.get("corpus") == "wiki"] or [0.0]
    )

    scored: list[dict[str, Any]] = []
    for row in candidates:
        doc_id = str(row.get("id") or "")
        lexical = float(lexical_scores.get(doc_id, 0.0))
        doc_space = str(row.get("embedding_space") or "")
        vector = 0.0
        if vector_leg_enabled and _spaces_compatible(query_space, doc_space, manifest):
            vector = _cosine_similarity(query_vector, row.get("embedding_vector"), left_space=query_space, right_space=doc_space)
        keyword = _keyword_score(tokens, str(row.get("title") or ""), str(row.get("text") or ""))
        is_wiki = row.get("corpus") == "wiki"
        source_priority = 1.2 if is_wiki else 0.0
        reasoning_wiki_boost = 0.8 if (is_wiki and query_type == "reasoning") else 0.0
        route_score, route_reasons = _route_score(row, profile)
        freshness = 0.05 if str(row.get("updated_at") or "") else 0.0
        citation = 0.0
        reasons: list[str] = []
        source_ids = [str(value) for value in row.get("source_ids", []) or [] if str(value)]
        source_id = str(row.get("source_id") or "")
        if is_wiki:
            reasons.append("wiki_synthesis_boost")
            if raw_candidate_ids.intersection(source_ids):
                citation = 0.4
                reasons.append("cites_raw_candidate")
        elif source_id in wiki_cited_ids:
            citation = 0.25
            reasons.append("cited_by_wiki_candidate")
        if keyword:
            reasons.append("keyword_match")
        if reasoning_wiki_boost:
            reasons.append("reasoning_wiki_priority")
        if vector > 0:
            reasons.append("vector_match")
        reasons.extend(route_reasons)
        if not is_wiki and best_wiki_lexical < lexical * 0.5:
            reasons.append("raw_source_fallback")
        if not reasons:
            reasons.append("lexical_match")
        leadership_boost = 0.0
        if is_leadership_query(query):
            leadership_boost, leadership_reasons = leadership_text_boost(
                query,
                str(row.get("title") or ""),
                str(row.get("text") or ""),
            )
            reasons.extend(leadership_reasons)
        combined = lexical + (1.5 * vector) + keyword + source_priority + reasoning_wiki_boost + route_score + freshness + citation + leadership_boost
        scored.append(
            {
                "id": doc_id,
                "source_kind": str(row.get("source_kind") or ""),
                "source_id": source_id,
                "source_ids": source_ids,
                "path": str(row.get("path") or ""),
                "title": str(row.get("title") or ""),
                "snippet": _snippet(str(row.get("text") or ""), tokens),
                "scores": {
                    "lexical": round(lexical, 6),
                    "vector": round(vector, 6),
                    "keyword": round(keyword, 6),
                    "source_priority": round(source_priority, 6),
                    "reasoning_wiki_priority": round(reasoning_wiki_boost, 6),
                    "route": round(route_score, 6),
                    "freshness": round(freshness, 6),
                    "citation": round(citation, 6),
                    "model_rerank": 0.0,
                    "combined": round(combined, 6),
                },
                "source_path": str(row.get("path") or ""),
                "checksum": str(row.get("checksum") or ""),
                "parser": str(row.get("parser") or ""),
                "tags": [str(value) for value in row.get("tags", []) or [] if str(value)],
                "ranking_reasons": reasons,
                "metadata": row.get("metadata", {}) if isinstance(row.get("metadata"), dict) else {},
            }
        )
    reranked = _maybe_openrouter_rerank(query, scored)
    if reranked is not None:
        return reranked
    return sorted(
        scored,
        key=lambda item: (
            -float(item["scores"]["combined"]),
            0 if item["source_kind"] == "wiki" else 1,
            str(item["path"]),
            str(item["id"]),
        ),
    )


def _openrouter_rerank_ready() -> bool:
    return bool(os.getenv("OPENROUTER_API_KEY", "").strip())


def _openrouter_rerank_model() -> str:
    return str(os.getenv("OPENROUTER_RERANK_MODEL", RERANK_MODEL) or RERANK_MODEL).strip()


def _rerank_document_text(row: dict[str, Any]) -> str:
    title = str(row.get("title") or "").strip()
    source_kind = str(row.get("source_kind") or "").strip()
    path = str(row.get("path") or "").strip()
    text = str(row.get("snippet") or row.get("text") or "").strip()
    parts = [part for part in [title, f"kind={source_kind}" if source_kind else "", f"path={path}" if path else "", text] if part]
    return "\n".join(parts)


def _maybe_openrouter_rerank(query: str, scored: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if not scored or not _openrouter_rerank_ready():
        return None
    try:
        response = requests.post(
            RERANK_API_URL,
            headers={
                "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY', '').strip()}",
                "Content-Type": "application/json",
            },
            json={
                "model": _openrouter_rerank_model(),
                "query": query,
                "documents": [_rerank_document_text(row) for row in scored],
                "top_n": len(scored),
            },
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results") or []
        if not isinstance(results, list) or not results:
            return None
        reranked: list[dict[str, Any]] = []
        seen: set[str] = set()
        for result in results:
            if not isinstance(result, dict):
                continue
            idx = result.get("index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(scored):
                continue
            item = dict(scored[idx])
            item["scores"] = dict(item.get("scores") or {})
            model_score = float(result.get("relevance_score") or 0.0)
            item["scores"]["model_rerank"] = round(model_score, 6)
            item["scores"]["combined"] = round(
                model_score
                + (0.05 * float(item["scores"].get("citation") or 0.0))
                + (0.02 * float(item["scores"].get("freshness") or 0.0)),
                6,
            )
            reasons = list(item.get("ranking_reasons") or [])
            if "openrouter_rerank" not in reasons:
                reasons.insert(0, "openrouter_rerank")
            item["ranking_reasons"] = reasons
            reranked.append(item)
            seen.add(str(item.get("id") or ""))
        for item in sorted(
            [row for row in scored if str(row.get("id") or "") not in seen],
            key=lambda row: (
                -float(row["scores"]["combined"]),
                0 if row["source_kind"] == "wiki" else 1,
                str(row["path"]),
                str(row["id"]),
            ),
        ):
            reranked.append(item)
        return reranked
    except (requests.RequestException, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        _LOGGER.warning("openrouter rerank failed: %s", exc)
        return None


def index_info(site_root: Path) -> dict[str, Any]:
    layout = site_layout(Path(site_root))
    manifest_path = layout.indexes_dir / "llm_wiki_manifest.json"
    if not manifest_path.exists():
        return {
            "ok": False,
            "ready": False,
            "error": "missing_index",
            "site_root": str(layout.site_root.resolve()),
            "index_path": str(manifest_path),
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "ok": False,
            "ready": False,
            "error": "malformed_index",
            "site_root": str(layout.site_root.resolve()),
            "index_path": str(manifest_path),
        }
    embedding_error = _embedding_manifest_error(manifest)
    ready = str(manifest.get("status") or "") == "ready" and embedding_error is None
    return {
        "ok": ready,
        "ready": ready,
        "error": "" if ready else (embedding_error or {}).get("reason", str(manifest.get("status") or "not_ready")),
        "message": "" if ready else (embedding_error or {}).get("message", ""),
        "site_root": str(layout.site_root.resolve()),
        "index_path": str(manifest_path),
        "raw_index_count": int(manifest.get("raw_index_count") or 0),
        "wiki_index_count": int(manifest.get("wiki_index_count") or 0),
        "last_build_time": str(manifest.get("built_at") or ""),
        "index_health": str(manifest.get("index_health") or manifest.get("status") or "missing"),
        "query_modes_available": [str(value) for value in manifest.get("query_modes_available", []) or [] if str(value)],
        "vector_store": manifest.get("vector_store") if isinstance(manifest.get("vector_store"), dict) else {},
        "manifest": manifest,
        "config_snippet": generate_mcp_config_snippet(layout.site_root),
    }


def site_mcp_query_readiness(site_root: Path) -> dict[str, Any]:
    """Return the same query gate used by MCP index_info/query_wiki for registry readiness."""
    info = index_info(site_root)
    ready = bool(info.get("ready"))
    reason = str(info.get("error") or "")
    message = str(info.get("message") or "")
    if ready:
        return {
            "query_ready": True,
            "mcp_block_reason": "",
            "reason": "",
            "message": "",
            "index_ready": True,
        }
    block = message or reason or "Index is not query-ready."
    return {
        "query_ready": False,
        "mcp_block_reason": block,
        "reason": reason,
        "message": message,
        "index_ready": False,
    }


def generate_mcp_config_snippet(site_root: Path, *, server_name: str | None = None, python_executable: str | None = None) -> dict[str, Any]:
    root = Path(site_root).resolve()
    command = str(Path(python_executable or sys.executable).resolve())
    name = server_name or f"llm-wiki-{root.name}"
    return {
        "mcpServers": {
            name: {
                "command": command,
                "args": ["-m", "mcp_servers.llm_wiki_mcp", "--site-root", str(root)],
            }
        }
    }


def _raw_documents(site_root: Path, *, chunk_chars: int, overlap: int) -> tuple[list[IndexedDocument], list[dict[str, Any]]]:
    docs: list[IndexedDocument] = []
    invalid: list[dict[str, Any]] = []
    for row in read_registry_rows(site_root / "raw_sources" / "registry.jsonl"):
        if str(row.get("status") or "").lower() != "ready":
            continue
        rel_path = str(row.get("markdown_path") or "")
        source_id = str(row.get("source_id") or "")
        path, path_error = _resolve_site_path(site_root, rel_path)
        if path_error:
            invalid.append(
                {"source_id": source_id, "path": rel_path, "field": "markdown_path", "reason": path_error}
            )
            continue
        if path is None or not path.exists():
            invalid.append({"source_id": source_id, "path": rel_path, "reason": "raw_source_missing"})
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            invalid.append({"source_id": source_id, "path": rel_path, "reason": f"raw_source_unreadable:{exc}"})
            continue
        checksum = checksum_text(text)
        registry_checksum = str(row.get("checksum") or "")
        parser_metadata, parser_metadata_checksum, parser_metadata_error = _read_parser_metadata(
            site_root,
            str(row.get("metadata_path") or ""),
        )
        if parser_metadata_error:
            invalid.append(
                {
                    "source_id": source_id,
                    "path": str(row.get("metadata_path") or ""),
                    "field": "metadata_path",
                    "reason": parser_metadata_error,
                }
            )
        metadata = {
            "original_url": str(row.get("original_url") or ""),
            "original_path": str(row.get("original_path") or ""),
            "metadata_path": str(row.get("metadata_path") or ""),
            "parser_metadata": parser_metadata,
            "parser_metadata_checksum": parser_metadata_checksum,
            "registry_checksum": registry_checksum,
            "provenance": row.get("provenance", {}) if isinstance(row.get("provenance"), dict) else {},
            "change_state": str(row.get("change_state") or ""),
            "wiki_page_paths": row.get("wiki_page_paths", []) if isinstance(row.get("wiki_page_paths"), list) else [],
        }
        for idx, chunk in enumerate(_chunk_text(text, chunk_chars=chunk_chars, overlap=overlap), start=1):
            docs.append(
                IndexedDocument(
                    id=f"raw:{source_id}:{idx}",
                    corpus="raw",
                    source_kind=str(row.get("source_kind") or "unknown"),
                    source_id=source_id,
                    source_ids=[source_id],
                    path=rel_path,
                    title=str(row.get("title") or source_id),
                    checksum=checksum,
                    parser=str(row.get("parser") or ""),
                    tags=[],
                    updated_at=str(row.get("last_changed_at") or row.get("last_seen_at") or ""),
                    text=chunk,
                    chunk_index=idx,
                    metadata=metadata,
                )
            )
    return docs, invalid


def _wiki_documents(site_root: Path, *, chunk_chars: int, overlap: int) -> tuple[list[IndexedDocument], list[dict[str, Any]]]:
    docs: list[IndexedDocument] = []
    invalid: list[dict[str, Any]] = []
    pages_dir = site_root / "wiki" / "pages"
    for path in sorted(pages_dir.rglob("*.md")) if pages_dir.exists() else []:
        rel_path = site_relative(path, site_root, resolve=True)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            invalid.append({"path": rel_path, "reason": f"wiki_page_unreadable:{exc}"})
            continue
        metadata = parse_markdown_frontmatter(text)
        title = str(metadata.get("title") or path.stem.replace("-", " ").title())
        source_ids = [str(value) for value in metadata.get("source_ids", []) if str(value)] if isinstance(metadata.get("source_ids"), list) else []
        tags = [str(value) for value in metadata.get("tags", []) if str(value)] if isinstance(metadata.get("tags"), list) else []
        route_metadata = {
            "page_type": str(metadata.get("page_type") or "source"),
            "school": str(metadata.get("school") or ""),
            "schools": _frontmatter_list(metadata, "schools"),
            "departments": _frontmatter_list(metadata, "departments"),
            "offices": _frontmatter_list(metadata, "offices"),
            "programs": _frontmatter_list(metadata, "programs"),
            "degree_levels": _frontmatter_list(metadata, "degree_levels"),
            "topics": _frontmatter_list(metadata, "topics"),
            "related_pages": _frontmatter_list(metadata, "related_pages"),
            "audiences": _frontmatter_list(metadata, "audiences"),
            "roles": _frontmatter_list(metadata, "roles"),
            "intents": _frontmatter_list(metadata, "intents"),
            "academic_interests": _frontmatter_list(metadata, "academic_interests"),
            "canonical_facts": _frontmatter_list(metadata, "canonical_facts"),
            "aliases": _frontmatter_list(metadata, "aliases"),
            "canonical_owner": str(metadata.get("canonical_owner") or rel_path),
            "source_priority": str(metadata.get("source_priority") or "curated-wiki"),
        }
        checksum = checksum_file(path)
        for idx, chunk in enumerate(_chunk_text(strip_markdown_frontmatter(text), chunk_chars=chunk_chars, overlap=overlap), start=1):
            docs.append(
                IndexedDocument(
                    id=f"wiki:{rel_path}:{idx}",
                    corpus="wiki",
                    source_kind="wiki",
                    source_id=rel_path,
                    source_ids=source_ids,
                    path=rel_path,
                    title=title,
                    checksum=checksum,
                    parser="llm-wiki-builder",
                    tags=tags,
                    updated_at=str(metadata.get("updated_at") or ""),
                    text=chunk,
                    chunk_index=idx,
                    metadata={"frontmatter": metadata, "routing": route_metadata},
                )
            )
    return docs, invalid


def _document_row(doc: IndexedDocument) -> dict[str, Any]:
    vector, space = _embedding_vector_and_space(f"{doc.title}\n{doc.text}")
    return _document_row_with_embedding(doc, vector=vector, space=space)


def _document_rows(
    docs: list[IndexedDocument],
    *,
    progress_callback: ProgressCallback | None = None,
    progress_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    batch_size = _embedding_batch_size()
    batch_count = math.ceil(len(docs) / batch_size) if docs else 0
    embedded = 0
    started = time.monotonic()
    for start in range(0, len(docs), batch_size):
        batch = docs[start : start + batch_size]
        batch_index = (start // batch_size) + 1
        vectors, space = _embedding_vectors_and_space([_embedding_text(doc) for doc in batch])
        rows.extend(_document_row_with_embedding(doc, vector=vector, space=space) for doc, vector in zip(batch, vectors))
        embedded += len(batch)
        elapsed = max(0.001, time.monotonic() - started)
        docs_per_second = embedded / elapsed
        remaining = max(0, len(docs) - embedded)
        estimated_seconds_remaining = remaining / docs_per_second if docs_per_second > 0 else None
        _emit_progress(
            progress_callback,
            {
                **(progress_context or {}),
                "stage": "embedding_batch",
                "batch_index": batch_index,
                "batch_count": batch_count,
                "batch_size": batch_size,
                "embedded_document_count": embedded,
                "remaining_document_count": remaining,
                "elapsed_seconds": round(elapsed, 3),
                "documents_per_second": round(docs_per_second, 6),
                "estimated_seconds_remaining": round(estimated_seconds_remaining, 3)
                if estimated_seconds_remaining is not None
                else None,
            },
        )
    return rows


def _embedding_text(doc: IndexedDocument) -> str:
    return f"{doc.title}\n{doc.text}"


def _embedding_progress_plan(
    *,
    raw_docs: list[IndexedDocument],
    wiki_docs: list[IndexedDocument],
    changed_docs: list[IndexedDocument],
    changed_raw: int,
    changed_wiki: int,
    skipped: int,
) -> dict[str, Any]:
    total_changed = len(changed_docs)
    estimated_tokens = _estimate_embedding_tokens_for_docs(changed_docs)
    price = _embedding_price_per_million_input_tokens()
    return {
        "embedding_provider": EMBEDDING_PROVIDER,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimensions": EMBEDDING_DIMENSIONS,
        "embedding_price_per_million_input_tokens": price,
        "embedding_price_source": "openrouter_catalog",
        "estimated_input_tokens": estimated_tokens,
        "estimated_embedding_cost_usd": round((estimated_tokens / 1_000_000) * price, 6),
        "raw_document_count": len(raw_docs),
        "wiki_document_count": len(wiki_docs),
        "total_document_count": len(raw_docs) + len(wiki_docs),
        "changed_raw_count": changed_raw,
        "changed_wiki_count": changed_wiki,
        "changed_document_count": total_changed,
        "total_changed_document_count": total_changed,
        "skipped_document_count": skipped,
        "batch_size": _embedding_batch_size(),
        "batch_count": math.ceil(total_changed / _embedding_batch_size()) if total_changed else 0,
        "embedded_document_count": 0,
        "remaining_document_count": total_changed,
    }


def _estimate_embedding_tokens_for_docs(docs: list[IndexedDocument]) -> int:
    return sum(_estimate_embedding_tokens(_embedding_text(doc)) for doc in docs)


def _estimate_embedding_tokens(text: str) -> int:
    text = str(text or "")[:EMBEDDING_TEXT_CHAR_LIMIT]
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def _embedding_price_per_million_input_tokens(model: str | None = None) -> float:
    return embedding_price_per_million_input_tokens(model or EMBEDDING_MODEL)


def _emit_progress(progress_callback: ProgressCallback | None, event: dict[str, Any]) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(event)
    except Exception as exc:
        _LOGGER.warning("embedding progress callback failed: %s", exc)


def _document_row_with_embedding(doc: IndexedDocument, *, vector: list[float], space: str) -> dict[str, Any]:
    provider = EMBEDDING_PROVIDER if space == EMBEDDING_SPACE_DENSE else FALLBACK_EMBEDDING_PROVIDER
    model = EMBEDDING_MODEL if space == EMBEDDING_SPACE_DENSE else FALLBACK_EMBEDDING_MODEL
    return {
        "id": doc.id,
        "corpus": doc.corpus,
        "source_kind": doc.source_kind,
        "source_id": doc.source_id,
        "source_ids": doc.source_ids,
        "path": doc.path,
        "title": doc.title,
        "checksum": doc.checksum,
        "parser": doc.parser,
        "tags": doc.tags,
        "updated_at": doc.updated_at,
        "text": doc.text,
        "chunk_index": doc.chunk_index,
        "metadata": doc.metadata,
        "tokens": _token_counts(doc.text),
        "embedding_provider": provider,
        "embedding_model": model,
        "embedding_space": space,
        "index_version": INDEX_VERSION,
        "embedding_dimensions": EMBEDDING_DIMENSIONS,
        "embedding_vector": vector,
    }


def _document_row_current(
    row: dict[str, Any],
    doc: IndexedDocument,
    *,
    previous_manifest: dict[str, Any] | None = None,
) -> bool:
    if str(row.get("checksum") or "") != doc.checksum:
        return False
    if str(row.get("index_version") or "") != INDEX_VERSION:
        return False
    row_space = str(row.get("embedding_space") or "")
    if not row_space:
        row_space = EMBEDDING_SPACE_DENSE if str(row.get("embedding_provider") or "") == EMBEDDING_PROVIDER else EMBEDDING_SPACE_HASH
    expected_space = EMBEDDING_SPACE_DENSE
    if row_space != expected_space:
        return False
    vector = row.get("embedding_vector")
    if not isinstance(vector, list) or len(vector) != EMBEDDING_DIMENSIONS:
        return False
    if doc.corpus == "raw" and doc.metadata.get("metadata_path"):
        old_metadata = row.get("metadata", {}) if isinstance(row.get("metadata"), dict) else {}
        if old_metadata.get("parser_metadata_checksum") != doc.metadata.get("parser_metadata_checksum"):
            return False
    return True


def _select_retrieval_candidates(
    docs: list[dict[str, Any]],
    postings: dict[str, Any],
    query: str,
    tokens: list[str],
    *,
    max_candidates: int,
    retrieval_strategy: str,
    manifest: dict[str, Any] | None = None,
    site_root: Path | None = None,
) -> dict[str, Any]:
    requested = _normalize_retrieval_strategy(retrieval_strategy)
    query_type, classifier_reason = _classify_query_type(query)
    if requested in {"auto", "mcp_auto"}:
        bm25 = _wiki_bm25_retrieval(docs, query, tokens, max_candidates=max_candidates)
        vector = _vector_retrieval(docs, query, max_candidates=max_candidates, manifest=manifest, site_root=site_root)
        if query_type == "factual":
            fused = _fuse_retrievals(bm25, vector, leading_strategy="wiki_bm25", max_candidates=max_candidates)
        else:
            fused = _fuse_retrievals(vector, bm25, leading_strategy="vector", max_candidates=max_candidates)
        fused.update(
            {
                "strategy": "hybrid_fused",
                "requested_strategy": requested,
                "query_type": query_type,
                "classifier_reason": classifier_reason,
                "attempted_strategies": ["wiki_bm25", "vector"],
                "bm25_backend": bm25.get("bm25_backend", ""),
            }
        )
        if fused["candidates"]:
            return fused
        hybrid = _hybrid_retrieval(docs, postings, tokens, max_candidates=max_candidates)
        hybrid.update(
            {
                "strategy": "hybrid_fallback",
                "requested_strategy": requested,
                "query_type": query_type,
                "classifier_reason": classifier_reason,
                "attempted_strategies": ["wiki_bm25", "vector", "hybrid"],
                "fallback_reason": "fused_no_hits",
                "bm25_backend": bm25.get("bm25_backend", ""),
            }
        )
        return hybrid
    if requested in {"bm25", "wiki_bm25", "factual"}:
        retrieval = _wiki_bm25_retrieval(docs, query, tokens, max_candidates=max_candidates)
        retrieval.update(
            {
                "requested_strategy": requested,
                "query_type": "factual",
                "classifier_reason": "forced_bm25",
                "attempted_strategies": ["wiki_bm25"],
            }
        )
        return retrieval
    if requested in {"vector", "reasoning"}:
        retrieval = _vector_retrieval(docs, query, max_candidates=max_candidates, manifest=manifest, site_root=site_root)
        retrieval.update(
            {
                "requested_strategy": requested,
                "query_type": "reasoning",
                "classifier_reason": "forced_vector",
                "attempted_strategies": ["vector"],
            }
        )
        return retrieval
    retrieval = _hybrid_retrieval(docs, postings, tokens, max_candidates=max_candidates)
    retrieval.update(
        {
            "requested_strategy": requested,
            "query_type": query_type,
            "classifier_reason": classifier_reason,
            "attempted_strategies": ["hybrid"],
        }
    )
    return retrieval


def _normalize_retrieval_strategy(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "hybrid").lower()).strip("_")
    return normalized or "hybrid"


def _classify_query_type(query: str) -> tuple[str, str]:
    normalized = re.sub(r"\s+", " ", str(query or "").lower()).strip()
    reasoning_patterns = (
        r"\bwhy\b",
        r"\bcompare\b",
        r"\bcontrast\b",
        r"\bdifferences?\b",
        r"\brecommend\b",
        r"\bshould\b",
        r"\bbest\b",
        r"\bpros?\b",
        r"\bcons?\b",
        r"\btrade\s*-?\s*offs?\b",
        r"\bexplain\b",
        r"\banaly[sz]e\b",
        r"\bevaluate\b",
        r"\bhelp me choose\b",
    )
    factual_patterns = (
        r"\bwho\b",
        r"\bwhat\b",
        r"\bwhen\b",
        r"\bwhere\b",
        r"\bhow many\b",
        r"\bhow much\b",
        r"\bdeadline\b",
        r"\bdate\b",
        r"\btuition\b",
        r"\bfee\b",
        r"\bcost\b",
        r"\brequirements?\b",
        r"\bemail\b",
        r"\bphone\b",
        r"\bcontact\b",
        r"\baddress\b",
        r"\bhours?\b",
    )
    school_or_program_terms = (
        "cox", "business", "mba", "lyle", "engineering", "meadows", "arts", "simmons", "education",
        "perkins", "theology", "law", "dedman", "graduate", "student",
    )
    multi_aspect_student_fact = (
        any(token in normalized for token in school_or_program_terms)
        and any(token in normalized for token in ("course", "curriculum", "class"))
        and any(token in normalized for token in ("fee", "tuition", "cost", "aid"))
        and any(token in normalized for token in ("admission", "apply", "application", "process"))
    )
    if multi_aspect_student_fact:
        return "factual", "student_multi_aspect_fact"
    if any(re.search(pattern, normalized) for pattern in reasoning_patterns):
        return "reasoning", "reasoning_marker"
    if any(re.search(pattern, normalized) for pattern in factual_patterns):
        return "factual", "factual_marker"
    if len(_content_tokens(normalized)) <= 6:
        return "factual", "short_fact_like_query"
    return "reasoning", "default_reasoning"


def _hybrid_retrieval(
    docs: list[dict[str, Any]],
    postings: dict[str, Any],
    tokens: list[str],
    *,
    max_candidates: int,
) -> dict[str, Any]:
    candidates, lexical_scores = _retrieve_candidates_by_corpus(docs, postings, tokens, max_candidates=max_candidates)
    return {
        "strategy": "hybrid",
        "candidates": candidates,
        "lexical_scores": lexical_scores,
        "reasons_by_id": {},
        "scores_by_id": {},
    }


def _fuse_retrievals(
    primary: dict[str, Any],
    secondary: dict[str, Any],
    *,
    leading_strategy: str,
    max_candidates: int,
) -> dict[str, Any]:
    candidates = _dedupe_candidates(list(primary.get("candidates") or []) + list(secondary.get("candidates") or []))[:max_candidates]
    lexical_scores = {
        **(secondary.get("lexical_scores") if isinstance(secondary.get("lexical_scores"), dict) else {}),
        **(primary.get("lexical_scores") if isinstance(primary.get("lexical_scores"), dict) else {}),
    }
    reasons_by_id: dict[str, str] = {}
    for source in (primary, secondary):
        values = source.get("reasons_by_id") if isinstance(source.get("reasons_by_id"), dict) else {}
        for key, value in values.items():
            reasons_by_id.setdefault(str(key), str(value))
    scores_by_id: dict[str, dict[str, float]] = {}
    for source in (secondary, primary):
        values = source.get("scores_by_id") if isinstance(source.get("scores_by_id"), dict) else {}
        for key, score_map in values.items():
            if not isinstance(score_map, dict):
                continue
            target = scores_by_id.setdefault(str(key), {})
            for score_key, score in score_map.items():
                try:
                    target[str(score_key)] = float(score)
                except (TypeError, ValueError):
                    continue
    vector_backend = str(primary.get("vector_backend") or secondary.get("vector_backend") or "")
    vector_store_path = str(primary.get("vector_store_path") or secondary.get("vector_store_path") or "")
    return {
        "strategy": "hybrid_fused",
        "leading_strategy": leading_strategy,
        "vector_backend": vector_backend,
        "vector_store_path": vector_store_path,
        "candidates": candidates,
        "lexical_scores": lexical_scores,
        "reasons_by_id": reasons_by_id,
        "scores_by_id": scores_by_id,
    }


def _wiki_bm25_retrieval(
    docs: list[dict[str, Any]],
    query: str,
    tokens: list[str],
    *,
    max_candidates: int,
) -> dict[str, Any]:
    wiki_docs = [row for row in docs if row.get("corpus") == "wiki"]
    query_tokens = _content_tokens(query) or [token for token in tokens if token]
    bm25_scores, backend = _bm25_wiki_scores(query_tokens, wiki_docs, query=query, max_candidates=max_candidates)
    doc_map = {str(row.get("id") or ""): row for row in wiki_docs}
    _boost_semantic_wiki_scores(bm25_scores, doc_map, query)
    ranked_wiki = sorted(bm25_scores.items(), key=lambda item: (-item[1], item[0]))[:max_candidates]
    wiki_candidates = [doc_map[doc_id] for doc_id, _score in ranked_wiki if doc_id in doc_map]
    support_candidates, support_scores = _supporting_raw_candidates_for_wiki_hits(
        docs,
        wiki_candidates,
        query_tokens,
        max_candidates=max_candidates,
    )
    candidates = _dedupe_candidates(wiki_candidates + support_candidates)
    lexical_scores = {**support_scores, **{doc_id: score for doc_id, score in ranked_wiki}}
    reasons_by_id = {str(row.get("id") or ""): "bm25_wiki_match" for row in wiki_candidates}
    reasons_by_id.update({str(row.get("id") or ""): "bm25_cited_raw_support" for row in support_candidates})
    scores_by_id = {doc_id: {"bm25": score} for doc_id, score in ranked_wiki}
    for doc_id, score in support_scores.items():
        scores_by_id.setdefault(doc_id, {})["bm25"] = score
    return {
        "strategy": "wiki_bm25",
        "candidates": candidates,
        "lexical_scores": lexical_scores,
        "reasons_by_id": reasons_by_id,
        "scores_by_id": scores_by_id,
        "bm25_backend": backend,
    }


def _boost_semantic_wiki_scores(bm25_scores: dict[str, float], doc_map: dict[str, dict[str, Any]], query: str) -> None:
    query_lower = str(query or "").lower()
    school_terms = {
        "cox-school-of-business": ("cox", "business", "mba"),
        "lyle-school-of-engineering": ("lyle", "engineering"),
        "meadows-school-of-the-arts": ("meadows", "arts", "music", "theatre", "dance"),
        "simmons-school-of-education": ("simmons", "education"),
        "perkins-school-of-theology": ("perkins", "theology"),
        "dedman-school-of-law": ("law", "dedman law"),
        "dedman-college": ("dedman college", "humanities", "sciences"),
    }
    wanted_schools = {slug for slug, terms in school_terms.items() if any(term in query_lower for term in terms)}
    wants_grad = any(token in query_lower for token in ("grad", "graduate", "master", "mba"))
    wants_multi_aspect = sum(
        1
        for group in (
            ("course", "curriculum", "class"),
            ("fee", "tuition", "cost", "aid"),
            ("admission", "apply", "application", "deadline"),
        )
        if any(token in query_lower for token in group)
    ) >= 2
    for doc_id, row in doc_map.items():
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        frontmatter = metadata.get("frontmatter") if isinstance(metadata.get("frontmatter"), dict) else {}
        routing = metadata.get("routing") if isinstance(metadata.get("routing"), dict) else {}
        page_type = str(frontmatter.get("page_type") or routing.get("page_type") or "")
        source_priority = str(routing.get("source_priority") or frontmatter.get("source_priority") or "")
        path = str(row.get("path") or "")
        if page_type == "semantic" or source_priority == "semantic-wiki":
            bm25_scores[doc_id] = bm25_scores.get(doc_id, 0.0) * 4.0 + 25.0
            if any(f"wiki/pages/schools/{slug}" in path for slug in wanted_schools):
                bm25_scores[doc_id] += 60.0
            if wants_grad and path.endswith("/graduate.md"):
                bm25_scores[doc_id] += 20.0
            if wants_multi_aspect and any(f"wiki/pages/schools/{slug}" in path for slug in wanted_schools):
                bm25_scores[doc_id] += 30.0
        elif page_type == "source" and doc_id in bm25_scores:
            bm25_scores[doc_id] = bm25_scores.get(doc_id, 0.0) * 0.85


def _vector_retrieval(
    docs: list[dict[str, Any]],
    query: str,
    *,
    max_candidates: int,
    manifest: dict[str, Any] | None = None,
    site_root: Path | None = None,
) -> dict[str, Any]:
    vector_store = manifest.get("vector_store") if isinstance(manifest, dict) and isinstance(manifest.get("vector_store"), dict) else {}
    if not _vector_leg_enabled(manifest):
        return {
            "strategy": "vector",
            "candidates": [],
            "lexical_scores": {},
            "reasons_by_id": {},
            "scores_by_id": {},
            "vector_leg_skipped": True,
        }
    candidates, vector_scores = _retrieve_vector_candidates_by_corpus(
        docs,
        query,
        max_candidates=max_candidates,
        manifest=manifest,
        site_root=site_root,
    )
    return {
        "strategy": "vector",
        "vector_backend": "zvec",
        "vector_store_path": str(vector_store.get("path") or ""),
        "candidates": candidates,
        "lexical_scores": {},
        "reasons_by_id": {str(row.get("id") or ""): "vector_candidate" for row in candidates},
        "scores_by_id": {doc_id: {"retrieval_vector": score} for doc_id, score in vector_scores.items()},
    }


def _retrieval_metadata(retrieval: dict[str, Any]) -> dict[str, Any]:
    return {
        "requested_strategy": str(retrieval.get("requested_strategy") or retrieval.get("strategy") or ""),
        "selected_strategy": str(retrieval.get("strategy") or ""),
        "query_type": str(retrieval.get("query_type") or ""),
        "classifier_reason": str(retrieval.get("classifier_reason") or ""),
        "attempted_strategies": [str(value) for value in retrieval.get("attempted_strategies", []) or [] if str(value)],
        "fallback_reason": str(retrieval.get("fallback_reason") or ""),
        "bm25_backend": str(retrieval.get("bm25_backend") or ""),
        "vector_backend": str(retrieval.get("vector_backend") or ""),
        "vector_store_path": str(retrieval.get("vector_store_path") or ""),
    }


def _apply_retrieval_annotations(evidence: list[dict[str, Any]], retrieval: dict[str, Any]) -> None:
    reasons_by_id = retrieval.get("reasons_by_id") if isinstance(retrieval.get("reasons_by_id"), dict) else {}
    scores_by_id = retrieval.get("scores_by_id") if isinstance(retrieval.get("scores_by_id"), dict) else {}
    for item in evidence:
        doc_id = str(item.get("id") or "")
        reason = str(reasons_by_id.get(doc_id) or "")
        if reason:
            reasons = list(item.get("ranking_reasons") or [])
            if reason not in reasons:
                reasons.insert(0, reason)
            item["ranking_reasons"] = reasons
        score_updates = scores_by_id.get(doc_id)
        if isinstance(score_updates, dict):
            scores = dict(item.get("scores") or {})
            for key, value in score_updates.items():
                try:
                    scores[str(key)] = round(float(value), 6)
                except (TypeError, ValueError):
                    continue
            item["scores"] = scores


def _retrieve_candidates_by_corpus(
    docs: list[dict[str, Any]],
    postings: dict[str, Any],
    tokens: list[str],
    *,
    max_candidates: int,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    raw_candidates, raw_scores = _retrieve_candidates_for_corpus(docs, postings, tokens, corpus="raw", max_candidates=max_candidates)
    wiki_candidates, wiki_scores = _retrieve_candidates_for_corpus(docs, postings, tokens, corpus="wiki", max_candidates=max_candidates)
    scores = {**raw_scores, **wiki_scores}
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for row in raw_candidates + wiki_candidates:
        doc_id = str(row.get("id") or "")
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            candidates.append(row)
    return candidates, scores


def _retrieve_candidates_for_corpus(
    docs: list[dict[str, Any]],
    postings: dict[str, Any],
    tokens: list[str],
    *,
    corpus: str,
    max_candidates: int,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    doc_map = {str(row.get("id") or ""): row for row in docs if row.get("corpus") == corpus}
    scores: dict[str, float] = {}
    for token in tokens:
        hits = postings.get(token)
        if not isinstance(hits, dict):
            continue
        matching_hits = {str(doc_id): tf for doc_id, tf in hits.items() if str(doc_id) in doc_map}
        idf = math.log((len(doc_map) + 1) / (len(matching_hits) + 1)) + 1.0
        for doc_id, tf in matching_hits.items():
            try:
                scores[doc_id] = scores.get(doc_id, 0.0) + float(tf) * idf
            except (TypeError, ValueError):
                continue
    sorted_candidates = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:max_candidates]
    return [doc_map[doc_id] for doc_id, _score in sorted_candidates if doc_id in doc_map], scores


def _retrieve_vector_candidates_by_corpus(
    docs: list[dict[str, Any]],
    query: str,
    *,
    max_candidates: int,
    manifest: dict[str, Any] | None = None,
    site_root: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    if not _vector_leg_enabled(manifest):
        return [], {}
    if site_root is None:
        raise EmbeddingUnavailableError("Zvec vector retrieval requires a site root.")
    query_text = " ".join(_content_tokens(query)) or query
    query_vector, query_space = _embedding_vector_and_space(query_text, manifest=manifest)
    if not _spaces_compatible(query_space, str(manifest.get("embedding_space") or query_space) if manifest else query_space, manifest):
        return [], {}
    doc_map = {str(row.get("id") or ""): row for row in docs if row.get("id")}
    try:
        hits = query_zvec_documents(site_root, query_vector, top_k=max(max_candidates * 2, max_candidates))
    except ZvecStoreUnavailable as exc:
        raise EmbeddingUnavailableError(f"zvec vector store unavailable: {exc}") from exc
    candidates: list[dict[str, Any]] = []
    scores: dict[str, float] = {}
    for hit in hits:
        doc_id = str(hit.get("id") or "")
        if not doc_id:
            continue
        score = _zvec_score(hit.get("score"))
        if score < 0.05:
            continue
        row = doc_map.get(doc_id)
        if row is None:
            row = {
                "id": doc_id,
                "corpus": str(hit.get("corpus") or ""),
                "source_kind": str(hit.get("source_kind") or ""),
                "source_id": str(hit.get("source_id") or ""),
                "source_ids": [str(value) for value in hit.get("source_ids", []) or [] if str(value)],
                "path": str(hit.get("path") or ""),
                "title": str(hit.get("title") or ""),
                "checksum": str(hit.get("checksum") or ""),
                "text": str(hit.get("text") or ""),
                "embedding_space": EMBEDDING_SPACE_DENSE,
                "embedding_vector": [],
                "metadata": {},
            }
        candidates.append(row)
        scores[doc_id] = score
        if len(candidates) >= max_candidates:
            break
    return _dedupe_candidates(candidates), scores


def _zvec_score(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _retrieve_vector_candidates_for_corpus(
    docs: list[dict[str, Any]],
    query_vector: list[float],
    *,
    corpus: str,
    max_candidates: int,
    min_score: float = 0.05,
    query_space: str = "",
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    scored: list[tuple[str, float]] = []
    doc_map: dict[str, dict[str, Any]] = {}
    for row in docs:
        if row.get("corpus") != corpus:
            continue
        doc_id = str(row.get("id") or "")
        if not doc_id:
            continue
        doc_space = str(row.get("embedding_space") or "")
        score = _cosine_similarity(
            query_vector,
            row.get("embedding_vector"),
            left_space=query_space,
            right_space=doc_space,
        )
        if score < min_score:
            continue
        doc_map[doc_id] = row
        scored.append((doc_id, score))
    ranked = sorted(scored, key=lambda item: (-item[1], item[0]))[:max_candidates]
    return [doc_map[doc_id] for doc_id, _score in ranked if doc_id in doc_map], {doc_id: score for doc_id, score in ranked}


def _bm25_wiki_scores(
    query_tokens: list[str],
    wiki_docs: list[dict[str, Any]],
    *,
    query: str,
    max_candidates: int,
) -> tuple[dict[str, float], str]:
    if not query_tokens or not wiki_docs or max_candidates <= 0:
        return {}, ""
    bm25s_scores = _bm25s_wiki_scores(query_tokens, wiki_docs, max_candidates=max_candidates)
    if bm25s_scores is not None:
        return bm25s_scores, "bm25s"
    return _python_bm25_wiki_scores(query_tokens, wiki_docs), "python-bm25"


def _bm25s_wiki_scores(
    query_tokens: list[str], wiki_docs: list[dict[str, Any]], *, max_candidates: int
) -> dict[str, float] | None:
    if _BM25S_MODULE is None:
        return None
    try:
        corpus = [_bm25_document_text(row) for row in wiki_docs]
        if not corpus:
            return {}
        tokenized_corpus = _bm25s_tokenize(_BM25S_MODULE, corpus)
        retriever = _BM25S_MODULE.BM25()
        try:
            retriever.index(tokenized_corpus, show_progress=False)
        except TypeError:
            retriever.index(tokenized_corpus)
        tokenized_query = _bm25s_tokenize(_BM25S_MODULE, [" ".join(query_tokens)])
        k = min(max_candidates, len(wiki_docs))
        try:
            retrieve_result = retriever.retrieve(tokenized_query, k=k, show_progress=False)
        except TypeError:
            retrieve_result = retriever.retrieve(tokenized_query, k=k)
        results, score_rows = retrieve_result
        result_values = _first_bm25s_row(results)
        score_values = _first_bm25s_row(score_rows)
        scores: dict[str, float] = {}
        for result, score in zip(result_values, score_values):
            index = _bm25s_result_index(result, wiki_docs)
            if index is None:
                continue
            try:
                numeric_score = float(score)
            except (TypeError, ValueError):
                continue
            if numeric_score <= 0:
                continue
            doc_id = str(wiki_docs[index].get("id") or "")
            if doc_id:
                scores[doc_id] = numeric_score
        return scores
    except (TypeError, ValueError, AttributeError, IndexError) as exc:
        _LOGGER.warning("bm25s wiki scoring failed: %s", exc)
        return None


def _bm25s_tokenize(bm25s_module: Any, texts: list[str]) -> Any:
    try:
        return bm25s_module.tokenize(texts, stopwords="en", show_progress=False)
    except TypeError:
        try:
            return bm25s_module.tokenize(texts, show_progress=False)
        except TypeError:
            return bm25s_module.tokenize(texts)


def _first_bm25s_row(value: Any) -> list[Any]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list):
        return []
    if len(value) == 1:
        first = value[0]
        if hasattr(first, "tolist"):
            first = first.tolist()
        if isinstance(first, tuple):
            first = list(first)
        if isinstance(first, list):
            return first
    return value


def _bm25s_result_index(value: Any, wiki_docs: list[dict[str, Any]]) -> int | None:
    try:
        index = int(value)
    except (TypeError, ValueError):
        if isinstance(value, dict):
            doc_id = str(value.get("id") or "")
            for idx, row in enumerate(wiki_docs):
                if str(row.get("id") or "") == doc_id:
                    return idx
        return None
    if 0 <= index < len(wiki_docs):
        return index
    return None


def _python_bm25_wiki_scores(query_tokens: list[str], wiki_docs: list[dict[str, Any]]) -> dict[str, float]:
    token_set = [token for token in dict.fromkeys(query_tokens) if token]
    if not token_set:
        return {}
    document_counts: list[tuple[str, dict[str, int], int]] = []
    document_frequency: dict[str, int] = {}
    for row in wiki_docs:
        counts = _content_token_counts(_bm25_document_text(row))
        doc_length = sum(counts.values())
        if doc_length <= 0:
            continue
        doc_id = str(row.get("id") or "")
        document_counts.append((doc_id, counts, doc_length))
        for token in set(counts):
            document_frequency[token] = document_frequency.get(token, 0) + 1
    if not document_counts:
        return {}
    avg_doc_length = sum(length for _doc_id, _counts, length in document_counts) / len(document_counts)
    k1 = 1.5
    b = 0.75
    scores: dict[str, float] = {}
    document_count = len(document_counts)
    for doc_id, counts, doc_length in document_counts:
        score = 0.0
        for token in token_set:
            tf = counts.get(token, 0)
            if tf <= 0:
                continue
            df = document_frequency.get(token, 0)
            if df <= 0:
                continue
            idf = math.log(1.0 + (document_count - df + 0.5) / (df + 0.5))
            denominator = tf + k1 * (1.0 - b + b * (doc_length / avg_doc_length))
            score += idf * ((tf * (k1 + 1.0)) / denominator)
        if score > 0.0 and doc_id:
            scores[doc_id] = score
    return scores


def _supporting_raw_candidates_for_wiki_hits(
    docs: list[dict[str, Any]],
    wiki_candidates: list[dict[str, Any]],
    query_tokens: list[str],
    *,
    max_candidates: int,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    source_ids = {
        str(source_id)
        for row in wiki_candidates
        for source_id in row.get("source_ids", []) or []
        if str(source_id)
    }
    if not source_ids:
        return [], {}
    raw_rows = [row for row in docs if row.get("corpus") == "raw" and str(row.get("source_id") or "") in source_ids]
    scores: dict[str, float] = {}
    for row in raw_rows:
        doc_id = str(row.get("id") or "")
        if not doc_id:
            continue
        counts = _content_token_counts(_bm25_document_text(row))
        score = float(sum(counts.get(token, 0) for token in set(query_tokens)))
        if score <= 0:
            score = 0.01
        scores[doc_id] = min(score * RAW_SUPPORT_SCORE_FACTOR, RAW_SUPPORT_SCORE_CAP)
    ranked = sorted(raw_rows, key=lambda row: (-scores.get(str(row.get("id") or ""), 0.0), str(row.get("id") or "")))[
        :max_candidates
    ]
    return ranked, {str(row.get("id") or ""): scores[str(row.get("id") or "")] for row in ranked if str(row.get("id") or "")}


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in candidates:
        doc_id = str(row.get("id") or "")
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        deduped.append(row)
    return deduped


def _content_tokens(text: str) -> list[str]:
    return [token for token in _tokenize(text) if token not in BM25_STOPWORDS]


def _content_token_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in _content_tokens(text):
        counts[token] = counts.get(token, 0) + 1
    return counts


def _bm25_document_text(row: dict[str, Any]) -> str:
    return f"{row.get('title') or ''}\n{row.get('text') or ''}"


def infer_query_profile(query: str, profile: QueryProfile | dict[str, Any] | None = None) -> QueryProfile:
    if isinstance(profile, QueryProfile):
        base = profile
    elif isinstance(profile, dict):
        base = QueryProfile(
            education_level=str(profile.get("education_level") or ""),
            role=str(profile.get("role") or ""),
            intent=str(profile.get("intent") or ""),
            academic_interest=str(profile.get("academic_interest") or profile.get("academic_interest_area") or ""),
            query=str(profile.get("query") or query or ""),
        )
    else:
        base = QueryProfile(query=query)
    haystack = f"{base.query or query} {base.education_level} {base.role} {base.intent} {base.academic_interest}".lower()
    education_level = base.education_level or _first_match(
        haystack,
        {
            "early learner": ("middle school", "young", "kid", "early learner"),
            "secondary student": ("high school", "secondary"),
            "undergraduate": ("undergraduate", "freshman", "bachelor", "major"),
            "graduate": ("graduate", "master", "phd", "doctoral"),
            "professional": ("professional", "certificate", "executive"),
        },
    )
    role = base.role or _first_match(
        haystack,
        {
            "applicant": ("apply", "admission", "application", "applicant"),
            "current student": ("current student", "registrar", "transcript"),
            "parent": ("parent", "family"),
            "researcher": ("research", "lab"),
            "visitor": ("visit", "tour"),
        },
    )
    intent = base.intent or _first_match(
        haystack,
        {
            "apply": ("apply", "admission", "application", "deadline", "requirement"),
            "pay": ("tuition", "fee", "cost", "financial aid", "scholarship"),
            "study": ("program", "degree", "major", "course", "catalog"),
            "contact": ("contact", "email", "phone", "office"),
            "research": ("research", "lab", "faculty"),
            "visit": ("visit", "tour"),
            "enroll": ("registrar", "enroll", "transcript"),
        },
    )
    academic_interest = base.academic_interest or _first_match(
        haystack,
        {
            "business": ("business", "mba"),
            "computer": ("computer", "cs", "software"),
            "engineering": ("engineering", "network engineering", "ece", "eets", "lyle"),
            "science": ("science",),
            "arts": ("arts", "music", "theatre"),
            "law": ("law",),
        },
    )
    if not academic_interest and re.search(r"\bnetwork\s+engineering\b", haystack):
        academic_interest = "engineering"
    return QueryProfile(
        education_level=education_level,
        role=role,
        intent=intent,
        academic_interest=academic_interest,
        query=base.query or query,
    )


def _first_match(haystack: str, patterns: dict[str, tuple[str, ...]]) -> str:
    for label, needles in patterns.items():
        if any(needle in haystack for needle in needles):
            return label
    return ""


def _route_score(row: dict[str, Any], profile: QueryProfile | None) -> tuple[float, list[str]]:
    if profile is None:
        return 0.0, []
    routing = _row_routing(row)
    score = 0.0
    reasons: list[str] = []
    if row.get("corpus") == "wiki":
        score += 0.15
        reasons.append("routed_wiki_candidate")
    if profile.intent and _route_value_matches(profile.intent, routing.get("intents", [])):
        score += 0.9
        reasons.append("intent_route_match")
    if profile.role and _route_value_matches(profile.role, routing.get("roles", []) + routing.get("audiences", [])):
        score += 0.6
        reasons.append("profile_role_match")
    if profile.education_level and _route_value_matches(profile.education_level, routing.get("audiences", [])):
        score += 0.5
        reasons.append("education_level_match")
    if profile.academic_interest and _route_value_matches(profile.academic_interest, routing.get("academic_interests", []) + routing.get("tags", [])):
        score += 0.5
        reasons.append("academic_interest_match")
    if _profile_out_of_scope(profile, routing):
        score -= 1.4
        reasons.append("profile_scope_penalty")
    return score, reasons


def _profile_out_of_scope(profile: QueryProfile, routing: dict[str, list[str]]) -> bool:
    audiences = set(routing.get("audiences", []))
    intents = set(routing.get("intents", []))
    if profile.education_level in {"early learner", "secondary student"} and {"graduate", "researcher"}.intersection(audiences):
        return True
    if profile.intent and intents and not _route_value_matches(profile.intent, list(intents)) and "explore" not in intents:
        return True
    return False


def _route_value_matches(value: str, candidates: list[str]) -> bool:
    normalized = _route_token(value)
    candidate_tokens = {_route_token(candidate) for candidate in candidates}
    if normalized in candidate_tokens:
        return True
    if normalized == "current-student" and "current-student" in candidate_tokens:
        return True
    if normalized == "graduate" and "graduate" in candidate_tokens:
        return True
    return False


def _route_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def _row_routing(row: dict[str, Any]) -> dict[str, list[str]]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    routing = metadata.get("routing") if isinstance(metadata.get("routing"), dict) else {}
    frontmatter = metadata.get("frontmatter") if isinstance(metadata.get("frontmatter"), dict) else {}
    return {
        "audiences": _metadata_list(routing, "audiences") or _metadata_list(frontmatter, "audiences"),
        "roles": _metadata_list(routing, "roles") or _metadata_list(frontmatter, "roles"),
        "intents": _metadata_list(routing, "intents") or _metadata_list(frontmatter, "intents"),
        "academic_interests": _metadata_list(routing, "academic_interests") or _metadata_list(frontmatter, "academic_interests"),
        "tags": [str(value) for value in row.get("tags", []) or [] if str(value)],
    }


def _metadata_list(metadata: dict[str, Any], key: str) -> list[str]:
    value = metadata.get(key)
    if isinstance(value, list):
        return [_route_token(str(item)) for item in value if str(item)]
    if isinstance(value, str) and value.strip():
        return [_route_token(value)]
    return []


def _frontmatter_list(metadata: dict[str, Any], key: str) -> list[str]:
    value = metadata.get(key)
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _profile_metadata(
    profile: QueryProfile,
    *,
    evidence: list[dict[str, Any]] | None = None,
    candidate_count: int,
) -> dict[str, Any]:
    evidence = evidence or []
    return {
        "profile": {
            "education_level": profile.education_level,
            "role": profile.role,
            "intent": profile.intent,
            "academic_interest": profile.academic_interest,
        },
        "candidate_count": candidate_count,
        "candidate_pages": [str(row.get("path") or "") for row in evidence if row.get("source_kind") == "wiki"],
        "raw_fallback_used": any("raw_source_fallback" in (row.get("ranking_reasons") or []) for row in evidence),
    }


def _build_postings(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    postings: dict[str, dict[str, int]] = {}
    for row in rows:
        doc_id = str(row.get("id") or "")
        token_counts = row.get("tokens")
        if not isinstance(token_counts, dict):
            token_counts = _token_counts(str(row.get("text") or ""))
            row["tokens"] = token_counts
        for token, count in token_counts.items():
            postings.setdefault(str(token), {})[doc_id] = int(count)
    return postings


def _write_documents_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    ordered = sorted(rows, key=lambda item: str(item.get("id") or ""))
    payload = "\n".join(json.dumps(row, ensure_ascii=True) for row in ordered)
    if payload:
        payload += "\n"
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, path)


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _index_embedding_space(rows: list[dict[str, Any]]) -> str:
    spaces = {str(row.get("embedding_space") or "") for row in rows if row.get("embedding_space")}
    if EMBEDDING_SPACE_HASH in spaces:
        return EMBEDDING_SPACE_HASH
    if spaces:
        return next(iter(spaces))
    return EMBEDDING_SPACE_DENSE


def _vector_leg_enabled(manifest: dict[str, Any] | None) -> bool:
    if not manifest:
        return True
    if manifest.get("vector_leg_enabled") is False:
        return False
    if bool(manifest.get("embedding_degraded")):
        return False
    if str(manifest.get("embedding_space") or "") not in {"", EMBEDDING_SPACE_DENSE}:
        return False
    return True


def _spaces_compatible(left_space: str, right_space: str, manifest: dict[str, Any] | None) -> bool:
    if not left_space or not right_space:
        return True
    if left_space != right_space:
        return False
    if manifest and str(manifest.get("embedding_space") or "") not in {"", left_space}:
        return False
    return True


def _read_documents(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("id"):
            rows.append(row)
    return rows


def _chunk_text(text: str, *, chunk_chars: int, overlap: int) -> list[str]:
    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_chars)
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def _token_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in _tokenize(text):
        counts[token] = counts.get(token, 0) + 1
    return counts


def _embedding_vector_and_space(
    text: str,
    *,
    dimensions: int = EMBEDDING_DIMENSIONS,
    manifest: dict[str, Any] | None = None,
) -> tuple[list[float], str]:
    global _DENSE_EMBEDDING_UNAVAILABLE, _EMBEDDING_DEGRADED
    manifest_space = str(manifest.get("embedding_space") or "") if manifest else ""
    if manifest and manifest_space and manifest_space != EMBEDDING_SPACE_DENSE:
        if _allow_hash_embedding_fallback() and manifest_space == EMBEDDING_SPACE_HASH:
            return _hash_embedding_vector(text, dimensions=dimensions), EMBEDDING_SPACE_HASH
        _EMBEDDING_DEGRADED = True
        raise EmbeddingUnavailableError(
            f"Index embedding space is {manifest_space}; expected {EMBEDDING_SPACE_DENSE}. Rebuild the index."
        )
    if _dense_embeddings_disabled():
        _DENSE_EMBEDDING_UNAVAILABLE = True
        _EMBEDDING_DEGRADED = True
        raise EmbeddingUnavailableError("OpenRouter embeddings are disabled by RAG_DISABLE_DENSE_EMBEDDING.")
    if _DENSE_EMBEDDING_UNAVAILABLE:
        _EMBEDDING_DEGRADED = True
        raise EmbeddingUnavailableError("OpenRouter embeddings unavailable.")
    try:
        vector = embed_text(text[:EMBEDDING_TEXT_CHAR_LIMIT], embedding_config_from_env())
    except Exception as exc:
        if _allow_hash_embedding_fallback():
            _EMBEDDING_DEGRADED = True
            return _hash_embedding_vector(text, dimensions=dimensions), EMBEDDING_SPACE_HASH
        _DENSE_EMBEDDING_UNAVAILABLE = True
        _EMBEDDING_DEGRADED = True
        raise EmbeddingUnavailableError(
            "OpenRouter embeddings unavailable. Set OPENROUTER_API_KEY or choose a reachable OpenRouter embedding model."
        ) from exc
    if not vector:
        _DENSE_EMBEDDING_UNAVAILABLE = True
        _EMBEDDING_DEGRADED = True
        raise EmbeddingUnavailableError("OpenRouter embedding response was empty.")
    return _normalize_embedding_dimensions(vector, dimensions), EMBEDDING_SPACE_DENSE


def _embedding_vectors_and_space(
    texts: list[str],
    *,
    dimensions: int = EMBEDDING_DIMENSIONS,
    manifest: dict[str, Any] | None = None,
) -> tuple[list[list[float]], str]:
    global _DENSE_EMBEDDING_UNAVAILABLE, _EMBEDDING_DEGRADED
    if not texts:
        return [], EMBEDDING_SPACE_DENSE
    manifest_space = str(manifest.get("embedding_space") or "") if manifest else ""
    if manifest and manifest_space and manifest_space != EMBEDDING_SPACE_DENSE:
        if _allow_hash_embedding_fallback() and manifest_space == EMBEDDING_SPACE_HASH:
            return [_hash_embedding_vector(text, dimensions=dimensions) for text in texts], EMBEDDING_SPACE_HASH
        _EMBEDDING_DEGRADED = True
        raise EmbeddingUnavailableError(
            f"Index embedding space is {manifest_space}; expected {EMBEDDING_SPACE_DENSE}. Rebuild the index."
        )
    if _dense_embeddings_disabled():
        _DENSE_EMBEDDING_UNAVAILABLE = True
        _EMBEDDING_DEGRADED = True
        raise EmbeddingUnavailableError("OpenRouter embeddings are disabled by RAG_DISABLE_DENSE_EMBEDDING.")
    if _DENSE_EMBEDDING_UNAVAILABLE:
        _EMBEDDING_DEGRADED = True
        raise EmbeddingUnavailableError("OpenRouter embeddings unavailable.")
    try:
        vectors = embed_texts([text[:EMBEDDING_TEXT_CHAR_LIMIT] for text in texts], embedding_config_from_env())
    except Exception as exc:
        if _allow_hash_embedding_fallback():
            _EMBEDDING_DEGRADED = True
            return [_hash_embedding_vector(text, dimensions=dimensions) for text in texts], EMBEDDING_SPACE_HASH
        _DENSE_EMBEDDING_UNAVAILABLE = True
        _EMBEDDING_DEGRADED = True
        raise EmbeddingUnavailableError(
            "OpenRouter embeddings unavailable. Set OPENROUTER_API_KEY or choose a reachable OpenRouter embedding model."
        ) from exc
    if len(vectors) != len(texts):
        _DENSE_EMBEDDING_UNAVAILABLE = True
        _EMBEDDING_DEGRADED = True
        raise EmbeddingUnavailableError("OpenRouter embedding response row count did not match input count.")
    return [_normalize_embedding_dimensions(vector, dimensions) for vector in vectors], EMBEDDING_SPACE_DENSE


def _embedding_batch_size() -> int:
    try:
        value = int(os.getenv("OPENROUTER_EMBED_BATCH_SIZE", "64") or "64")
    except ValueError:
        value = 64
    return max(1, min(value, 256))


def _allow_hash_embedding_fallback() -> bool:
    return str(os.getenv("LLM_WIKI_ALLOW_HASH_FALLBACK") or "").strip().lower() in {"1", "true", "yes", "on"}


def _hash_embedding_vector(text: str, *, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    seed = hashlib.sha256(text.encode("utf-8", errors="replace")).digest()
    values: list[float] = []
    block = seed
    while len(values) < dimensions:
        block = hashlib.sha256(block + seed).digest()
        values.extend(((byte / 127.5) - 1.0) for byte in block)
    return _normalize_embedding_dimensions(values[:dimensions], dimensions)


def _normalize_embedding_dimensions(vector: list[float], dimensions: int) -> list[float]:
    values = [float(value) for value in vector[:dimensions]]
    if len(values) < dimensions:
        values.extend([0.0] * (dimensions - len(values)))
    norm = math.sqrt(sum(value * value for value in values))
    if not norm:
        return values
    return [round(value / norm, 6) for value in values]


def _dense_embeddings_disabled() -> bool:
    return os.getenv("RAG_DISABLE_DENSE_EMBEDDING", "").strip().lower() in {"1", "true", "yes", "on"}


def _reset_embedding_backend_state() -> None:
    global _DENSE_EMBEDDING_UNAVAILABLE, _EMBEDDING_DEGRADED
    _DENSE_EMBEDDING_UNAVAILABLE = False
    _EMBEDDING_DEGRADED = _dense_embeddings_disabled()


def _embedding_degraded() -> bool:
    return _EMBEDDING_DEGRADED


def _cosine_similarity(
    left: list[float],
    right: Any,
    *,
    left_space: str = "",
    right_space: str = "",
) -> float:
    if left_space and right_space and left_space != right_space:
        return 0.0
    if not isinstance(right, list) or len(right) != len(left):
        return 0.0
    total = 0.0
    for lvalue, rvalue in zip(left, right):
        try:
            total += float(lvalue) * float(rvalue)
        except (TypeError, ValueError):
            continue
    return max(0.0, total)


def _read_parser_metadata(site_root: Path, rel_path: str) -> tuple[dict[str, Any], str, str]:
    if not rel_path:
        return {}, "", ""
    path, path_error = _resolve_site_path(site_root, rel_path)
    if path_error:
        return {}, "", path_error
    if path is None or not path.exists() or not path.is_file():
        return {}, "", ""
    checksum = checksum_file(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}, checksum, ""
    return (payload if isinstance(payload, dict) else {"value": payload}), checksum, ""


def _resolve_site_path(site_root: Path, rel_path: str) -> tuple[Path | None, str]:
    if not rel_path:
        return None, ""
    root = site_root.resolve()
    raw = Path(rel_path)
    candidate = raw if raw.is_absolute() else site_root / raw
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None, "path_escapes_site_root"
    return resolved, ""


def _keyword_score(tokens: list[str], title: str, text: str) -> float:
    haystack = f"{title}\n{text}".lower()
    score = 0.0
    for token in set(tokens):
        if token and token in title.lower():
            score += 0.4
        if re.search(rf"\b{re.escape(token)}\b", haystack):
            score += 0.1
    if " ".join(tokens) and " ".join(tokens) in haystack:
        score += 0.8
    return score


def _snippet(text: str, tokens: list[str], *, chars: int = 320) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= chars:
        return compact
    lower = compact.lower()
    first = min([lower.find(token) for token in tokens if token and lower.find(token) >= 0] or [0])
    start = max(0, first - chars // 4)
    snippet = compact[start : start + chars].strip()
    if start > 0:
        snippet = "..." + snippet
    if start + chars < len(compact):
        snippet = snippet.rstrip() + "..."
    return snippet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or query deterministic LLM Wiki indexes.")
    parser.add_argument("--site-root", required=True)
    parser.add_argument("--query", default="")
    args = parser.parse_args(argv)
    if args.query:
        print(json.dumps(query_llm_wiki_index(Path(args.site_root), args.query), ensure_ascii=True))
    else:
        print(json.dumps(build_llm_wiki_index(Path(args.site_root)), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
