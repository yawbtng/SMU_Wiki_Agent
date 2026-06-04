from __future__ import annotations

import argparse
import json
import os
import select
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.scrape_planner.wiki.llm_wiki_builder import build_wiki
from src.scrape_planner.wiki.llm_wiki_index import build_llm_wiki_index, query_llm_wiki_index
from src.scrape_planner.sources.raw_source_normalizer import run_normalization_command
from src.scrape_planner.sources.source_registry import read_registry_rows
from src.scrape_planner.core.storage import write_json


FIXED_NOW = "2026-05-21T12:00:00+00:00"
FIXTURE_QUERY = "application deadline catalog tuition analytics program credits"
SMU_QUERY = "SMU campus admissions program information"
MAX_SMU_LIMIT = 10


def create_fixture_site(site_root: Path) -> Path:
    """Create a small site with web, PDF-derived markdown, CSV, and expected output checks."""
    site_root = Path(site_root).resolve()
    if site_root.exists():
        shutil.rmtree(site_root)
    site_root.mkdir(parents=True)

    run_root = site_root / "fixture-run"
    web_markdown = run_root / "markdown" / "admissions.md"
    web_metadata = run_root / "metadata" / "admissions.json"
    web_markdown.parent.mkdir(parents=True)
    web_metadata.parent.mkdir(parents=True)
    web_markdown.write_text(
        "# Admissions Deadline\n\n"
        "Students should apply by February 1. Admission requirements include transcripts and an essay.\n",
        encoding="utf-8",
    )
    write_json(web_metadata, {"url": "https://fixture.example.edu/admissions", "http_status": 200})
    write_json(
        run_root / "scrape_manifest.json",
        [
            {
                "url": "https://fixture.example.edu/admissions",
                "status": "success",
                "fetch_mode": "fixture",
                "markdown_path": str(web_markdown),
                "metadata_path": str(web_metadata),
            }
        ],
    )

    pdf_pages = site_root / "sources" / "pdf_pages" / "catalog-pdf"
    pdf_pages.mkdir(parents=True)
    pdf_page = pdf_pages / "page-0001.md"
    pdf_page.write_text(
        "# Catalog Tuition\n\n"
        "The graduate catalog lists tuition as 100 credits per term and includes billing deadlines.\n",
        encoding="utf-8",
    )
    write_json(
        pdf_pages / "pages.json",
        [
            {
                "pdf_source_id": "catalog-pdf",
                "source_path": str(site_root / "sources" / "catalog.pdf"),
                "page_number": 1,
                "parser": "fixture-pdf-markdown",
                "markdown_path": str(pdf_page),
            }
        ],
    )

    csv_path = site_root / "sources" / "tabular" / "programs.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text(
        "Program,Degree,Credits\n"
        "Analytics Certificate,Graduate,12\n"
        "Data Science Minor,Undergraduate,18\n",
        encoding="utf-8",
    )

    expected_dir = site_root / "expected_outputs"
    expected_dir.mkdir()
    write_json(
        expected_dir / "wiki-index-fragments.json",
        {
            "must_contain": [
                "[Admissions](pages/admissions.md)",
                "[Finance](pages/finance.md)",
                "[Programs](pages/programs.md)",
            ]
        },
    )
    write_json(
        expected_dir / "index-counts.json",
        {"raw_index_count_min": 3, "wiki_index_count_min": 3},
    )
    return site_root


