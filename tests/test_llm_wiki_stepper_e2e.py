from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_fixture_stepper_runs_normalize_wiki_index_rerank_and_mcp(tmp_path: Path, monkeypatch) -> None:
    from scripts.validate_llm_wiki_stepper import (
        FIXED_NOW,
        create_fixture_site,
        run_fixture_validation,
    )

    monkeypatch.setenv("WIKI_SKIP_PI", "1")
    monkeypatch.setenv("LLM_WIKI_ALLOW_HASH_FALLBACK", "1")
    site_root = create_fixture_site(tmp_path / "fixture-site")
    report = run_fixture_validation(site_root, now=FIXED_NOW)

    assert report["status"] == "passed"
    assert report["fixture"]["source_counts"] == {"web": 1, "pdf": 1, "excel": 1}
    assert report["fixture"]["normalization"]["counts"]["ready"] == 3
    assert report["fixture"]["wiki"]["pages_created"] >= 3
    assert report["fixture"]["index"]["raw_index_count"] >= 3
    assert report["fixture"]["index"]["wiki_index_count"] >= 3

    query = report["fixture"]["query"]
    assert query["status"] == "ok"
    assert query["evidence"][0]["source_kind"] == "wiki"
    assert "wiki_synthesis_boost" in query["evidence"][0]["ranking_reasons"]
    assert any(row["source_kind"] == "pdf" for row in query["evidence"])
    assert any(row["source_kind"] == "excel" for row in query["evidence"])

    mcp = report["fixture"]["mcp"]
    assert mcp["direct"]["index_info"]["ready"] is True
    assert mcp["direct"]["query_wiki"]["ok"] is True
    assert mcp["stdio"]["initialize"]["result"]["serverInfo"]["name"] == "llm-wiki-query"
    assert mcp["stdio"]["query_wiki"]["ok"] is True

    index_text = (site_root / "wiki" / "index.md").read_text(encoding="utf-8")
    assert "[Admissions](pages/admissions.md)" in index_text
    assert "[Finance](pages/finance.md)" in index_text
    assert "[Programs](pages/programs.md)" in index_text


def test_validation_command_writes_fixture_and_smu_proof_report(tmp_path: Path, monkeypatch) -> None:
    from scripts.validate_llm_wiki_stepper import run_validation

    monkeypatch.setenv("WIKI_SKIP_PI", "1")
    monkeypatch.setenv("LLM_WIKI_ALLOW_HASH_FALLBACK", "1")
    output_root = tmp_path / "validation"
    report = run_validation(
        output_root=output_root,
        repo_root=Path.cwd(),
        include_smu=True,
        smu_limit=2,
    )

    report_path = Path(report["report_path"])
    persisted = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["status"] == "passed"
    assert report_path.exists()
    assert persisted["fixture"]["status"] == "passed"
    assert persisted["smu"]["status"] in {"passed", "skipped"}
    assert "manual_prompts" in persisted["smu"]
    assert persisted["smu"]["manual_prompts"] == 0
    assert persisted["smu"]["mode"] in {"bounded_real_artifact_proof", "no_local_artifacts"}


def test_validation_script_runs_as_direct_operator_command(tmp_path: Path) -> None:
    output_root = tmp_path / "cli-validation"
    report_path = tmp_path / "cli-report.json"
    relative_output_root = Path(os.path.relpath(output_root, Path.cwd()))
    relative_report_path = Path(os.path.relpath(report_path, Path.cwd()))

    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_llm_wiki_stepper.py",
            "--output-root",
            str(relative_output_root),
            "--report-path",
            str(relative_report_path),
            "--skip-smu",
        ],
        cwd=Path.cwd(),
        env={**os.environ, "WIKI_SKIP_PI": "1", "LLM_WIKI_ALLOW_HASH_FALLBACK": "1"},
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert report_path.exists()
