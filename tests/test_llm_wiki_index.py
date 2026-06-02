from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.scrape_planner.sources.source_registry import checksum_text, write_registry_rows

from tests.fixtures.llm_wiki import LATER, NOW, _fixture_site, _write_source, _write_wiki_page


def test_wiki_documents_include_nested_category_source_pages(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_index import _wiki_documents

    site_root = tmp_path / "site"
    nested = site_root / "wiki" / "pages" / "programs"
    nested.mkdir(parents=True)
    (nested / "computer-science.md").write_text(
        "---\ntitle: Computer Science\nsource_ids:\n  - web_cs\ntags:\n  - programs\nupdated_at: now\n---\n# Computer Science\n\nProgram details.",
        encoding="utf-8",
    )

    docs, invalid = _wiki_documents(site_root, chunk_chars=1000, overlap=0)

    assert invalid == []
    assert docs
    assert docs[0].path == "wiki/pages/programs/computer-science.md"
    assert docs[0].source_ids == ["web_cs"]


def test_wiki_documents_preserve_school_department_and_office_routing(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_index import _wiki_documents

    site_root = tmp_path / "site"
    nested = site_root / "wiki" / "pages" / "registrar"
    nested.mkdir(parents=True)
    (nested / "computer-science.md").write_text(
        "---\n"
        "title: Computer Science Registrar Guide\n"
        "source_ids:\n  - web_cs\n"
        "tags:\n  - registrar\n"
        "schools:\n  - lyle-school-of-engineering\n"
        "departments:\n  - computer-science\n"
        "offices:\n  - registrar\n"
        f"updated_at: {NOW}\n"
        "---\n"
        "# Computer Science Registrar Guide\n\nEnrollment and transcript details.",
        encoding="utf-8",
    )

    docs, invalid = _wiki_documents(site_root, chunk_chars=1000, overlap=0)

    assert invalid == []
    assert docs[0].metadata["routing"]["schools"] == ["lyle-school-of-engineering"]
    assert docs[0].metadata["routing"]["departments"] == ["computer-science"]
    assert docs[0].metadata["routing"]["offices"] == ["registrar"]


def test_query_prefers_semantic_cox_pages_for_multi_aspect_student_question(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

    site_root = tmp_path / "site"
    raw = _write_source(
        site_root,
        source_id="web_cox_admissions",
        title="Cox Admissions Raw",
        body="# Cox Admissions\n\nGraduate applicants apply by February 1. Tuition and courses are described by Cox.",
    )
    raw["wiki_page_paths"] = ["wiki/pages/schools/cox/graduate.md"]
    write_registry_rows(site_root / "raw_sources" / "registry.jsonl", [raw])
    semantic = site_root / "wiki" / "pages" / "schools" / "cox"
    semantic.mkdir(parents=True)
    (semantic / "graduate.md").write_text(
        "---\n"
        "title: Cox Graduate Student Guide\n"
        "page_type: semantic\n"
        "school: cox\n"
        "programs:\n  - mba\n"
        "degree_levels:\n  - graduate\n"
        "intents:\n  - study\n  - apply\n  - pay\n"
        "topics:\n  - courses\n  - costs\n  - admissions\n"
        "source_priority: semantic-wiki\n"
        "source_ids:\n  - web_cox_admissions\n"
        "tags:\n  - cox\n  - graduate\n"
        f"updated_at: {NOW}\n"
        "---\n"
        "# Cox Graduate Student Guide\n\n"
        "## Courses / Curriculum\nCox graduate courses and curriculum are summarized here.\n\n"
        "## Costs / Fees / Aid\nTuition and course fees are summarized here.\n\n"
        "## Admissions / Requirements / Deadlines\nAdmissions process and deadlines are summarized here.\n",
        encoding="utf-8",
    )

    build_llm_wiki_index(site_root, now=NOW)
    response = query_llm_wiki_index(
        site_root,
        "I am a new graduate student likely joining Cox; tell me about courses, course fees, and the admission process",
        max_evidence=3,
    )

    assert response["status"] == "ok"
    assert response["evidence"]
    assert response["evidence"][0]["path"] == "wiki/pages/schools/cox/graduate.md"
    assert response["evidence"][0]["metadata"]["routing"]["page_type"] == "semantic"


def test_query_returns_next_pages_from_navigation_manifest(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

    site_root = _fixture_site(tmp_path)
    (site_root / "wiki" / "navigation_manifest.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "graduate-application-workflow",
                        "title": "Graduate Application Workflow",
                        "path": "wiki/pages/workflows/graduate-application-workflow.md",
                        "summary": "Next page for admissions requirements and application steps.",
                        "page_type": "workflow",
                        "tags": ["admissions", "graduate"],
                        "entities": ["Graduate Admissions"],
                        "priority": 95,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    build_llm_wiki_index(site_root, now=NOW)

    response = query_llm_wiki_index(site_root, "What is the admissions application deadline?", max_evidence=1)

    assert response["metadata"]["next_pages"]
    assert response["metadata"]["next_pages"][0]["title"] == "Graduate Application Workflow"


def test_build_query_prefers_relevant_wiki_and_includes_raw_support(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

    site_root = _fixture_site(tmp_path)

    report = build_llm_wiki_index(site_root, now=NOW)
    assert report["status"] == "ready"
    assert report["raw_index_count"] >= 2
    assert report["wiki_index_count"] == 1
    assert report["changed_raw_count"] == report["raw_index_count"]
    assert report["changed_wiki_count"] == 1
    assert report["embedding"]["provider"] == "ollama"
    assert "fallback_provider" not in report["embedding"]
    assert report["embedding"]["degraded"] is False
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
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

    site_root = _fixture_site(tmp_path)
    build_llm_wiki_index(site_root, now=NOW)

    response = query_llm_wiki_index(site_root, "graduate catalog tuition credits", max_evidence=2)

    assert response["status"] == "ok"
    assert response["evidence"][0]["source_kind"] == "pdf"
    assert response["evidence"][0]["source_id"] == "pdf_catalog"
    assert response["evidence"][0]["scores"]["vector"] > 0


def test_mcp_query_uses_bm25_wiki_first_for_factual_questions(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_mcp_wiki_index

    site_root = _fixture_site(tmp_path)
    build_llm_wiki_index(site_root, now=NOW)

    response = query_mcp_wiki_index(site_root, "When is the admissions application deadline?", max_evidence=2)

    assert response["status"] == "ok"
    assert response["metadata"]["retrieval"]["query_type"] == "factual"
    assert response["metadata"]["retrieval"]["selected_strategy"] == "hybrid_fused"
    assert response["metadata"]["retrieval"]["attempted_strategies"] == ["wiki_bm25", "vector"]
    assert response["evidence"][0]["source_kind"] == "wiki"
    assert response["evidence"][0]["path"] == "wiki/pages/admissions.md"
    assert response["evidence"][0]["scores"]["bm25"] > 0
    assert "bm25_wiki_match" in response["evidence"][0]["ranking_reasons"]
    assert any("bm25_cited_raw_support" in row["ranking_reasons"] for row in response["evidence"])


def test_mcp_factual_bm25_falls_back_to_hybrid_when_wiki_has_no_hit(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_mcp_wiki_index

    site_root = _fixture_site(tmp_path)
    build_llm_wiki_index(site_root, now=NOW)

    response = query_mcp_wiki_index(site_root, "graduate catalog tuition credits", max_evidence=2)

    assert response["status"] == "ok"
    assert response["metadata"]["retrieval"]["query_type"] == "factual"
    assert response["metadata"]["retrieval"]["selected_strategy"] == "hybrid_fused"
    assert response["metadata"]["retrieval"]["attempted_strategies"] == ["wiki_bm25", "vector"]
    assert response["evidence"][0]["source_kind"] == "pdf"
    assert response["evidence"][0]["source_id"] == "pdf_catalog"


def test_mcp_query_uses_vector_search_for_reasoning_questions(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_mcp_wiki_index

    site_root = tmp_path / "site"
    pathway = _write_source(
        site_root,
        source_id="web_pathway",
        title="Startup Mentorship Pathway",
        body="# Startup Mentorship Pathway\n\nStudents choose the startup mentorship pathway for venture labs and coaching.",
    )
    calendar = _write_source(
        site_root,
        source_id="web_calendar",
        title="Academic Calendar",
        body="# Academic Calendar\n\nThe fall deadline is October 1 and the spring deadline is March 1.",
    )
    pathway["wiki_page_paths"] = ["wiki/pages/startup-pathway.md"]
    calendar["wiki_page_paths"] = ["wiki/pages/calendar.md"]
    write_registry_rows(site_root / "raw_sources" / "registry.jsonl", [pathway, calendar])
    _write_wiki_page(
        site_root,
        name="startup-pathway",
        title="Startup Mentorship Pathway",
        tags=["entrepreneurship"],
        source_ids=["web_pathway"],
        body="# Startup Mentorship Pathway\n\nThe startup mentorship pathway helps students choose venture labs and coaching.",
    )
    _write_wiki_page(
        site_root,
        name="calendar",
        title="Academic Calendar",
        tags=["dates"],
        source_ids=["web_calendar"],
        body="# Academic Calendar\n\nFall deadline details and spring deadline details are listed here.",
    )
    build_llm_wiki_index(site_root, now=NOW)

    response = query_mcp_wiki_index(site_root, "Why should a student choose the startup mentorship pathway?", max_evidence=2)

    assert response["status"] == "ok"
    assert response["metadata"]["retrieval"]["query_type"] == "reasoning"
    assert response["metadata"]["retrieval"]["selected_strategy"] == "hybrid_fused"
    assert response["evidence"][0]["path"] == "wiki/pages/startup-pathway.md"
    assert "vector_candidate" in response["evidence"][0]["ranking_reasons"]
    assert response["evidence"][0]["scores"]["retrieval_vector"] > 0


def test_profile_routing_prefers_undergraduate_page_over_graduate_noise(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

    site_root = tmp_path / "site"
    undergrad = _write_source(
        site_root,
        source_id="web_undergrad",
        title="Undergraduate Programs",
        body="# Undergraduate Programs\n\nHigh school students can explore undergraduate computer science majors.",
    )
    graduate = _write_source(
        site_root,
        source_id="web_grad",
        title="Graduate Research",
        body="# Graduate Research\n\nGraduate computer science applicants review doctoral labs and faculty research.",
    )
    undergrad["wiki_page_paths"] = ["wiki/pages/undergraduate.md"]
    graduate["wiki_page_paths"] = ["wiki/pages/graduate.md"]
    write_registry_rows(site_root / "raw_sources" / "registry.jsonl", [undergrad, graduate])
    _write_wiki_page(
        site_root,
        name="undergraduate",
        title="Undergraduate Programs",
        tags=["programs"],
        source_ids=["web_undergrad"],
        audiences=["undergraduate", "secondary-student"],
        roles=["applicant"],
        intents=["explore", "study"],
        academic_interests=["computer"],
        body="# Undergraduate Programs\n\nUndergraduate computer science majors are designed for new college students.",
    )
    _write_wiki_page(
        site_root,
        name="graduate",
        title="Graduate Research",
        tags=["research"],
        source_ids=["web_grad"],
        audiences=["graduate", "researcher"],
        roles=["applicant"],
        intents=["research", "study"],
        academic_interests=["computer"],
        body="# Graduate Research\n\nGraduate doctoral labs focus on computer science research.",
    )
    build_llm_wiki_index(site_root, now=NOW)

    response = query_llm_wiki_index(
        site_root,
        "computer science programs",
        profile={"education_level": "secondary student", "intent": "study", "academic_interest": "computer"},
        max_evidence=3,
    )

    assert response["status"] == "ok"
    assert response["evidence"][0]["path"] == "wiki/pages/undergraduate.md"
    assert "education_level_match" in response["evidence"][0]["ranking_reasons"]
    assert response["metadata"]["routing"]["profile"]["education_level"] == "secondary student"


def test_query_reports_insufficient_evidence_when_no_candidates_match(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

    site_root = _fixture_site(tmp_path)
    build_llm_wiki_index(site_root, now=NOW)

    response = query_llm_wiki_index(site_root, "zzzzqwerty impossible-nohit", max_evidence=3)

    assert response["status"] == "insufficient_evidence"
    assert response["evidence"] == []
    assert response["metadata"]["reason"] == "no_related_candidates"


def test_canonical_department_page_outranks_broad_raw_leadership_chunk(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

    site_root = tmp_path / "site"
    raw = _write_source(
        site_root,
        source_id="web_directory",
        title="Large Faculty Directory",
        body="# Large Faculty Directory\n\nThe directory mentions Computer Science chair Jane Rivera alongside many unrelated offices.",
    )
    raw["wiki_page_paths"] = ["wiki/pages/computer-science.md"]
    write_registry_rows(site_root / "raw_sources" / "registry.jsonl", [raw])
    _write_wiki_page(
        site_root,
        name="computer-science",
        title="Computer Science Department",
        tags=["departments"],
        source_ids=["web_directory"],
        audiences=["graduate", "undergraduate"],
        roles=["student"],
        intents=["study", "contact"],
        academic_interests=["computer"],
        body="# Computer Science Department\n\n## Fast Answer\n\nThe Computer Science chair is Jane Rivera.\n",
    )
    build_llm_wiki_index(site_root, now=NOW)

    response = query_llm_wiki_index(site_root, "Who is the Computer Science chair?", max_evidence=2)

    assert response["status"] == "ok"
    assert response["evidence"][0]["source_kind"] == "wiki"
    assert response["evidence"][0]["path"] == "wiki/pages/computer-science.md"
    assert "wiki_synthesis_boost" in response["evidence"][0]["ranking_reasons"]


def test_networking_director_query_surfaces_program_leadership_page(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

    site_root = tmp_path / "site"
    raw = _write_source(
        site_root,
        source_id="web_ms_net",
        title="M.S. Network Engineering",
        body=(
            "# M.S. Network Engineering\n\n"
            "M. Scott Kingsley, Eng.D. — Director of Graduate Network Engineering Program\n\n"
            "The program covers telecommunications and network design."
        ),
    )
    raw["wiki_page_paths"] = ["wiki/pages/ms-network-engineering.md"]
    write_registry_rows(site_root / "raw_sources" / "registry.jsonl", [raw])
    _write_wiki_page(
        site_root,
        name="ms-network-engineering",
        title="M.S. Network Engineering",
        tags=["programs", "leadership"],
        source_ids=["web_ms_net"],
        audiences=["graduate"],
        roles=["student"],
        intents=["study", "contact"],
        academic_interests=["engineering"],
        body=(
            "# M.S. Network Engineering\n\n"
            "## Fast Answer\n\n"
            "M. Scott Kingsley, Eng.D. — Director of Graduate Network Engineering Program\n"
        ),
    )
    _write_wiki_page(
        site_root,
        name="networking-social-events",
        title="Networking Social Events",
        tags=["events"],
        source_ids=[],
        audiences=["graduate"],
        roles=["student"],
        intents=["visit"],
        academic_interests=[],
        body="# Networking Social Events\n\nCareer networking happy hour.\n",
    )
    build_llm_wiki_index(site_root, now=NOW)

    response = query_llm_wiki_index(site_root, "Who is the director of SMU networking?", max_evidence=3)

    assert response["status"] == "ok"
    assert response["evidence"]
    top_path = str(response["evidence"][0]["path"])
    assert "ms-network-engineering" in top_path
    assert response["metadata"]["confidence"]["confident"] is True
    assert "leadership_entity_match" in response["metadata"]["confidence"]["reasons"]


def test_search_sources_retrieves_raw_candidates_before_filtering_mixed_results(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, search_source_index

    site_root = _fixture_site(tmp_path)
    build_llm_wiki_index(site_root, now=NOW)

    response = search_source_index(site_root, "admissions application deadline", max_evidence=2, max_candidates=1)

    assert response["status"] == "ok"
    assert response["evidence"]
    assert all(row["source_kind"] != "wiki" for row in response["evidence"])
    assert response["evidence"][0]["source_id"] == "web_admissions"
    assert response["metadata"]["source_only"] is True


def test_query_uses_openrouter_rerank_when_configured(tmp_path: Path, monkeypatch) -> None:
    import src.scrape_planner.wiki.llm_wiki_index as llm_wiki_index
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

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


def test_build_fails_when_dense_embeddings_are_unavailable(tmp_path: Path, monkeypatch) -> None:
    import src.scrape_planner.wiki.llm_wiki_index as llm_wiki_index
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index

    site_root = _fixture_site(tmp_path)
    monkeypatch.delenv("RAG_DISABLE_DENSE_EMBEDDING", raising=False)
    monkeypatch.setattr(llm_wiki_index, "embed_text", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))

    with pytest.raises(llm_wiki_index.EmbeddingUnavailableError, match="Ollama dense embeddings unavailable"):
        build_llm_wiki_index(site_root, now=NOW)

    assert not (site_root / "indexes" / "llm_wiki_manifest.json").exists()


def test_mcp_query_fails_for_degraded_hash_index_manifest(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_mcp_wiki_index

    site_root = _fixture_site(tmp_path)
    report = build_llm_wiki_index(site_root, now=NOW)
    manifest_path = Path(report["report_path"]).parent.parent / "llm_wiki_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["embedding_degraded"] = True
    manifest["embedding_space"] = "hash-fallback"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    response = query_mcp_wiki_index(site_root, "When is the admissions application deadline?", max_evidence=2)

    assert response["status"] == "embedding_unavailable"
    assert response["evidence"] == []
    assert response["metadata"]["reason"] == "embedding_degraded"
    assert response["metadata"]["embedding_space"] == "hash-fallback"



def test_incremental_reuses_unchanged_documents_and_reindexes_changed_raw(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index

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
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

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
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

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
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index

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
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index

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
