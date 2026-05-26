from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

from src.scrape_planner.source_registry import (
    build_source_row,
    checksum_text,
    read_registry_rows,
    write_registry_rows,
)


NOW = "2026-05-21T10:00:00+00:00"
LATER = "2026-05-21T11:00:00+00:00"


def _write_ready_source(
    site_root: Path,
    *,
    source_id: str,
    title: str,
    source_kind: str = "web",
    body: str,
    wiki_status: str = "pending",
    checksum: str | None = None,
) -> dict:
    raw_dir = site_root / "raw_sources" / source_kind
    raw_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = raw_dir / f"{source_id}.md"
    markdown_path.write_text(body, encoding="utf-8")
    metadata_path = raw_dir / f"{source_id}.metadata.json"
    metadata_path.write_text(json.dumps({"title": title}), encoding="utf-8")
    return build_source_row(
        source_id=source_id,
        source_kind=source_kind,
        title=title,
        original_url=f"https://example.edu/{source_id}",
        original_path="",
        markdown_path=str(markdown_path.relative_to(site_root)),
        metadata_path=str(metadata_path.relative_to(site_root)),
        checksum=checksum or checksum_text(body),
        parser="fixture",
        status="ready",
        now=NOW,
        wiki_status=wiki_status,
    )


def test_wiki_builder_noninteractive_writes_pages_index_log_review_report_and_updates_registry(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_builder import build_wiki

    site_root = tmp_path / "site"
    registry_path = site_root / "raw_sources" / "registry.jsonl"
    admissions = _write_ready_source(
        site_root,
        source_id="web_admissions",
        title="Admissions Requirements",
        body="# Admissions Requirements\n\nApply by February 1. Admissions requirements include transcripts.\n",
    )
    finance = _write_ready_source(
        site_root,
        source_id="web_tuition",
        title="Tuition And Fees",
        body="# Tuition And Fees\n\nTuition is listed as 100. Conflicting tuition language says tuition is 200.\n",
    )
    already_done = _write_ready_source(
        site_root,
        source_id="web_done",
        title="Already Integrated",
        body="# Already Integrated\n\nThis should not be processed in incremental mode.\n",
        wiki_status="integrated",
    )
    write_registry_rows(registry_path, [admissions, finance, already_done])

    report = build_wiki(site_root, no_input=True, now=NOW)

    admissions_page = site_root / "wiki" / "pages" / "admissions.md"
    finance_page = site_root / "wiki" / "pages" / "finance.md"
    index = (site_root / "wiki" / "index.md").read_text(encoding="utf-8")
    log = (site_root / "wiki" / "log.md").read_text(encoding="utf-8")
    review_queue = (site_root / "wiki" / "review_queue.md").read_text(encoding="utf-8")
    report_payload = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))

    assert report["status"] == "complete"
    assert report["sources_considered"] == 2
    assert admissions_page.exists()
    assert finance_page.exists()
    page_text = admissions_page.read_text(encoding="utf-8")
    assert page_text.startswith("---\n")
    assert "page_path: wiki/pages/admissions.md" in page_text
    assert f"page_checksum: {checksum_text(page_text.split('---', 2)[2].lstrip())}" in page_text
    assert "source_ids:\n  - web_admissions" in page_text
    assert "source_paths:\n  - raw_sources/web/web_admissions.md" in page_text
    assert "source_count: 1" in page_text
    assert "tags:\n  - admissions" in page_text
    assert "updated_at: 2026-05-21T10:00:00+00:00" in page_text
    assert "## Sources" in page_text
    assert "- `web_admissions` - raw_sources/web/web_admissions.md" in page_text
    assert "## Admissions" in index
    assert "[Admissions](pages/admissions.md) - Admissions Requirements. Sources: 1." in index
    assert "## Finance" in index
    assert "Sources: 1." in index
    assert "| 2026-05-21T10:00:00+00:00 | ingest | sources_considered=2" in log
    assert "| 2026-05-21T10:00:00+00:00 | page-create | pages/admissions.md | sources=1 |" in log
    assert "| 2026-05-21T10:00:00+00:00 | rebuild | status=complete" in log
    assert "web_tuition" in review_queue
    assert "conflicting" in review_queue.lower()
    assert report_payload["review_queue_count"] == 1
    rows = {row["source_id"]: row for row in read_registry_rows(registry_path)}
    assert rows["web_admissions"]["wiki_status"] == "integrated"
    assert rows["web_admissions"]["wiki_page_paths"] == ["wiki/pages/admissions.md"]
    assert rows["web_done"]["wiki_page_paths"] == []


