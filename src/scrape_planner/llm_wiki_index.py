from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .run_persistence import _append_jsonl, _write_json_atomic
from .site_layout import ensure_layout_for_site_root, site_layout
from .source_registry import checksum_file, read_registry_rows, utc_now_iso


INDEX_VERSION = "llm-wiki-hybrid-v1"
EMBEDDING_PROVIDER = "deterministic-hash-embedding"
EMBEDDING_MODEL = "hashed-token-vector-v1"
EMBEDDING_DIMENSIONS = 64
RERANK_PROVIDER = "openrouter"
RERANK_API_URL = "https://openrouter.ai/api/v1/rerank"
RERANK_MODEL = "cohere/rerank-4-pro"
TOKEN_RE = re.compile(r"[a-z0-9]+")


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


def build_llm_wiki_index(
    site_root: Path,
    *,
    chunk_chars: int = 1600,
    overlap: int = 200,
    now: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic dual-corpus index for raw sources and wiki pages."""
    timestamp = now or utc_now_iso()
    layout = ensure_layout_for_site_root(Path(site_root))
    index_dir = layout.indexes_dir
    docs_path = index_dir / "llm_wiki_documents.jsonl"
    postings_path = index_dir / "llm_wiki_postings.json"
    manifest_path = index_dir / "llm_wiki_manifest.json"

    previous_docs = _read_documents(docs_path)
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
    for doc in raw_docs + wiki_docs:
        old = previous_by_id.get(doc.id)
        if old and _document_row_current(old, doc):
            current_docs.append(old)
            skipped += 1
            continue
        as_row = _document_row(doc)
        current_docs.append(as_row)
        if doc.corpus == "raw":
            changed_raw += 1
        else:
            changed_wiki += 1

    postings = _build_postings(current_docs)
    if docs_path.exists():
        docs_path.unlink()
    for row in sorted(current_docs, key=lambda item: str(item.get("id") or "")):
        _append_jsonl(docs_path, row)
    _write_json_atomic(postings_path, postings)

    raw_count = sum(1 for doc in current_docs if doc.get("corpus") == "raw")
    wiki_count = sum(1 for doc in current_docs if doc.get("corpus") == "wiki")
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
        "embedding": {
            "provider": EMBEDDING_PROVIDER,
            "model": EMBEDDING_MODEL,
            "vector_dimensions": EMBEDDING_DIMENSIONS,
        },
        "reranker": {
            "provider": RERANK_PROVIDER if _openrouter_rerank_ready() else "",
            "model": _openrouter_rerank_model() if _openrouter_rerank_ready() else "",
            "api_url": RERANK_API_URL if _openrouter_rerank_ready() else "",
        },
        "invalid_sources": invalid_sources,
    }
    _write_json_atomic(manifest_path, manifest)
    reports_dir = index_dir / "reports"
    report_path = reports_dir / f"embedding-{_timestamp_slug(timestamp)}.json"
    report = {**manifest, "report_path": str(report_path), "last_build_time": timestamp}
    _write_json_atomic(report_path, report)
    _write_json_atomic(index_dir / "embedding_status.json", {**report, "report_path": str(index_dir / "embedding_status.json")})
    return report


def query_llm_wiki_index(
    site_root: Path,
    query: str,
    *,
    max_evidence: int = 5,
    max_candidates: int = 50,
    profile: QueryProfile | dict[str, Any] | None = None,
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

    query_profile = infer_query_profile(query, profile)
    tokens = _tokenize(query)
    if max_evidence <= 0 or not tokens:
        return {
            "status": "ok",
            "query": query,
            "evidence": [],
            "metadata": {"bounded": True, "reason": "empty_query_or_zero_limit"},
        }

    candidates, lexical_scores = _retrieve_candidates_by_corpus(
        docs,
        postings if isinstance(postings, dict) else {},
        tokens,
        max_candidates=max_candidates,
    )
    evidence = rerank_candidates(query, candidates, lexical_scores, profile=query_profile)[:max_evidence]
    if not evidence:
        return {
            "status": "insufficient_evidence",
            "query": query,
            "evidence": [],
            "metadata": {
                "bounded": True,
                "reason": "no_related_candidates",
                "routing": _profile_metadata(query_profile, candidate_count=len(candidates)),
                "site_root": str(layout.site_root.resolve()),
            },
        }
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
            "routing": _profile_metadata(query_profile, evidence=evidence, candidate_count=len(candidates)),
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
    evidence = rerank_candidates(query, candidates, lexical_scores)[:max_evidence]
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


def rerank_candidates(
    query: str,
    candidates: list[dict[str, Any]],
    lexical_scores: dict[str, float],
    *,
    profile: QueryProfile | None = None,
) -> list[dict[str, Any]]:
    tokens = _tokenize(query)
    query_vector = _embedding_vector(query)
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
        vector = _cosine_similarity(query_vector, row.get("embedding_vector"))
        keyword = _keyword_score(tokens, str(row.get("title") or ""), str(row.get("text") or ""))
        is_wiki = row.get("corpus") == "wiki"
        source_priority = 1.2 if is_wiki else 0.0
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
        if vector > 0:
            reasons.append("vector_match")
        reasons.extend(route_reasons)
        if not is_wiki and best_wiki_lexical < lexical * 0.5:
            reasons.append("raw_source_fallback")
        if not reasons:
            reasons.append("lexical_match")
        combined = lexical + (1.5 * vector) + keyword + source_priority + route_score + freshness + citation
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
    except Exception:
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
    ready = str(manifest.get("status") or "") == "ready"
    return {
        "ok": ready,
        "ready": ready,
        "error": "" if ready else str(manifest.get("status") or "not_ready"),
        "site_root": str(layout.site_root.resolve()),
        "index_path": str(manifest_path),
        "raw_index_count": int(manifest.get("raw_index_count") or 0),
        "wiki_index_count": int(manifest.get("wiki_index_count") or 0),
        "last_build_time": str(manifest.get("built_at") or ""),
        "index_health": str(manifest.get("index_health") or manifest.get("status") or "missing"),
        "manifest": manifest,
        "config_snippet": generate_mcp_config_snippet(layout.site_root),
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
        checksum = _checksum_text(text)
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
    for path in sorted(pages_dir.glob("*.md")) if pages_dir.exists() else []:
        rel_path = _site_relative(path, site_root)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            invalid.append({"path": rel_path, "reason": f"wiki_page_unreadable:{exc}"})
            continue
        metadata = _parse_frontmatter(text)
        title = str(metadata.get("title") or path.stem.replace("-", " ").title())
        source_ids = [str(value) for value in metadata.get("source_ids", []) if str(value)] if isinstance(metadata.get("source_ids"), list) else []
        tags = [str(value) for value in metadata.get("tags", []) if str(value)] if isinstance(metadata.get("tags"), list) else []
        route_metadata = {
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
        for idx, chunk in enumerate(_chunk_text(_strip_frontmatter(text), chunk_chars=chunk_chars, overlap=overlap), start=1):
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
    vector = _embedding_vector(f"{doc.title}\n{doc.text}")
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
        "embedding_provider": EMBEDDING_PROVIDER,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimensions": EMBEDDING_DIMENSIONS,
        "embedding_vector": vector,
    }


def _document_row_current(row: dict[str, Any], doc: IndexedDocument) -> bool:
    if str(row.get("checksum") or "") != doc.checksum:
        return False
    if str(row.get("embedding_provider") or "") != EMBEDDING_PROVIDER:
        return False
    vector = row.get("embedding_vector")
    if not isinstance(vector, list) or len(vector) != EMBEDDING_DIMENSIONS:
        return False
    if doc.corpus == "raw" and doc.metadata.get("metadata_path"):
        old_metadata = row.get("metadata", {}) if isinstance(row.get("metadata"), dict) else {}
        if old_metadata.get("parser_metadata_checksum") != doc.metadata.get("parser_metadata_checksum"):
            return False
    return True


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
            "engineering": ("engineering",),
            "science": ("science",),
            "arts": ("arts", "music", "theatre"),
            "law": ("law",),
        },
    )
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


def _embedding_vector(text: str, *, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    for token, count in _token_counts(text).items():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 else -1.0
        vector[index] += sign * (1.0 + math.log(float(count)))
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [round(value / norm, 6) for value in vector]


def _cosine_similarity(left: list[float], right: Any) -> float:
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


def _checksum_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


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


def _parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    metadata: dict[str, Any] = {}
    current_key = ""
    for line in text[4:end].splitlines():
        if line.startswith("  - ") and current_key:
            metadata.setdefault(current_key, []).append(line[4:].strip())
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            current_key = key.strip()
            metadata[current_key] = value.strip() if value.strip() else []
    return metadata


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    if end < 0:
        return text
    return text[end + 4 :].lstrip()


def _site_relative(path: Path, site_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(site_root.resolve()))
    except ValueError:
        return str(path)


def _timestamp_slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z]+", "-", value).strip("-")
    return cleaned or hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


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
