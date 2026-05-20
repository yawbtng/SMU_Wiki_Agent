import json
from pathlib import Path

from src.scrape_planner.retrieval_recovery import (
    ANSWERABLE,
    NEEDS_WEB_RECOVERY,
    UNANSWERABLE_AFTER_RECOVERY,
    answer_with_recovery,
    retrieve_from_corpus,
)


def _write_run(tmp_path: Path, pages: list[tuple[str, str]]) -> Path:
    run_root = tmp_path / "sites" / "www.smu.edu" / "run-1"
    markdown_dir = run_root / "markdown"
    markdown_dir.mkdir(parents=True)
    manifest = []
    for idx, (url, text) in enumerate(pages, start=1):
        path = markdown_dir / f"page-{idx}.md"
        path.write_text(text, encoding="utf-8")
        manifest.append({"url": url, "status": "success", "markdown_path": str(path)})
    (run_root / "scrape_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return run_root


def test_retrieve_from_corpus_answers_only_when_evidence_is_explicit(tmp_path: Path):
    run_root = _write_run(
        tmp_path,
        [
            (
                "https://www.smu.edu/lyle/departments/ece/ms-network-engineering",
                "# Network Engineering\nThe Network Engineering program is offered by the ECE department.",
            ),
            (
                "https://www.smu.edu/lyle/departments/ece/people",
                "# ECE People\nDr. Ada Smith is the Director of Network Engineering.",
            ),
        ],
    )

    result = retrieve_from_corpus("Who is the Director of Network Engineering?", run_root)

    assert result.state == ANSWERABLE
    assert result.evidence
    assert "Director of Network Engineering" in result.evidence[0].snippet


def test_retrieve_from_corpus_marks_missing_answer_for_web_recovery(tmp_path: Path):
    run_root = _write_run(
        tmp_path,
        [
            (
                "https://www.smu.edu/lyle/departments/ece/ms-network-engineering",
                "# Network Engineering\nThis page describes curriculum and admissions requirements.",
            )
        ],
    )

    result = retrieve_from_corpus("Who is the Director of Network Engineering?", run_root)

    assert result.state == NEEDS_WEB_RECOVERY
    assert result.evidence == []
    assert result.closest


def test_answer_with_recovery_searches_scrapes_indexes_and_retries(monkeypatch, tmp_path: Path):
    run_root = _write_run(
        tmp_path,
        [
            (
                "https://www.smu.edu/lyle/departments/ece/ms-network-engineering",
                "# Network Engineering\nThis page describes curriculum and admissions requirements.",
            )
        ],
    )

    monkeypatch.setattr(
        "src.scrape_planner.retrieval_recovery.tavily_search",
        lambda question, tavily_api_key, include_domains, max_results: (
            [{"url": "https://www.smu.edu/lyle/departments/ece/people", "score": 0.9}],
            12,
        ),
    )
    monkeypatch.setattr(
        "src.scrape_planner.retrieval_recovery.tavily_extract_urls",
        lambda urls, tavily_api_key: (
            [
                {
                    "url": urls[0],
                    "score": 0.9,
                    "raw_content": "# ECE People\nDr. Ada Smith is the Director of Network Engineering.",
                }
            ],
            15,
        ),
    )

    result = answer_with_recovery(
        "Who is the Director of Network Engineering?",
        run_root,
        tavily_api_key="test-key",
        include_domains=["www.smu.edu"],
    )

    assert result.state == ANSWERABLE
    assert result.recovery["searched"] is True
    assert result.recovery["indexed_pages"] == 1
    assert "Ada Smith" in result.evidence[0].snippet
    manifest = json.loads((run_root / "scrape_manifest.json").read_text(encoding="utf-8"))
    recovered_rows = [
        row
        for row in manifest
        if row.get("url") == "https://www.smu.edu/lyle/departments/ece/people"
    ]
    assert len(recovered_rows) == 1
    recovered = recovered_rows[0]
    assert recovered["fetch_mode"] == "tavily_search_recovery"
    assert recovered["status"] == "success"
    recovered_markdown = Path(recovered["markdown_path"])
    assert recovered_markdown.exists()
    assert "Dr. Ada Smith is the Director of Network Engineering." in recovered_markdown.read_text(encoding="utf-8")


def test_answer_with_recovery_reports_unanswerable_after_recovery(monkeypatch, tmp_path: Path):
    run_root = _write_run(
        tmp_path,
        [
            (
                "https://www.smu.edu/lyle/departments/ece/ms-network-engineering",
                "# Network Engineering\nThis page describes curriculum and admissions requirements.",
            )
        ],
    )

    monkeypatch.setattr(
        "src.scrape_planner.retrieval_recovery.tavily_search",
        lambda question, tavily_api_key, include_domains, max_results: (
            [{"url": "https://www.smu.edu/lyle/departments/ece/contact", "score": 0.8}],
            10,
        ),
    )
    monkeypatch.setattr(
        "src.scrape_planner.retrieval_recovery.tavily_extract_urls",
        lambda urls, tavily_api_key: (
            [{"url": urls[0], "score": 0.8, "raw_content": "# Contact\nEmail the ECE department for details."}],
            11,
        ),
    )

    result = answer_with_recovery(
        "Who is the Director of Network Engineering?",
        run_root,
        tavily_api_key="test-key",
        include_domains=["www.smu.edu"],
    )

    assert result.state == UNANSWERABLE_AFTER_RECOVERY
    assert result.recovery["indexed_pages"] == 1
    assert result.evidence == []