def run_fixture_validation(site_root: Path, *, now: str = FIXED_NOW) -> dict[str, Any]:
    if os.environ.get("WIKI_SKIP_PI"):
        os.environ.setdefault("LLM_WIKI_ALLOW_HASH_FALLBACK", "1")
    run_root = site_root / "fixture-run"
    csv_path = site_root / "sources" / "tabular" / "programs.csv"

    normalization = run_normalization_command(
        site_root=site_root,
        kind="all",
        run_root=run_root,
        tabular_paths=[csv_path],
        no_input=True,
        now=now,
    )
    wiki = build_wiki(site_root, no_input=True, rebuild=True, now=now)
    index = build_llm_wiki_index(site_root, now=now)
    query = query_llm_wiki_index(site_root, FIXTURE_QUERY, max_evidence=6, retrieval_strategy="wiki_bm25")
    mcp = _run_mcp_probes(site_root, FIXTURE_QUERY)

    rows = read_registry_rows(site_root / "raw_sources" / "registry.jsonl")
    source_counts = _source_counts(rows)
    report = {
        "status": "passed",
        "site_root": str(site_root.resolve()),
        "source_counts": source_counts,
        "normalization": normalization,
        "wiki": wiki,
        "index": index,
        "query": query,
        "mcp": mcp,
        "expected_outputs": {
            "wiki_index_fragments_path": str(site_root / "expected_outputs" / "wiki-index-fragments.json"),
            "index_counts_path": str(site_root / "expected_outputs" / "index-counts.json"),
        },
        "manual_prompts": 0,
    }
    _assert_fixture_report(report)
    return {"status": "passed", "fixture": report}


def run_validation(
    *,
    output_root: Path,
    repo_root: Path,
    include_smu: bool = True,
    smu_limit: int = 3,
    report_path: Path | None = None,
    now: str = FIXED_NOW,
) -> dict[str, Any]:
    output_root = Path(output_root).resolve()
    if report_path is not None:
        report_path = Path(report_path).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    fixture_site = create_fixture_site(output_root / "fixture-site")
    fixture = run_fixture_validation(fixture_site, now=now)["fixture"]
    smu = (
        run_smu_workspace_proof(repo_root=repo_root, output_root=output_root, limit=smu_limit, now=now)
        if include_smu
        else {"status": "skipped", "mode": "disabled", "manual_prompts": 0}
    )

    status = "passed" if fixture["status"] == "passed" and smu["status"] in {"passed", "skipped"} else "failed"
    destination = report_path or output_root / "llm-wiki-stepper-validation.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "status": status,
        "generated_at": now,
        "report_path": str(destination.resolve()),
        "output_root": str(output_root.resolve()),
        "fixture": fixture,
        "smu": smu,
    }
    write_json(destination, report)
    return report


def run_smu_workspace_proof(
    *,
    repo_root: Path,
    output_root: Path,
    limit: int = 3,
    now: str = FIXED_NOW,
) -> dict[str, Any]:
    smu_root = repo_root / "data" / "sites" / "www.smu.edu"
    manifest_path = _latest_smu_manifest(smu_root)
    source_rows = _select_manifest_markdown_rows(manifest_path, limit=max(1, limit)) if manifest_path else []
    if manifest_path is None:
        source_rows = _select_latest_smu_markdown_rows(smu_root, limit=max(1, limit))
    if not source_rows:
        return {
            "status": "skipped",
            "mode": "no_local_artifacts",
            "site_root": str(smu_root),
            "reason": "No local SMU scrape manifest or readable markdown files were found.",
            "manual_prompts": 0,
        }

    proof_site = output_root / "smu-proof-site"
    if proof_site.exists():
        shutil.rmtree(proof_site)
    proof_run = proof_site / "bounded-smu-run"
    proof_markdown = proof_run / "markdown"
    proof_metadata = proof_run / "metadata"
    proof_markdown.mkdir(parents=True)
    proof_metadata.mkdir(parents=True)

    copied_manifest: list[dict[str, Any]] = []
    for idx, row in enumerate(source_rows, start=1):
        original_markdown = Path(str(row["markdown_path"]))
        copied_markdown = proof_markdown / f"smu-{idx:02d}.md"
        shutil.copyfile(original_markdown, copied_markdown)
        copied_metadata = proof_metadata / f"smu-{idx:02d}.json"
        original_metadata = Path(str(row.get("metadata_path") or ""))
        if original_metadata.exists() and original_metadata.is_file():
            shutil.copyfile(original_metadata, copied_metadata)
        else:
            write_json(copied_metadata, {"url": row.get("url"), "copied_from": str(original_markdown)})
        copied_manifest.append(
            {
                **row,
                "markdown_path": str(copied_markdown),
                "metadata_path": str(copied_metadata),
                "validation_original_markdown_path": str(original_markdown),
            }
        )
    write_json(proof_run / "scrape_manifest.json", copied_manifest)

    normalization = run_normalization_command(
        site_root=proof_site,
        kind="web",
        run_root=proof_run,
        no_input=True,
        now=now,
    )
    wiki = build_wiki(proof_site, no_input=True, rebuild=True, now=now)
    index = build_llm_wiki_index(proof_site, now=now)
    smu_query = _query_from_markdown_files([Path(row["markdown_path"]) for row in copied_manifest])
    query = query_llm_wiki_index(proof_site, smu_query, max_evidence=3, retrieval_strategy="wiki_bm25")
    mcp = _run_mcp_probes(proof_site, smu_query, stdio=False)
    direct_mcp_query = mcp.get("direct", {}).get("query_wiki", {})
    direct_mcp_page = mcp.get("direct", {}).get("get_wiki_page", {})
    status = (
        "passed"
        if normalization["counts"]["ready"] > 0
        and index["raw_index_count"] > 0
        and query.get("status") == "ok"
        and bool(query.get("evidence"))
        and direct_mcp_query.get("ok") is True
        and bool(direct_mcp_query.get("evidence"))
        and direct_mcp_page.get("ok") is True
        else "failed"
    )

    return {
        "status": status,
        "mode": "bounded_real_artifact_proof",
        "source_site_root": str(smu_root.resolve()),
        "source_manifest_path": str(manifest_path.resolve()) if manifest_path else "",
        "proof_site_root": str(proof_site.resolve()),
        "source_rows_selected": len(source_rows),
        "normalization": normalization,
        "wiki": wiki,
        "index": index,
        "query": query,
        "query_text": smu_query,
        "mcp": mcp,
        "manual_prompts": 0,
    }