def test_wiki_builder_writes_routed_contract_source_notes_and_metadata(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_builder import build_wiki

    site_root = tmp_path / "site"
    registry_path = site_root / "raw_sources" / "registry.jsonl"
    program = _write_ready_source(
        site_root,
        source_id="web_program",
        title="Computer Science Graduate Program",
        body="# Computer Science Graduate Program\n\nGraduate applicants apply by March 1. Tuition and faculty research labs are listed.",
    )
    write_registry_rows(registry_path, [program])

    report = build_wiki(site_root, no_input=True, now=NOW)

    page = (site_root / "wiki" / "pages" / "programs.md").read_text(encoding="utf-8")
    assert (site_root / "wiki" / "routing" / "audience.md").exists()
    assert (site_root / "wiki" / "routing" / "intent.md").exists()
    assert (site_root / "wiki" / "routing" / "topics.md").exists()
    assert (site_root / "wiki" / "source-notes" / "index.md").exists()
    assert (site_root / "wiki" / "programs" / "index.md").exists()
    assert "## Fast Answer" in page
    assert "## Who This Applies To" in page
    assert "## Source Notes" not in page
    assert "audiences:\n  - applicant" in page
    assert "intents:\n  - apply" in page
    assert "canonical_owner: wiki/pages/programs.md" in page
    assert "Computer Science Graduate Program" in (site_root / "wiki" / "source-notes" / "programs.md").read_text(encoding="utf-8")
    assert "smu" not in page.lower()
    assert "wiki/routing/audience.md" in report["required_markdown_paths"]


def test_wiki_builder_report_preserves_tmux_session(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_builder import build_wiki

    site_root = tmp_path / "site"
    registry_path = site_root / "raw_sources" / "registry.jsonl"
    admissions = _write_ready_source(
        site_root,
        source_id="web_admissions",
        title="Admissions Requirements",
        body="# Admissions Requirements\n\nApply by February 1.\n",
    )
    write_registry_rows(registry_path, [admissions])

    report = build_wiki(site_root, no_input=True, now=NOW, tmux_session="wiki-site-20260522-120000")

    assert report["tmux_session"] == "wiki-site-20260522-120000"
    payload = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
    assert payload["tmux_session"] == "wiki-site-20260522-120000"


def test_wiki_builder_resume_processes_pending_rows_after_prior_report(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_builder import build_wiki

    site_root = tmp_path / "site"
    registry_path = site_root / "raw_sources" / "registry.jsonl"
    first = _write_ready_source(
        site_root,
        source_id="web_programs",
        title="Programs",
        body="# Programs\n\nGraduate programs include data science.\n",
        wiki_status="integrated",
    )
    second = _write_ready_source(
        site_root,
        source_id="pdf_catalog",
        title="Catalog Admissions",
        source_kind="pdf",
        body="# Catalog Admissions\n\nAdmission requirements include a transcript.\n",
    )
    first["wiki_page_paths"] = ["wiki/pages/programs.md"]
    write_registry_rows(registry_path, [first, second])
    (site_root / "wiki" / "reports").mkdir(parents=True, exist_ok=True)
    (site_root / "wiki" / "reports" / "wiki-build-prior.json").write_text(
        json.dumps({"status": "failed", "processed_source_ids": ["web_programs"]}),
        encoding="utf-8",
    )

    report = build_wiki(site_root, no_input=True, resume=True, now=LATER)

    assert report["status"] == "complete"
    assert report["sources_considered"] == 1
    assert (site_root / "wiki" / "pages" / "admissions.md").exists()
    rows = {row["source_id"]: row for row in read_registry_rows(registry_path)}
    assert rows["pdf_catalog"]["wiki_status"] == "integrated"
    assert rows["web_programs"]["wiki_status"] == "integrated"


def test_wiki_builder_incremental_noop_preserves_existing_wiki_outputs(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_builder import build_wiki

    site_root = tmp_path / "site"
    registry_path = site_root / "raw_sources" / "registry.jsonl"
    row = _write_ready_source(
        site_root,
        source_id="web_admissions",
        title="Admissions",
        body="# Admissions\n\nAdmissions requirements include transcripts.\n",
        wiki_status="integrated",
    )
    row["wiki_page_paths"] = ["wiki/pages/admissions.md"]
    write_registry_rows(registry_path, [row])
    wiki = site_root / "wiki"
    pages = wiki / "pages"
    pages.mkdir(parents=True)
    (pages / "admissions.md").write_text("# Existing Admissions\n\nKeep this page.\n", encoding="utf-8")
    (wiki / "index.md").write_text("# Existing Index\n\nKeep this index.\n", encoding="utf-8")
    (wiki / "review_queue.md").write_text("- [ ] `web_admissions` Existing review item.\n", encoding="utf-8")

    report = build_wiki(site_root, no_input=True, now=LATER)

    assert report["status"] == "complete"
    assert report["job_status"] == "complete"
    assert report["no_op"] is True
    assert report["sources_considered"] == 0
    assert report["skipped_source_ids"] == ["web_admissions"]
    assert (pages / "admissions.md").read_text(encoding="utf-8") == "# Existing Admissions\n\nKeep this page.\n"
    assert (wiki / "index.md").read_text(encoding="utf-8") == "# Existing Index\n\nKeep this index.\n"
    assert (wiki / "review_queue.md").read_text(encoding="utf-8") == "- [ ] `web_admissions` Existing review item.\n"
    assert "no-op" in (wiki / "log.md").read_text(encoding="utf-8")


def test_wiki_builder_resume_retries_explicit_ids_only_when_processable(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_builder import build_wiki

    site_root = tmp_path / "site"
    registry_path = site_root / "raw_sources" / "registry.jsonl"
    unchanged_failed = _write_ready_source(
        site_root,
        source_id="web_unchanged_failed",
        title="Unchanged Failed Admissions",
        body="# Unchanged Failed Admissions\n\nAdmissions requirements are unchanged.\n",
        wiki_status="integrated",
    )
    changed_pending = _write_ready_source(
        site_root,
        source_id="web_changed_pending",
        title="Changed Pending Tuition",
        body="# Changed Pending Tuition\n\nTuition and fees changed.\n",
        wiki_status="integrated",
        checksum="old-checksum",
    )
    not_integrated_failed = _write_ready_source(
        site_root,
        source_id="web_not_integrated_failed",
        title="Failed Programs",
        body="# Failed Programs\n\nProgram details should retry.\n",
        wiki_status="pending",
    )
    skipped = _write_ready_source(
        site_root,
        source_id="web_skipped",
        title="Skipped Programs",
        body="# Skipped Programs\n\nProgram details unchanged.\n",
        wiki_status="integrated",
    )
    for row in (unchanged_failed, changed_pending, not_integrated_failed, skipped):
        row["wiki_page_paths"] = ["wiki/pages/old.md"]
    write_registry_rows(registry_path, [unchanged_failed, changed_pending, not_integrated_failed, skipped])
    reports = site_root / "wiki" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "wiki-build-latest.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "processed_source_ids": ["web_skipped"],
                "failed_source_ids": ["web_unchanged_failed", "web_not_integrated_failed"],
                "pending_source_ids": ["web_changed_pending"],
            }
        ),
        encoding="utf-8",
    )

    report = build_wiki(site_root, no_input=True, resume=True, now=LATER)

    assert report["resume_source_ids"] == ["web_changed_pending", "web_not_integrated_failed"]
    assert report["processed_source_ids"] == ["web_changed_pending", "web_not_integrated_failed"]
    assert report["sources_considered"] == 2
    rows = {row["source_id"]: row for row in read_registry_rows(registry_path)}
    assert rows["web_unchanged_failed"]["wiki_page_paths"] == ["wiki/pages/old.md"]
    assert rows["web_changed_pending"]["wiki_page_paths"] == ["wiki/pages/finance.md"]
    assert rows["web_not_integrated_failed"]["wiki_page_paths"] == ["wiki/pages/programs.md"]
    assert rows["web_skipped"]["wiki_page_paths"] == ["wiki/pages/old.md"]


def test_wiki_builder_resume_fallback_skips_integrated_unchanged_sources(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_builder import build_wiki

    site_root = tmp_path / "site"
    registry_path = site_root / "raw_sources" / "registry.jsonl"
    integrated = _write_ready_source(
        site_root,
        source_id="web_integrated",
        title="Integrated Admissions",
        body="# Integrated Admissions\n\nAlready handled admissions content.\n",
        wiki_status="integrated",
    )
    pending = _write_ready_source(
        site_root,
        source_id="web_pending",
        title="Pending Tuition",
        body="# Pending Tuition\n\nTuition and fees changed.\n",
    )
    integrated["wiki_page_paths"] = ["wiki/pages/admissions.md"]
    write_registry_rows(registry_path, [integrated, pending])
    reports = site_root / "wiki" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "wiki-build-latest.json").write_text(
        json.dumps({"status": "failed", "processed_source_ids": []}),
        encoding="utf-8",
    )

    report = build_wiki(site_root, no_input=True, resume=True, now=LATER)

    assert report["resume_source_ids"] == ["web_pending"]
    assert report["processed_source_ids"] == ["web_pending"]
    assert report["sources_considered"] == 1
    rows = {row["source_id"]: row for row in read_registry_rows(registry_path)}
    assert rows["web_integrated"]["wiki_page_paths"] == ["wiki/pages/admissions.md"]
    assert rows["web_pending"]["wiki_status"] == "integrated"


def test_wiki_builder_missing_markdown_is_reviewed_and_not_integrated(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_builder import build_wiki

    site_root = tmp_path / "site"
    registry_path = site_root / "raw_sources" / "registry.jsonl"
    missing = _write_ready_source(
        site_root,
        source_id="web_missing",
        title="Missing Source",
        body="# Missing Source\n\nThis file will be removed.\n",
    )
    (site_root / missing["markdown_path"]).unlink()
    write_registry_rows(registry_path, [missing])

    report = build_wiki(site_root, no_input=True, now=LATER)

    assert report["sources_considered"] == 1
    assert report["integrated_sources"] == 0
    assert report["failed_source_ids"] == ["web_missing"]
    assert not (site_root / "wiki" / "pages" / "general.md").exists()
    review_queue = (site_root / "wiki" / "review_queue.md").read_text(encoding="utf-8")
    assert "web_missing" in review_queue
    assert "missing" in review_queue.lower()
    rows = {row["source_id"]: row for row in read_registry_rows(registry_path)}
    assert rows["web_missing"]["wiki_status"] != "integrated"
    assert rows["web_missing"]["wiki_page_paths"] == []


def test_wiki_builder_rebuild_removes_stale_generated_pages(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_builder import build_wiki

    site_root = tmp_path / "site"
    registry_path = site_root / "raw_sources" / "registry.jsonl"
    row = _write_ready_source(
        site_root,
        source_id="web_admissions",
        title="Admissions",
        body="# Admissions\n\nAdmissions requirements include transcripts.\n",
        wiki_status="integrated",
    )
    row["wiki_page_paths"] = ["wiki/pages/admissions.md"]
    write_registry_rows(registry_path, [row])
    wiki = site_root / "wiki"
    pages = wiki / "pages"
    pages.mkdir(parents=True)
    (pages / "admissions.md").write_text("# Old Admissions\n", encoding="utf-8")
    (pages / "stale.md").write_text("# Stale Generated Page\n", encoding="utf-8")
    nested = wiki / "archive" / "old"
    nested.mkdir(parents=True)
    (nested / "stale-nested.md").write_text("# Stale Nested Generated Page\n", encoding="utf-8")
    (wiki / "index.md").write_text("# Existing Index\n", encoding="utf-8")
    (wiki / "log.md").write_text("# Wiki Log\n\n", encoding="utf-8")
    (wiki / "review_queue.md").write_text("- [ ] `old` Existing review item.\n", encoding="utf-8")
    (wiki / "reports").mkdir(parents=True)
    (wiki / "reports" / "keep.json").write_text("{}", encoding="utf-8")
    (wiki / "reports" / "keep.md").write_text("# Maintained Report\n", encoding="utf-8")

    report = build_wiki(site_root, no_input=True, rebuild=True, now=LATER)

    assert report["rebuild"] is True
    assert (pages / "admissions.md").exists()
    assert not (pages / "stale.md").exists()
    assert not (nested / "stale-nested.md").exists()
    assert (wiki / "index.md").exists()
    assert (wiki / "log.md").exists()
    assert (wiki / "review_queue.md").exists()
    assert (wiki / "reports" / "keep.json").exists()
    assert (wiki / "reports" / "keep.md").exists()


def test_wiki_lint_reports_orphans_missing_citations_stale_checksums_review_items_and_missing_index(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_builder import lint_wiki

    site_root = tmp_path / "site"
    registry_path = site_root / "raw_sources" / "registry.jsonl"
    row = _write_ready_source(
        site_root,
        source_id="web_admissions",
        title="Admissions",
        body="# Admissions\n\nApply now.\n",
        checksum="stale-checksum",
    )
    row["wiki_status"] = "integrated"
    row["wiki_page_paths"] = ["wiki/pages/admissions.md"]
    write_registry_rows(registry_path, [row])
    pages = site_root / "wiki" / "pages"
    pages.mkdir(parents=True)
    (pages / "admissions.md").write_text("# Admissions\n\nNo frontmatter or sources.\n", encoding="utf-8")
    (pages / "orphan.md").write_text(
        "---\ntitle: Orphan\nsource_ids:\n  - missing\nsource_paths:\n  - raw_sources/web/missing.md\nsource_count: 1\ntags:\n  - orphan\nupdated_at: 2026-05-21T00:00:00+00:00\n---\n\n## Sources\n- `missing` - raw_sources/web/missing.md\n",
        encoding="utf-8",
    )
    (site_root / "wiki" / "index.md").write_text("# Wiki Index\n\n", encoding="utf-8")
    (site_root / "wiki" / "review_queue.md").write_text(
        "# Wiki Review Queue\n\n"
        "- [ ] `web_admissions` Admissions (raw_sources/web/web_admissions.md): contradiction between catalog and page.\n"
        "- [ ] source_id=pdf_catalog reason=needs-review line from source\n",
        encoding="utf-8",
    )

    report = lint_wiki(site_root, now=NOW)

    assert "wiki/pages/orphan.md" in report["orphan_pages"]
    assert "wiki/pages/admissions.md" in report["missing_citations"]
    assert "web_admissions" in report["stale_source_checksums"]
    assert report["review_queue_count"] == 2
    assert report["review_items"][0]["source_id"] == "web_admissions"
    assert report["review_items"][0]["line"] == 3
    assert report["review_items"][0]["reason"] == "contradiction between catalog and page."
    assert report["review_items"][0]["type"] == "contradiction"
    assert report["review_items"][1]["source_id"] == "pdf_catalog"
    assert report["review_items"][1]["type"] == "review"
    assert "wiki/pages/admissions.md" in report["missing_index_entries"]
    assert Path(report["report_path"]).exists()
    assert "| 2026-05-21T10:00:00+00:00 | lint |" in (site_root / "wiki" / "log.md").read_text(encoding="utf-8")


def test_wiki_launcher_uses_tmux_with_no_input_paths_and_resume(tmp_path: Path, monkeypatch) -> None:
    from src.scrape_planner.llm_wiki_builder import launch_wiki_builder

    class FakeRunner:
        def __init__(self) -> None:
            self.calls = []

        def session_exists(self, name: str) -> bool:
            return any(existing_name == name for existing_name, _command, _workdir in self.calls)

        def start(self, name: str, command: str, workdir: str):
            self.calls.append((name, command, workdir))
            return {"ok": True, "command": "tmux shell command"}

    runner = FakeRunner()
    site_root = tmp_path / "site with spaces"
    monkeypatch.chdir(tmp_path)

    result = launch_wiki_builder(
        site_root,
        session_name="wiki-test",
        runner=runner,
        python_executable="/usr/bin/python3",
        resume=True,
    )

    [(name, command, workdir)] = runner.calls
    assert result["ok"] is True
    assert result["session_name"] == "wiki-test"
    assert name == "wiki-test"
    repo_root = Path(__file__).resolve().parents[1]
    assert workdir == str(repo_root)
    assert "/usr/bin/python3 -m src.scrape_planner.llm_wiki_builder" in command
    split_command = shlex.split(command)
    assert split_command[split_command.index("--site-root") + 1] == str(site_root)
    assert split_command[split_command.index("--registry-path") + 1] == str(site_root / "raw_sources" / "registry.jsonl")
    assert split_command[split_command.index("--wiki-dir") + 1] == str(site_root / "wiki")
    assert "'" in command
    assert "--no-input" in command
    assert "--resume" in command
    assert str(site_root / "wiki" / "reports" / "wiki-build-latest.json") in command
    launch_report = json.loads((site_root / "wiki" / "reports" / "wiki-build-latest.json").read_text(encoding="utf-8"))
    assert launch_report["status"] == "running"
    assert launch_report["job_status"] == "running"
    assert launch_report["tmux_session"] == "wiki-test"
    assert launch_report["report_path"] == str(site_root / "wiki" / "reports" / "wiki-build-latest.json")


def test_wiki_builder_cli_refuses_build_without_no_input(tmp_path: Path) -> None:
    site_root = tmp_path / "site"
    registry_path = site_root / "raw_sources" / "registry.jsonl"
    row = _write_ready_source(
        site_root,
        source_id="web_admissions",
        title="Admissions",
        body="# Admissions\n\nAdmissions requirements include transcripts.\n",
    )
    write_registry_rows(registry_path, [row])

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.scrape_planner.llm_wiki_builder",
            "--site-root",
            str(site_root),
        ],
        input="",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert "--no-input" in result.stderr
    rows = {item["source_id"]: item for item in read_registry_rows(registry_path)}
    assert rows["web_admissions"]["wiki_status"] == "pending"


def test_wiki_launcher_uses_python_runtime(tmp_path: Path) -> None:
    from src.scrape_planner.llm_wiki_builder import launch_wiki_builder

    class FakeRunner:
        def __init__(self) -> None:
            self.calls = []

        def start(self, name: str, command: str, workdir: str):
            self.calls.append((name, command, workdir))
            return {"ok": True}

    runner = FakeRunner()
    site_root = tmp_path / "site"
    result = launch_wiki_builder(site_root, runner=runner)
    [(name, command, _workdir)] = runner.calls

    assert result["ok"] is True
    assert result["runtime"] == "python"
    assert name.startswith("wiki-site-")
    assert "--skill" not in command
    assert ".pi/skills/karpathy-wiki-builder/SKILL.md" not in command
    assert "src.scrape_planner.llm_wiki_builder" in command
    launch_report = json.loads((site_root / "wiki" / "reports" / "wiki-build-latest.json").read_text(encoding="utf-8"))
    assert launch_report["status"] == "running"
    assert launch_report["job_status"] == "running"
    assert launch_report["tmux_session"] == name


def test_wiki_launcher_uses_unique_default_session_names(tmp_path: Path, monkeypatch) -> None:
    from src.scrape_planner.llm_wiki_builder import launch_wiki_builder

    class FakeRunner:
        def __init__(self) -> None:
            self.calls = []

        def session_exists(self, name: str) -> bool:
            return any(existing_name == name for existing_name, _command, _workdir in self.calls)

        def start(self, name: str, command: str, workdir: str):
            self.calls.append((name, command, workdir))
            return {"ok": True, "command": "tmux shell command"}

    runner = FakeRunner()
    site_root = tmp_path / "site"
    monkeypatch.setattr("src.scrape_planner.llm_wiki_builder.utc_now_iso", lambda: "2026-05-22T10:11:12+00:00")

    first = launch_wiki_builder(site_root, runner=runner)
    second = launch_wiki_builder(site_root, runner=runner)

    assert first["session_name"] == "wiki-site-20260522-101112"
    assert second["session_name"] == "wiki-site-20260522-101112-2"
    assert runner.calls[0][0] == "wiki-site-20260522-101112"
    assert runner.calls[1][0] == "wiki-site-20260522-101112-2"
    latest_report = json.loads((site_root / "wiki" / "reports" / "wiki-build-latest.json").read_text(encoding="utf-8"))
    assert latest_report["tmux_session"] == "wiki-site-20260522-101112-2"


def test_raw_source_normalizer_cli_runs_without_input_and_writes_report(tmp_path: Path) -> None:
    site_root = tmp_path / "site"
    run_root = site_root / "run-001"
    markdown = run_root / "markdown" / "home.md"
    markdown.parent.mkdir(parents=True)
    markdown.write_text("# Home\n\nAdmissions info.\n", encoding="utf-8")
    (run_root / "scrape_manifest.json").write_text(
        json.dumps([{"url": "https://example.edu/", "status": "success", "markdown_path": str(markdown)}]),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.scrape_planner.raw_source_normalizer",
            "--site-root",
            str(site_root),
            "--kind",
            "web",
            "--run-root",
            str(run_root),
            "--no-input",
        ],
        input="",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    assert (site_root / "raw_sources" / "registry.jsonl").exists()
    assert json.loads(result.stdout)["mode"] == "web"
    assert json.loads(result.stdout)["no_input"] is True
    assert "input(" not in result.stderr.lower()
