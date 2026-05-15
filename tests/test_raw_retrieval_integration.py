from __future__ import annotations

from pathlib import Path

from scrape_planner.raw_retrieval import QueryRequest, build_raw_index, query_raw_index
from scripts.raw_retrieval_proof import run_fixture_proof


def _src(path: Path, source_id: str, url: str) -> dict[str, str]:
    return {"source_id": source_id, "url": url, "path": str(path)}


def test_missing_index_status(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    a.write_text("alpha", encoding="utf-8")
    resp = query_raw_index(tmp_path / "missing", [_src(a, "A", "https://a")], QueryRequest(query="alpha"))
    assert resp.status == "missing_index"
    assert resp.reason == "index_artifacts_missing"


def test_stale_index_status(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    a.write_text("alpha", encoding="utf-8")
    index_root = tmp_path / "index"
    build_raw_index(index_root, [_src(a, "A", "https://a")])

    b = tmp_path / "b.md"
    b.write_text("beta", encoding="utf-8")
    resp = query_raw_index(index_root, [_src(a, "A", "https://a"), _src(b, "B", "https://b")], QueryRequest(query="alpha"))
    assert resp.status == "stale_index"
    assert resp.reason == "source_fingerprint_mismatch"


def test_bounded_query_path_no_full_scan_fallback(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    a.write_text(("termx " * 200) + "\n" + ("termy " * 200), encoding="utf-8")
    index_root = tmp_path / "index"
    build_raw_index(index_root, [_src(a, "A", "https://a")], chunk_chars=100, overlap=20)

    resp = query_raw_index(index_root, [_src(a, "A", "https://a")], QueryRequest(query="termx termy", max_results=1, max_candidates=1, snippet_chars=20))
    assert resp.status == "ok"
    assert len(resp.evidence) == 1
    assert resp.metadata["bounded"] is True


def test_index_first_fixture_proof_command(tmp_path: Path) -> None:
    fixtures_root = tmp_path / "fixtures"
    index_root = tmp_path / "index"

    result = run_fixture_proof(fixtures_root, index_root)

    assert result["query"]["status"] == "ok"
    assert result["query"]["bounded"] is True
    assert result["query"]["evidence_count"] >= 1
    assert (index_root / "raw_index_manifest.json").exists()
    assert (index_root / "raw_postings.json").exists()
    assert (index_root / "raw_chunks.jsonl").exists()