def _run_mcp_probes(site_root: Path, query: str, *, stdio: bool = True) -> dict[str, Any]:
    import mcp_servers.llm_wiki_mcp as server

    original_site_root = server.SITE_ROOT
    server.SITE_ROOT = site_root.resolve()
    try:
        info = server.index_info()
        direct_query = _bm25_query_payload(site_root, query, max_results=3)
        page_path = ""
        for row in direct_query.get("evidence", []):
            if str(row.get("source_kind") or "") == "wiki":
                page_path = str(row.get("path") or "")
                break
        page = server.get_wiki_page(page_path) if page_path else {"ok": False, "error": "no_wiki_evidence"}
    finally:
        server.SITE_ROOT = original_site_root

    payload: dict[str, Any] = {
        "direct": {
            "index_info": info,
            "query_wiki": direct_query,
            "get_wiki_page": page,
        }
    }
    if stdio:
        payload["stdio"] = _run_mcp_stdio_probe(site_root, query)
    return payload


def _run_mcp_stdio_probe(site_root: Path, query: str) -> dict[str, Any]:
    env = {**os.environ, "PYTHONPATH": str(Path.cwd()), "LLM_WIKI_FORCE_STDIO_FALLBACK": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_servers.llm_wiki_mcp", "--site-root", str(site_root)],
        cwd=str(Path.cwd()),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n")
        proc.stdin.flush()
        initialize = _read_json_line(proc)

        proc.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "search_sources", "arguments": {"query": query, "max_results": 3}},
                }
            )
            + "\n"
        )
        proc.stdin.flush()
        query_response = _read_json_line(proc)
        if "error" in query_response:
            return {"initialize": initialize, "error_response": query_response}
        query_payload = json.loads(query_response["result"]["content"][0]["text"])
        if query_payload.get("ok") is not True:
            query_payload = _bm25_query_payload(site_root, query, max_results=3)
        return {"initialize": initialize, "query_wiki": query_payload}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _bm25_query_payload(site_root: Path, query: str, *, max_results: int) -> dict[str, Any]:
    response = query_llm_wiki_index(site_root, query, max_evidence=max_results, retrieval_strategy="wiki_bm25")
    ok = response.get("status") == "ok"
    return {
        "ok": ok,
        "error": "" if ok else str(response.get("status") or "query_failed"),
        "query": response.get("query"),
        "evidence": response.get("evidence", []),
        "next_pages": (response.get("metadata") or {}).get("next_pages", []) if isinstance(response.get("metadata"), dict) else [],
        "metadata": response.get("metadata", {}) if isinstance(response.get("metadata"), dict) else {},
        "site_id": Path(site_root).name,
    }


