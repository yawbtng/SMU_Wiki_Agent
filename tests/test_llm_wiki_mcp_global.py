from __future__ import annotations

from pathlib import Path

import mcp_servers.llm_wiki_mcp as server


def write_site(data_root: Path, site_id: str, *, name: str = "") -> Path:
    root = data_root / "sites" / site_id
    (root / "wiki" / "pages").mkdir(parents=True)
    (root / "indexes").mkdir(parents=True)
    (root / "wiki" / "pages" / "catalog.md").write_text("# Catalog\n", encoding="utf-8")
    (root / "indexes" / "llm_wiki_documents.jsonl").write_text("{}\n", encoding="utf-8")
    if name:
        (root / "discovery_summary.json").write_text(f'{{"site_url":"https://{site_id}","name":"{name}"}}', encoding="utf-8")
    return root


def test_global_mcp_lists_universities(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    write_site(data_root, "smu.edu", name="Southern Methodist University")
    monkeypatch.setattr(server, "DATA_ROOT", data_root)
    monkeypatch.setattr(server, "SITE_ROOT", data_root)

    payload = server.list_universities()

    assert payload["mode"] == "global"
    assert payload["ready_count"] == 1
    assert payload["universities"][0]["site_id"] == "smu.edu"
    assert payload["universities"][0]["mcp_enabled"] is True


def test_global_mcp_query_uses_explicit_site_id(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    site_root = write_site(data_root, "smu.edu", name="Southern Methodist University")
    monkeypatch.setattr(server, "DATA_ROOT", data_root)
    monkeypatch.setattr(server, "SITE_ROOT", data_root)
    seen: dict[str, Path] = {}

    def fake_query(root: Path, question: str, max_evidence: int = 5) -> dict:
        seen["root"] = root
        return {"status": "ok", "query": question, "evidence": [], "metadata": {}}

    monkeypatch.setattr(server, "query_mcp_wiki_index", fake_query)

    payload = server.query_wiki("deadline", site_id="smu.edu")

    assert payload["ok"] is True
    assert payload["site_id"] == "smu.edu"
    assert seen["root"] == site_root.resolve()


def test_global_mcp_returns_candidates_for_ambiguous_hint(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    write_site(data_root, "alpha.edu", name="Example University")
    write_site(data_root, "beta.edu", name="Example University")
    monkeypatch.setattr(server, "DATA_ROOT", data_root)
    monkeypatch.setattr(server, "SITE_ROOT", data_root)

    payload = server.query_wiki("tuition", university_hint="Example")

    assert payload["ok"] is False
    assert payload["error"] == "ambiguous_university"
    assert len(payload["candidates"]) == 2
