from __future__ import annotations

from pathlib import Path

from scrape_planner.raw_retrieval import QueryRequest, build_raw_index, query_raw_index


def _src(path: Path, source_id: str, url: str) -> dict[str, str]:
    return {"source_id": source_id, "url": url, "path": str(path)}


def test_build_and_query_bounded(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("alpha beta alpha gamma\n" * 50, encoding="utf-8")
    b.write_text("beta delta epsilon\n" * 30, encoding="utf-8")

    index_root = tmp_path / "index"
    build = build_raw_index(index_root, [_src(a, "A", "https://a"), _src(b, "B", "https://b")], chunk_chars=120, overlap=20)
    assert build["status"] == "ok"
    assert (index_root / "raw_index_manifest.json").exists()

    resp = query_raw_index(
        index_root,
        [_src(a, "A", "https://a"), _src(b, "B", "https://b")],
        QueryRequest(query="alpha beta", max_results=1, max_candidates=1, snippet_chars=40),
    )
    assert resp.status == "ok"
    assert len(resp.evidence) == 1
    row = resp.evidence[0]
    assert row.source_id
    assert row.url
    assert row.path
    assert row.chunk_id
    assert row.score >= 0
    assert len(row.snippet) <= 43
    assert resp.metadata["bounded"] is True
    assert "candidates_truncated" in resp.metadata


def test_query_empty_and_zero_bounds(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    a.write_text("hello world", encoding="utf-8")
    index_root = tmp_path / "index"
    build_raw_index(index_root, [_src(a, "A", "https://a")])

    r1 = query_raw_index(index_root, [_src(a, "A", "https://a")], QueryRequest(query="", max_results=5))
    assert r1.status == "ok"
    assert r1.evidence == []

    r2 = query_raw_index(index_root, [_src(a, "A", "https://a")], QueryRequest(query="hello", max_results=0))
    assert r2.status == "ok"
    assert r2.evidence == []
