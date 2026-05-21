from __future__ import annotations

import json
from pathlib import Path

from src.scrape_planner.markdown_graph import (
    answer_context,
    build_graph,
    get_page_markdown,
    get_unit_pages,
    graph_stats,
    list_units,
    load_edges,
    load_page_nodes,
    load_tags,
    run_graphify_enrichment_for_unit,
    search_pages,
    shortest_path,
    tag_page_units,
    traverse_from_page,
)


def _write_fixture_run(tmp_path: Path) -> tuple[Path, str, str]:
    site_id = "www.smu.edu"
    run_id = "fixture-run"
    run_root = tmp_path / "data" / "sites" / site_id / run_id
    md_dir = run_root / "markdown"
    meta_dir = run_root / "metadata"
    md_dir.mkdir(parents=True)
    meta_dir.mkdir(parents=True)

    pages = {
        "admission": {
            "url": "https://www.smu.edu/admission/apply",
            "markdown": "# Undergraduate Admission\nApply to SMU and review admitted student next steps. See [international students](/isss/i-20).\n",
        },
        "isss": {
            "url": "https://www.smu.edu/isss/i-20",
            "markdown": "# International Student I-20\nInternational students need an I-20 before the F-1 visa appointment.\n",
        },
        "aid": {
            "url": "https://www.smu.edu/bursar/tuition-and-fees",
            "markdown": "# Tuition and Financial Aid Deadlines\nReview tuition, fees, payment deadlines, scholarships, and financial aid.\n",
        },
        "registrar": {
            "url": "https://www.smu.edu/registrar/academic-calendar",
            "markdown": "# Registrar Academic Calendar\nThe registrar publishes enrollment, grades, and academic calendar deadlines.\n",
        },
        "president": {
            "url": "https://www.smu.edu/academic-ceremonies/featured-speakers",
            "markdown": "# 2025-2026 Featured speakers\n\n### Jay Hartzell\n\n**President, SMU**\n\nJay C. Hartzell proudly serves as the 11th president of SMU.\n",
        },
        "network": {
            "url": "https://www.smu.edu/lyle/departments/ece/ms-network-engineering",
            "markdown": "# Network Engineering\n\nThis professional program focuses on the engineering, operation, and management of networks.\n",
        },
    }
    manifest = []
    for stem, row in pages.items():
        md_path = md_dir / f"{stem}.md"
        meta_path = meta_dir / f"{stem}.json"
        md_path.write_text(row["markdown"], encoding="utf-8")
        meta_path.write_text(json.dumps({"url": row["url"], "http_status": 200}), encoding="utf-8")
        manifest.append(
            {
                "url": row["url"],
                "status": "success",
                "http_status": 200,
                "markdown_path": str(md_path),
                "metadata_path": str(meta_path),
                "raw_html_path": str(run_root / "raw_html" / f"{stem}.html"),
            }
        )
    (run_root / "scrape_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return run_root, site_id, run_id


def test_page_nodes_created_for_every_raw_markdown_file(tmp_path: Path) -> None:
    run_root, site_id, run_id = _write_fixture_run(tmp_path)
    graph = build_graph(run_root, site_id, run_id)

    assert graph["counts"]["raw_markdown_files"] == 6
    assert graph["counts"]["page_nodes"] == 6
    page_nodes = load_page_nodes(run_root)
    assert {page["relative_path"] for page in page_nodes} == {
        "markdown/admission.md",
        "markdown/isss.md",
        "markdown/aid.md",
        "markdown/registrar.md",
        "markdown/president.md",
        "markdown/network.md",
    }
    assert all(page["content_hash"] for page in page_nodes)


def test_url_title_and_content_unit_tagging() -> None:
    page = {
        "id": "page:isss",
        "source_url": "https://www.smu.edu/isss/i-20",
        "title": "International Student I-20",
        "headings": ["International Student I-20"],
    }

    tags = tag_page_units(page, "International students need an I-20 for F-1 visa status.")

    assert any(tag["unit_key"] == "isss_international" for tag in tags)
    reasons = [reason for tag in tags for reason in tag["reasons"]]
    assert any("url_path matched" in reason or "title matched" in reason for reason in reasons)


def test_edge_creation_and_artifact_roundtrip(tmp_path: Path) -> None:
    run_root, site_id, run_id = _write_fixture_run(tmp_path)
    graph = build_graph(run_root, site_id, run_id)

    stats = graph_stats(run_root)
    edges = load_edges(run_root)
    tags = load_tags(run_root)

    assert stats["counts_match"] is True
    assert stats["page_nodes"] == 6
    assert any(edge["type"] == "unit_has_page" for edge in edges)
    assert any(edge["type"] == "page_links_to_page" for edge in edges)
    assert any(edge["type"] == "source_url" for edge in edges)
    assert tags
    assert graph["counts"]["dynamic_profile_units"] > 0
    assert any(edge["type"] == "unit_has_child" for edge in edges)
    assert any(str(tag["unit_key"]).startswith("root-lyle") for tag in tags)
    assert (run_root / "knowledge_graph" / "graph.json").exists()
    assert (run_root / "knowledge_graph" / "graph_profile.json").exists()
    assert (run_root / "knowledge_graph" / "graph_report.md").exists()


def test_graph_query_functions_return_markdown_evidence(tmp_path: Path) -> None:
    run_root, site_id, run_id = _write_fixture_run(tmp_path)
    build_graph(run_root, site_id, run_id)

    units = list_units(run_root)
    assert any(unit["unit_key"] == "isss_international" and unit["page_count"] >= 1 for unit in units)
    isss_pages = get_unit_pages(run_root, "isss_international", limit=10)
    assert any("i-20" in page["source_url"] for page in isss_pages)
    isss_alias_pages = get_unit_pages(run_root, "isss", limit=10)
    assert [page["id"] for page in isss_alias_pages] == [page["id"] for page in isss_pages]

    results = search_pages(run_root, "what do international students need for I-20?", limit=5)
    assert results[0]["page_id"] == "page:isss"
    scoped_results = search_pages(run_root, "what do international students need for I-20?", unit="isss", limit=5)
    assert scoped_results[0]["page_id"] == "page:isss"
    president_results = search_pages(run_root, "who is the president of SMU?", limit=5)
    assert president_results[0]["page_id"] == "page:president"
    missing_role_results = search_pages(run_root, "who is the director of Network Engineering?", limit=5)
    assert missing_role_results == []
    context = answer_context(run_root, "what do international students need for I-20?", budget_chars=3000)
    assert context["evidence"]
    assert "I-20" in context["evidence"][0]["markdown_excerpt"]
    assert "https://www.smu.edu/isss/i-20" in context["evidence"][0]["source_url"]

    markdown = get_page_markdown(run_root, "page:isss")
    assert "International Student I-20" in markdown
    traversal = traverse_from_page(run_root, "page:admission", depth=1)
    assert any(edge["target"] == "page:isss" for edge in traversal["edges"])
    path = shortest_path(run_root, "page:admission", "page:isss")
    assert path["found"] is True


def test_graphify_not_required_for_deterministic_graph(tmp_path: Path) -> None:
    run_root, site_id, run_id = _write_fixture_run(tmp_path)
    assert not (run_root / "graphify-raw").exists()

    graph = build_graph(run_root, site_id, run_id)

    assert graph["counts"]["page_nodes"] == 6
    assert graph_stats(run_root)["status"] == "ready"


def test_bounded_graphify_enrichment_labels_unit_concepts(tmp_path: Path) -> None:
    run_root, site_id, run_id = _write_fixture_run(tmp_path)
    build_graph(run_root, site_id, run_id)

    result = run_graphify_enrichment_for_unit(run_root, "isss_international")

    assert result["status"] == "success"
    assert result["unit_key"] == "isss_international"
    enrichment_path = Path(result["path"])
    assert enrichment_path.exists()
    payload = json.loads(enrichment_path.read_text(encoding="utf-8"))
    assert payload["communities"]
    assert all("ISSS / international students:" in item["label"] for item in payload["communities"])
    assert any(edge["type"] == "semantic_keyword" for edge in load_edges(run_root))
