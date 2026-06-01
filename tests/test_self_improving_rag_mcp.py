from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

from src.scrape_planner.core.site_layout import ensure_site_layout
from src.scrape_planner.wiki.web_search import MockWebSearchProvider, WebSearchResult, provider_from_env, web_search


def _confident_result() -> dict:
    return {
        "status": "ok",
        "evidence": [
            {
                "title": "Admissions",
                "snippet": "The deadline is February 1.",
                "source_kind": "wiki",
                "source_id": "wiki/pages/admissions.md",
                "source_ids": ["web_admissions"],
                "path": "wiki/pages/admissions.md",
                "scores": {"combined": 3.0},
            },
            {"scores": {"combined": 1.0}},
        ],
        "metadata": {},
    }


def _low_confidence_result() -> dict:
    return {"status": "insufficient_evidence", "evidence": [], "metadata": {}}


def _ready_index(site_root: Path) -> None:
    indexes = site_root / "indexes"
    indexes.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": "llm-wiki-hybrid-v2",
        "status": "ready",
        "raw_index_count": 2,
        "wiki_index_count": 2,
        "embedding_degraded": False,
        "vector_leg_enabled": True,
        "embedding_space": "dense-ollama",
    }
    (indexes / "llm_wiki_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (indexes / "llm_wiki_documents.jsonl").write_text("", encoding="utf-8")
    (indexes / "llm_wiki_postings.json").write_text("{}", encoding="utf-8")
    trusted = site_root / "config"
    trusted.mkdir(parents=True, exist_ok=True)
    (trusted / "trusted_domains.txt").write_text("example.edu\n", encoding="utf-8")


def test_answer_question_confident_answer_skips_web_search(tmp_path: Path, monkeypatch) -> None:
    import src.scrape_planner.wiki.self_improving as self_improving

    provider = MockWebSearchProvider([WebSearchResult(title="Admissions", url="https://example.edu/admissions", snippet="Admission details")])
    monkeypatch.setattr(self_improving, "query_mcp_wiki_index", lambda *args, **kwargs: _confident_result())

    result = self_improving.answer_question(tmp_path / "site", "When is the deadline?", provider=provider)

    assert result["status"] == "ok"
    assert result["provenance"] == "wiki"
    assert provider.calls == []
    assert result["metadata"]["confidence"]["confident"] is True


def test_answer_question_low_confidence_uses_web_and_queues_ingest(tmp_path: Path, monkeypatch) -> None:
    import src.scrape_planner.wiki.self_improving as self_improving

    site_root = tmp_path / "example.edu"
    _ready_index(site_root)
    provider = MockWebSearchProvider(
        [WebSearchResult(title="Admission Requirements", url="https://example.edu/admission", snippet="Student admission requirements and deadlines.")]
    )
    monkeypatch.setattr(self_improving, "query_mcp_wiki_index", lambda *args, **kwargs: _low_confidence_result())
    monkeypatch.setattr(
        self_improving,
        "launch_ingest_job",
        lambda site_root, url, question="": {"id": "job-1", "status": "queued", "url": url},
    )

    result = self_improving.answer_question(site_root, "unknown admission rule", provider=provider)

    assert result["status"] == "ok"
    assert result["provenance"] == "web_provisional"
    assert result["ingestion_job"]["status"] == "queued"
    assert provider.calls == ["unknown admission rule"]


def test_answer_question_missing_provider_returns_unavailable(tmp_path: Path, monkeypatch) -> None:
    import src.scrape_planner.wiki.self_improving as self_improving

    site_root = tmp_path / "example.edu"
    _ready_index(site_root)
    monkeypatch.setattr(self_improving, "query_mcp_wiki_index", lambda *args, **kwargs: _low_confidence_result())

    result = self_improving.answer_question(site_root, "unknown admission rule")

    assert result["status"] == "web_search_unavailable"
    assert result["provenance"] == "none"


def test_quality_gate_rejection_is_recorded(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.self_improving import assess_candidate_source, record_rejection

    site_root = tmp_path / "example.edu"
    _ready_index(site_root)
    candidate = {"title": "Alumni Giving", "url": "https://example.edu/giving", "snippet": "Donor advancement update."}
    decision = assess_candidate_source(candidate, site_root=site_root).to_dict()
    record_rejection(site_root, candidate, decision)

    assert decision["accepted"] is False
    assert (site_root / "indexes" / "self_improving_rejections.jsonl").exists()


def test_loop_guard_suppresses_repeated_web_search_until_ttl(tmp_path: Path, monkeypatch) -> None:
    import src.scrape_planner.wiki.self_improving as self_improving

    site_root = tmp_path / "example.edu"
    _ready_index(site_root)
    provider = MockWebSearchProvider(
        [WebSearchResult(title="Admission Requirements", url="https://example.edu/admission", snippet="Student admission requirements and deadlines.")]
    )
    monkeypatch.setattr(self_improving, "query_mcp_wiki_index", lambda *args, **kwargs: _low_confidence_result())
    monkeypatch.setattr(
        self_improving,
        "launch_ingest_job",
        lambda site_root, url, question="": {"id": "job-1", "status": "queued", "url": url},
    )

    first = self_improving.answer_question(site_root, "unknown admission rule", provider=provider, now=100.0)
    second = self_improving.answer_question(site_root, "unknown admission rule", provider=provider, now=120.0)
    third = self_improving.answer_question(site_root, "unknown admission rule", provider=provider, now=100.0 + self_improving.LOOP_GUARD_TTL_SECONDS + 1)

    assert first["provenance"] == "web_provisional"
    assert second["metadata"]["loop_guard"] == "pending"
    assert len(provider.calls) == 2
    assert third["provenance"] == "web_provisional"


def test_web_search_without_provider_has_no_side_effects(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("RAG_WEB_SEARCH_PROVIDER", raising=False)

    before = set(tmp_path.iterdir())
    result = web_search("admissions deadline")
    after = set(tmp_path.iterdir())

    assert result["status"] == "web_search_unavailable"
    assert before == after


def test_confidence_decision_stable_across_reranker_modes() -> None:
    from src.scrape_planner.wiki.confidence import assess_confidence

    fused = {
        "status": "ok",
        "evidence": [
            {"source_kind": "wiki", "source_ids": ["raw1"], "scores": {"combined": 4.0, "model_rerank": 0.0}},
            {"scores": {"combined": 1.0, "model_rerank": 0.0}},
        ],
    }
    reranked = {
        "status": "ok",
        "evidence": [
            {
                "source_kind": "wiki",
                "source_ids": ["raw1"],
                "scores": {"combined": 0.92, "model_rerank": 0.9},
                "ranking_reasons": ["openrouter_rerank"],
            },
            {"scores": {"combined": 0.2, "model_rerank": 0.1}},
        ],
    }
    fused_decision = assess_confidence(fused)
    reranked_decision = assess_confidence(reranked)
    assert fused_decision["scoring_mode"] == "fused"
    assert reranked_decision["scoring_mode"] == "reranked"
    assert fused_decision["confident"] is True
    assert reranked_decision["confident"] is True


def test_citation_excludes_wiki_self_reference_only() -> None:
    from src.scrape_planner.wiki.confidence import assess_confidence

    result = {
        "status": "ok",
        "evidence": [
            {
                "source_kind": "wiki",
                "source_id": "wiki/pages/admissions.md",
                "source_ids": [],
                "scores": {"combined": 5.0},
            }
        ],
    }
    decision = assess_confidence(result)
    assert decision["citation_present"] is False
    assert decision["confident"] is False


def test_successful_ingest_clears_guard(tmp_path: Path, monkeypatch) -> None:
    import src.scrape_planner.wiki.self_improving as self_improving

    site_root = tmp_path / "example.edu"
    _ready_index(site_root)
    provider = MockWebSearchProvider(
        [WebSearchResult(title="Admission Requirements", url="https://example.edu/admission", snippet="Student admission requirements and deadlines.")]
    )
    monkeypatch.setattr(self_improving, "query_mcp_wiki_index", lambda *args, **kwargs: _low_confidence_result())
    monkeypatch.setattr(
        self_improving,
        "launch_ingest_job",
        lambda site_root, url, question="": {"id": "job-1", "status": "queued", "url": url, "status_file": str(site_root / "indexes" / "ingest_jobs" / "job-1.json")},
    )
    self_improving.answer_question(site_root, "unknown admission rule", provider=provider, now=100.0)
    status_path = site_root / "indexes" / "ingest_jobs" / "job-1.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps({"id": "job-1", "status": "succeeded", "source_ids": ["web_1"]}), encoding="utf-8")
    monkeypatch.setattr(self_improving, "query_mcp_wiki_index", lambda *args, **kwargs: _confident_result())
    after = self_improving.answer_question(site_root, "unknown admission rule", provider=provider, now=110.0)
    assert after["provenance"] == "wiki"
    assert "loop_guard" not in after.get("metadata", {})


def test_failed_ingest_clears_guard_and_surfaces_failure(tmp_path: Path, monkeypatch) -> None:
    import src.scrape_planner.wiki.self_improving as self_improving

    site_root = tmp_path / "example.edu"
    _ready_index(site_root)
    provider = MockWebSearchProvider(
        [WebSearchResult(title="Admission Requirements", url="https://example.edu/admission", snippet="Student admission requirements and deadlines.")]
    )
    monkeypatch.setattr(self_improving, "query_mcp_wiki_index", lambda *args, **kwargs: _low_confidence_result())
    monkeypatch.setattr(
        self_improving,
        "launch_ingest_job",
        lambda site_root, url, question="": {"id": "job-1", "status": "queued", "url": url, "status_file": str(site_root / "indexes" / "ingest_jobs" / "job-1.json")},
    )
    self_improving.answer_question(site_root, "unknown admission rule", provider=provider, now=100.0)
    status_path = site_root / "indexes" / "ingest_jobs" / "job-1.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps({"id": "job-1", "status": "failed", "reason": "quality_gate_failed"}), encoding="utf-8")
    failed = self_improving.answer_question(site_root, "unknown admission rule", provider=provider, now=110.0)
    assert failed["status"] == "ingest_failed"
    guard = self_improving.LoopGuard(site_root)
    assert guard.get("unknown admission rule", now=120.0) is None


def test_ingest_retries_are_bounded(tmp_path: Path) -> None:
    import src.scrape_planner.wiki.self_improving as self_improving

    site_root = tmp_path / "example.edu"
    guard = self_improving.LoopGuard(site_root)
    key = self_improving._query_key("retry question")
    guard._write(
        {
            key: {
                "created_at": 1.0,
                "payload": {"status": "ok"},
                "job_id": "job-x",
                "retry_count": self_improving.MAX_INGEST_RETRIES,
            }
        }
    )
    assert guard.retry_exhausted("retry question") is True


def test_atomic_documents_swap_under_concurrent_build(tmp_path: Path, monkeypatch) -> None:
    import src.scrape_planner.wiki.llm_wiki_index as llm_wiki_index
    from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index

    layout = ensure_site_layout(tmp_path, "example.edu")
    site_root = layout.site_root
    raw_dir = site_root / "raw_sources" / "web"
    raw_dir.mkdir(parents=True, exist_ok=True)
    wiki_dir = site_root / "wiki" / "pages"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "web_a.md").write_text("# Admissions\n\nApply by February 1 for graduate admission.\n", encoding="utf-8")
    (wiki_dir / "admissions.md").write_text("---\ntitle: Admissions\nsource_ids:\n  - web_a\n---\n\nApply by February 1.\n", encoding="utf-8")
    registry = site_root / "raw_sources" / "registry.jsonl"
    registry.write_text(
        json.dumps(
            {
                "source_id": "web_a",
                "source_kind": "web",
                "title": "Admissions",
                "original_url": "https://example.edu/admissions",
                "markdown_path": "raw_sources/web/web_a.md",
                "metadata_path": "",
                "checksum": "abc",
                "parser": "manual",
                "status": "ready",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_wiki_index, "embed_text", lambda text, config: [0.1, 0.2, 0.3] + [0.0] * 765)

    errors: list[str] = []

    def worker(label: str) -> None:
        try:
            build_llm_wiki_index(site_root, now=f"2026-06-01T12:00:{label}")
        except Exception as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=worker, args=(str(i),)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    docs_path = site_root / "indexes" / "llm_wiki_documents.jsonl"
    lines = [line for line in docs_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for line in lines:
        json.loads(line)


def test_ssrf_and_untrusted_domain_rejection(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.ingest_safety import assess_trusted_domain, assess_url_safety, safe_fetch

    site_root = tmp_path / "example.edu"
    _ready_index(site_root)
    assert assess_url_safety("http://example.edu/page").allowed is False
    assert assess_url_safety("https://127.0.0.1/page").allowed is False
    assert assess_trusted_domain("https://other.edu/admission", site_root=site_root).allowed is False
    try:
        safe_fetch("https://127.0.0.1/private", site_root=site_root)
        assert False, "expected SSRF rejection"
    except ValueError as exc:
        assert "blocked" in str(exc)


def test_student_policy_rejections(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.self_improving import assess_candidate_source

    site_root = tmp_path / "example.edu"
    _ready_index(site_root)
    cases = [
        ("Donor Giving", "https://example.edu/giving", "Donor advancement annual report"),
        ("Campus News", "https://example.edu/news/today", "Latest magazine press release"),
        ("Staff Bio", "https://example.edu/staff/bio", "Biography profile of director"),
        ("Trustees", "https://example.edu/admin/trustees", "Board of trustees cabinet"),
        ("Random Page", "https://example.edu/random", "Generic institutional overview"),
    ]
    for title, url, snippet in cases:
        decision = assess_candidate_source({"title": title, "url": url, "snippet": snippet}, site_root=site_root)
        assert decision.accepted is False, (title, decision.reasons)


def test_degraded_build_disables_vector_leg(tmp_path: Path, monkeypatch) -> None:
    import src.scrape_planner.wiki.llm_wiki_index as llm_wiki_index
    from src.scrape_planner.wiki.llm_wiki_index import EMBEDDING_SPACE_DENSE, EMBEDDING_SPACE_HASH, _cosine_similarity, build_llm_wiki_index, query_llm_wiki_index

    site_root = ensure_site_layout(tmp_path, "example.edu").site_root
    raw_dir = site_root / "raw_sources" / "web"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "web_a.md").write_text("# Admissions\n\nApply by February 1 for graduate admission.\n", encoding="utf-8")
    (site_root / "raw_sources" / "registry.jsonl").write_text(
        json.dumps(
            {
                "source_id": "web_a",
                "source_kind": "web",
                "title": "Admissions",
                "original_url": "https://example.edu/admissions",
                "markdown_path": "raw_sources/web/web_a.md",
                "metadata_path": "",
                "checksum": "abc",
                "parser": "manual",
                "status": "ready",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_wiki_index, "embed_text", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    report = build_llm_wiki_index(site_root, now="2026-06-01T12:00:00+00:00")
    assert report["embedding_degraded"] is True
    assert report["vector_leg_enabled"] is False
    response = query_llm_wiki_index(site_root, "admissions deadline")
    assert response["metadata"]["vector_leg_enabled"] is False
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0], left_space=EMBEDDING_SPACE_DENSE, right_space=EMBEDDING_SPACE_HASH) == 0.0


def test_idempotent_reingest_short_circuits(tmp_path: Path) -> None:
    from src.scrape_planner.scrape.manual_url_pipeline import run_manual_url_pipeline
    from src.scrape_planner.sources.source_registry import build_source_row, write_registry_rows

    layout = ensure_site_layout(tmp_path, "example.edu")
    row = build_source_row(
        source_kind="web",
        title="Admissions",
        original_url="https://example.edu/admissions",
        original_path="",
        markdown_path="raw_sources/web/web_a.md",
        metadata_path="",
        checksum="deadbeef",
        parser="manual",
        status="ready",
    )
    write_registry_rows(layout.registry_path, [row])
    fetch_calls: list[str] = []

    result = run_manual_url_pipeline(
        site_root=layout.site_root,
        site_url="https://example.edu",
        url="https://example.edu/admissions",
        fetcher=lambda url: fetch_calls.append(url) or SimpleNamespace(status_code=200, headers={}, text="unused"),
    )
    assert result["status"] == "unchanged"
    assert fetch_calls == []


def test_cold_start_suppresses_web_search(tmp_path: Path, monkeypatch) -> None:
    import src.scrape_planner.wiki.self_improving as self_improving

    site_root = tmp_path / "example.edu"
    provider = MockWebSearchProvider([WebSearchResult(title="Admission", url="https://example.edu/admission", snippet="Student admission requirements.")])
    monkeypatch.setattr(self_improving, "query_mcp_wiki_index", lambda *args, **kwargs: _low_confidence_result())
    result = self_improving.answer_question(site_root, "unknown admission rule", provider=provider)
    assert result["status"] == "index_not_ready"
    assert provider.calls == []


def test_web_search_budget_enforced(tmp_path: Path, monkeypatch) -> None:
    import src.scrape_planner.wiki.self_improving as self_improving

    site_root = tmp_path / "example.edu"
    _ready_index(site_root)
    monkeypatch.setenv("RAG_WEB_SEARCH_BUDGET", "1")
    provider = MockWebSearchProvider(
        [WebSearchResult(title="Admission Requirements", url="https://example.edu/admission", snippet="Student admission requirements and deadlines.")]
    )
    monkeypatch.setattr(self_improving, "query_mcp_wiki_index", lambda *args, **kwargs: _low_confidence_result())
    monkeypatch.setattr(
        self_improving,
        "launch_ingest_job",
        lambda site_root, url, question="": {"id": "job-1", "status": "queued", "url": url},
    )
    first = self_improving.answer_question(site_root, "question one", provider=provider, now=1000.0)
    second = self_improving.answer_question(site_root, "question two", provider=provider, now=1001.0)
    assert first["provenance"] == "web_provisional"
    assert second["status"] == "web_search_budget_exhausted"


def test_web_search_provider_precedence(monkeypatch) -> None:
    monkeypatch.setenv("RAG_WEB_SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-key")
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-key")
    provider = provider_from_env()
    assert provider is not None
    assert provider.__class__.__name__ == "TavilyWebSearchProvider"

    monkeypatch.delenv("RAG_WEB_SEARCH_PROVIDER", raising=False)
    provider = provider_from_env()
    assert provider is not None
    assert provider.__class__.__name__ == "BraveWebSearchProvider"


def test_accepted_ingest_ledger_and_rollback(tmp_path: Path, monkeypatch) -> None:
    from src.scrape_planner.wiki.self_improving import record_accepted_ingest, rollback_auto_ingest

    site_root = tmp_path / "example.edu"
    _ready_index(site_root)
    record_accepted_ingest(site_root, question="q", job={"id": "job-9", "status_file": ""}, url="https://example.edu/a", source_ids=["web_a"])
    ledger = (site_root / "indexes" / "self_improving_accepted.jsonl").read_text(encoding="utf-8")
    assert "job-9" in ledger
    status_path = site_root / "indexes" / "ingest_jobs" / "job-9.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps({"id": "job-9", "status": "succeeded", "source_ids": ["web_a"]}), encoding="utf-8")
    registry = site_root / "raw_sources" / "registry.jsonl"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        json.dumps({"source_id": "web_a", "status": "ready", "original_url": "https://example.edu/a"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("src.scrape_planner.wiki.llm_wiki_builder.build_wiki", lambda *args, **kwargs: {"status": "complete"})
    monkeypatch.setattr("src.scrape_planner.wiki.llm_wiki_index.build_llm_wiki_index", lambda *args, **kwargs: {"status": "ready"})
    result = rollback_auto_ingest(site_root, "job-9")
    assert result["status"] == "rolled_back"
    rows = [json.loads(line) for line in registry.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["status"] == "quarantined"
