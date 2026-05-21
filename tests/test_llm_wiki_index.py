from __future__ import annotations

import json
from pathlib import Path

from src.scrape_planner.source_registry import build_source_row, checksum_text, write_registry_rows


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


def _write_wiki_page(
    site_root: Path,
    *,
    name: str,
    title: str,
    tags: list[str],
    source_ids: list[str],
    body: str,
    updated_at: str = NOW,
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


def test_build_query_prefers_relevant_wiki_and_includes_raw_support(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

    site_root = _fixture_site(tmp_path)

    report = build_llm_wiki_index(site_root, now=NOW)
    assert report["status"] == "ready"
    assert report["raw_index_count"] >= 2
    assert report["wiki_index_count"] == 1
    assert report["changed_raw_count"] == report["raw_index_count"]
    assert report["changed_wiki_count"] == 1
    assert report["embedding"]["provider"] == "deterministic-hash-embedding"
    assert report["embedding"]["vector_dimensions"] > 0

    docs = [
        json.loads(line)
        for line in (site_root / "indexes" / "llm_wiki_documents.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert all(len(row["embedding_vector"]) == report["embedding"]["vector_dimensions"] for row in docs)
    raw_doc = next(row for row in docs if row["source_id"] == "web_admissions" and row["corpus"] == "raw")
    assert raw_doc["metadata"]["parser_metadata"]["parser_detail"] == "fixture"

    response = query_llm_wiki_index(site_root, "What is the admissions application deadline?", max_evidence=3)
    assert response["status"] == "ok"
    assert response["query"] == "What is the admissions application deadline?"
    evidence = response["evidence"]
    assert evidence[0]["source_kind"] == "wiki"
    assert evidence[0]["path"] == "wiki/pages/admissions.md"
    assert evidence[0]["source_ids"] == ["web_admissions"]
    assert any(row["source_kind"] == "web" and row["source_id"] == "web_admissions" for row in evidence[1:])
    assert evidence[0]["scores"]["combined"] >= evidence[0]["scores"]["lexical"]
    assert "wiki_synthesis_boost" in evidence[0]["ranking_reasons"]
    assert any("cites_raw_candidate" in row["ranking_reasons"] for row in evidence)
    assert any("cited_by_wiki_candidate" in row["ranking_reasons"] for row in evidence if row["source_kind"] != "wiki")
    assert evidence[0]["scores"]["vector"] > 0


def test_raw_source_fallback_when_wiki_is_weak(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

    site_root = _fixture_site(tmp_path)
    build_llm_wiki_index(site_root, now=NOW)

    response = query_llm_wiki_index(site_root, "graduate catalog tuition credits", max_evidence=2)

    assert response["status"] == "ok"
    assert response["evidence"][0]["source_kind"] == "pdf"
    assert response["evidence"][0]["source_id"] == "pdf_catalog"
    assert "raw_source_fallback" in response["evidence"][0]["ranking_reasons"]


def test_search_sources_retrieves_raw_candidates_before_filtering_mixed_results(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_index import build_llm_wiki_index, search_source_index

    site_root = _fixture_site(tmp_path)
    build_llm_wiki_index(site_root, now=NOW)

    response = search_source_index(site_root, "admissions application deadline", max_evidence=2, max_candidates=1)

    assert response["status"] == "ok"
    assert response["evidence"]
    assert all(row["source_kind"] != "wiki" for row in response["evidence"])
    assert response["evidence"][0]["source_id"] == "web_admissions"
    assert response["metadata"]["source_only"] is True


def test_query_uses_openrouter_rerank_when_configured(tmp_path: Path, monkeypatch) -> None:
    import src.scrape_planner.llm_wiki_index as llm_wiki_index
    from src.scrape_planner.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

    site_root = _fixture_site(tmp_path)
    build_llm_wiki_index(site_root, now=NOW)

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("OPENROUTER_RERANK_MODEL", "cohere/rerank-4-pro")
    captured: dict[str, object] = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            documents = list(captured["json"]["documents"])  # type: ignore[index]
            raw_index = next(idx for idx, doc in enumerate(documents) if "Admissions Raw" in str(doc))
            wiki_index = next(idx for idx, doc in enumerate(documents) if "The admissions wiki says" in str(doc))
            return {
                "model": "cohere/rerank-4-pro",
                "results": [
                    {"index": raw_index, "relevance_score": 0.98},
                    {"index": wiki_index, "relevance_score": 0.41},
                ],
                "provider": "openrouter",
            }

    def _fake_post(url: str, *, headers: dict, json: dict, timeout: int) -> _Response:
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(llm_wiki_index.requests, "post", _fake_post)

    response = query_llm_wiki_index(site_root, "What is the admissions application deadline?", max_evidence=2, max_candidates=5)

    assert captured["url"] == "https://openrouter.ai/api/v1/rerank"
    assert captured["headers"]["Authorization"] == "Bearer test-openrouter-key"  # type: ignore[index]
    assert captured["json"]["model"] == "cohere/rerank-4-pro"  # type: ignore[index]
    assert captured["json"]["query"] == "What is the admissions application deadline?"  # type: ignore[index]
    assert response["status"] == "ok"
    assert response["evidence"][0]["source_id"] == "web_admissions"
    assert response["evidence"][0]["scores"]["model_rerank"] == 0.98
    assert "openrouter_rerank" in response["evidence"][0]["ranking_reasons"]


def test_incremental_reuses_unchanged_documents_and_reindexes_changed_raw(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_index import build_llm_wiki_index

    site_root = _fixture_site(tmp_path)
    first = build_llm_wiki_index(site_root, now=NOW)
    assert first["changed_document_count"] == first["raw_index_count"] + first["wiki_index_count"]

    second = build_llm_wiki_index(site_root, now=LATER)
    assert second["changed_document_count"] == 0
    assert second["skipped_document_count"] == first["raw_index_count"] + first["wiki_index_count"]

    raw_path = site_root / "raw_sources" / "web" / "web_admissions.md"
    changed_body = raw_path.read_text(encoding="utf-8") + "\nNew portfolio requirement.\n"
    raw_path.write_text(changed_body, encoding="utf-8")
    rows = [
        _write_source(
            site_root,
            source_id="web_admissions",
            title="Admissions Raw",
            body=changed_body,
            checksum=checksum_text(changed_body),
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

    third = build_llm_wiki_index(site_root, now="2026-05-21T14:00:00+00:00")
    assert third["changed_raw_count"] == 1
    assert third["changed_wiki_count"] == 0
    assert third["skipped_document_count"] == second["raw_index_count"] + second["wiki_index_count"] - 1


def test_incremental_reindexes_raw_when_file_changes_but_registry_checksum_is_stale(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

    site_root = _fixture_site(tmp_path)
    build_llm_wiki_index(site_root, now=NOW)

    raw_path = site_root / "raw_sources" / "web" / "web_admissions.md"
    changed_body = raw_path.read_text(encoding="utf-8") + "\nScholarship essays now require cobalt-river evidence.\n"
    raw_path.write_text(changed_body, encoding="utf-8")

    report = build_llm_wiki_index(site_root, now=LATER)

    assert report["changed_raw_count"] > 0
    response = query_llm_wiki_index(site_root, "cobalt-river evidence", max_evidence=3)
    assert response["status"] == "ok"
    assert any("cobalt-river evidence" in row["snippet"] for row in response["evidence"])


def test_registry_path_escape_is_skipped_and_not_indexed(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

    site_root = tmp_path / "site"
    outside = tmp_path / "outside.md"
    outside.write_text("# Escaped\n\noutside-only sentinel phrase\n", encoding="utf-8")
    row = _write_source(
        site_root,
        source_id="escaped",
        title="Escaped Source",
        body="# Placeholder\n\nThis should be overwritten by the test row.\n",
    )
    row["markdown_path"] = "../outside.md"
    row["metadata_path"] = "../outside.metadata.json"
    row["checksum"] = checksum_text(outside.read_text(encoding="utf-8"))
    write_registry_rows(site_root / "raw_sources" / "registry.jsonl", [row])

    report = build_llm_wiki_index(site_root, now=NOW)

    assert report["raw_index_count"] == 0
    assert any(item["source_id"] == "escaped" and item["reason"] == "path_escapes_site_root" for item in report["invalid_sources"])
    response = query_llm_wiki_index(site_root, "outside-only sentinel phrase", max_evidence=3)
    assert response["evidence"] == []


def test_registry_metadata_path_escape_is_reported_without_reading_metadata(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_index import build_llm_wiki_index

    site_root = tmp_path / "site"
    outside_metadata = tmp_path / "outside.metadata.json"
    outside_metadata.write_text(json.dumps({"parser_detail": "outside metadata should not be read"}), encoding="utf-8")
    row = _write_source(
        site_root,
        source_id="web_metadata_escape",
        title="Metadata Escape",
        body="# Metadata Escape\n\nsafe raw body\n",
    )
    row["metadata_path"] = "../outside.metadata.json"
    write_registry_rows(site_root / "raw_sources" / "registry.jsonl", [row])

    report = build_llm_wiki_index(site_root, now=NOW)

    assert report["raw_index_count"] == 1
    assert any(
        item["source_id"] == "web_metadata_escape"
        and item["field"] == "metadata_path"
        and item["reason"] == "path_escapes_site_root"
        for item in report["invalid_sources"]
    )
    docs = [
        json.loads(line)
        for line in (site_root / "indexes" / "llm_wiki_documents.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert docs[0]["metadata"]["parser_metadata"] == {}


def test_explainable_evidence_schema_is_stable(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

    site_root = _fixture_site(tmp_path)
    build_llm_wiki_index(site_root, now=NOW)

    response = query_llm_wiki_index(site_root, "admissions deadline", max_evidence=1)

    assert set(response) >= {"status", "query", "evidence", "metadata"}
    row = response["evidence"][0]
    assert set(row) >= {
        "id",
        "source_kind",
        "source_id",
        "source_ids",
        "path",
        "title",
        "snippet",
        "scores",
        "ranking_reasons",
        "checksum",
    }
    assert set(row["scores"]) >= {"lexical", "vector", "keyword", "source_priority", "freshness", "citation", "combined"}
    assert isinstance(row["ranking_reasons"], list)