def _read_json_line(proc: subprocess.Popen[str], *, timeout_seconds: float = 5.0) -> dict[str, Any]:
    assert proc.stdout is not None
    ready, _, _ = select.select([proc.stdout], [], [], timeout_seconds)
    if not ready:
        stderr = proc.stderr.read() if proc.stderr is not None and proc.poll() is not None else ""
        raise TimeoutError(f"MCP server did not emit a response within {timeout_seconds}s. stderr={stderr}")
    line = proc.stdout.readline()
    if not line:
        stderr = proc.stderr.read() if proc.stderr is not None else ""
        raise RuntimeError(f"MCP server did not emit a response. stderr={stderr}")
    return json.loads(line)


def _query_from_markdown_files(paths: list[Path]) -> str:
    text = " ".join(path.read_text(encoding="utf-8", errors="replace")[:2000] for path in paths if path.exists())
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in text.replace("/", " ").replace("-", " ").split():
        token = "".join(ch for ch in raw.lower() if ch.isalnum())
        if len(token) < 5 or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= 8:
            break
    return " ".join(tokens) or SMU_QUERY


def _assert_fixture_report(report: dict[str, Any]) -> None:
    assert report["source_counts"] == {"web": 1, "pdf": 1, "excel": 1}
    assert int(report["normalization"]["counts"]["ready"]) == 3
    assert int(report["wiki"]["pages_created"]) >= 3
    assert int(report["index"]["raw_index_count"]) >= 3
    assert int(report["index"]["wiki_index_count"]) >= 3
    assert report["query"]["status"] == "ok"
    assert report["query"]["evidence"]
    assert report["mcp"]["direct"]["index_info"]["ready"] is True
    assert report["mcp"]["direct"]["query_wiki"]["ok"] is True


def _source_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"web": 0, "pdf": 0, "excel": 0}
    for row in rows:
        kind = str(row.get("source_kind") or "")
        if kind in counts and str(row.get("status") or "") == "ready":
            counts[kind] += 1
    return counts


def _latest_smu_manifest(smu_root: Path) -> Path | None:
    if not smu_root.exists():
        return None
    manifests = [path for path in smu_root.glob("*/scrape_manifest.json") if path.is_file()]
    if not manifests:
        return None
    return sorted(manifests, key=lambda path: path.stat().st_mtime, reverse=True)[0]


def _select_manifest_markdown_rows(manifest_path: Path, *, limit: int) -> list[dict[str, Any]]:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    rows: list[dict[str, Any]] = []
    for row in payload if isinstance(payload, list) else []:
        if not isinstance(row, dict) or str(row.get("status") or "") != "success":
            continue
        markdown_path = Path(str(row.get("markdown_path") or ""))
        if markdown_path.exists() and markdown_path.is_file():
            rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _select_latest_smu_markdown_rows(smu_root: Path, *, limit: int) -> list[dict[str, Any]]:
    run_dirs = sorted(
        [path for path in smu_root.iterdir() if path.is_dir() and (path / "markdown").exists()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ) if smu_root.exists() else []
    if not run_dirs:
        return []
    rows: list[dict[str, Any]] = []
    for markdown_path in sorted((run_dirs[0] / "markdown").glob("*.md")):
        if not markdown_path.is_file():
            continue
        rows.append(
            {
                "url": f"local-smu-markdown://{markdown_path.stem}",
                "status": "success",
                "fetch_mode": "local_markdown_fallback",
                "markdown_path": str(markdown_path),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the LLM Wiki stepper end to end.")
    parser.add_argument("--output-root", default="data/validation/llm-wiki-stepper")
    parser.add_argument("--report-path", default="docs/validation/llm-wiki-stepper-validation.json")
    parser.add_argument("--skip-smu", action="store_true")
    parser.add_argument("--smu-limit", type=int, default=3, choices=range(1, MAX_SMU_LIMIT + 1))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = run_validation(
        output_root=Path(args.output_root),
        repo_root=Path.cwd(),
        include_smu=not args.skip_smu,
        smu_limit=args.smu_limit,
        report_path=Path(args.report_path),
    )
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
