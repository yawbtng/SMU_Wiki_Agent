from __future__ import annotations

from pathlib import Path

from src.scrape_planner.webapp.embeddings import (
    append_embedding_log,
    embedding_job_status_payload,
    read_embedding_log_tail,
    start_embedding_job_state,
)


def test_read_embedding_log_tail_returns_recent_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "job.log"
    log_path.write_text("line1\nline2\nline3\n", encoding="utf-8")
    assert read_embedding_log_tail(log_path, lines=2) == ["line2", "line3"]


def test_embedding_job_status_payload_includes_log_tail(tmp_path: Path) -> None:
    site = tmp_path / "sites" / "demo.edu"
    indexes = site / "indexes" / "reports"
    indexes.mkdir(parents=True)
    state = start_embedding_job_state(site, "demo.edu", trigger="manual", changed_document_count=3, status="running")
    append_embedding_log(Path(state["log_path"]), "Scanning raw sources and wiki pages…")
    payload = embedding_job_status_payload("demo.edu", site)
    assert payload["phase"] == "building_index"
    assert "Scanning raw sources" in "\n".join(payload["log_tail"])
