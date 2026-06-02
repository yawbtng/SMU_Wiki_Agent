from __future__ import annotations

import json
from pathlib import Path

from src.scrape_planner.sources.source_registry import build_source_row, read_registry_rows, write_registry_rows

NOW = "2026-05-21T10:00:00+00:00"


def _ready_row(site_root: Path, source_id: str, title: str, body: str, *, wiki_status: str = "pending") -> dict:
    raw = site_root / "raw_sources" / "web"
    raw.mkdir(parents=True, exist_ok=True)
    md = raw / f"{source_id}.md"
    md.write_text(body, encoding="utf-8")
    meta = raw / f"{source_id}.metadata.json"
    meta.write_text(json.dumps({"title": title}), encoding="utf-8")
    return build_source_row(
        source_id=source_id,
        source_kind="web",
        title=title,
        original_url=f"https://example.edu/{source_id}",
        original_path="",
        markdown_path=str(md.relative_to(site_root)),
        metadata_path=str(meta.relative_to(site_root)),
        checksum="abc",
        parser="fixture",
        status="ready",
        now=NOW,
        wiki_status=wiki_status,
    )


def test_build_wiki_orchestrates_pi_and_writes_report(tmp_path: Path, monkeypatch) -> None:
    from src.scrape_planner.wiki.llm_wiki_builder import build_wiki

    site = tmp_path / "site"
    reg = site / "raw_sources" / "registry.jsonl"
    write_registry_rows(reg, [_ready_row(site, "web_a", "Admissions", "# Admissions\n\nApply.\n")])
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr("src.scrape_planner.wiki.llm_wiki_builder._run_pi_compile", lambda root, rebuild=False: calls.append((str(root), rebuild)))

    report = build_wiki(site, no_input=True, now=NOW)

    assert calls == [(str(site), False)]
    assert report["status"] == "complete"
    assert report["runtime"] == "pi"
    assert report["sources_considered"] == 1
    assert json.loads((site / "wiki" / "reports" / "wiki-build-latest.json").read_text(encoding="utf-8"))["processed_source_ids"] == ["web_a"]


def test_build_wiki_no_op_skips_pi(tmp_path: Path, monkeypatch) -> None:
    from src.scrape_planner.wiki.llm_wiki_builder import build_wiki

    site = tmp_path / "site"
    reg = site / "raw_sources" / "registry.jsonl"
    write_registry_rows(reg, [_ready_row(site, "web_done", "Done", "# Done\n", wiki_status="integrated")])
    called = False

    def _fail(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("src.scrape_planner.wiki.llm_wiki_builder._run_pi_compile", _fail)

    report = build_wiki(site, no_input=True, now=NOW)

    assert report["no_op"] is True
    assert report["sources_considered"] == 0
    assert called is False


def test_lint_wiki_flags_orphans_and_stale_sources(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_builder import lint_wiki

    site = tmp_path / "site"
    wiki = site / "wiki" / "pages"
    wiki.mkdir(parents=True)
    (wiki / "orphan.md").write_text("---\ntitle: Orphan\nsource_ids:\n  - x\nsource_paths:\n  - raw_sources/web/x.md\n---\n\n## Sources\n- x\n", encoding="utf-8")
    (site / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    reg = site / "raw_sources" / "registry.jsonl"
    row = _ready_row(site, "web_stale", "Stale", "# Stale\n")
    row["wiki_status"] = "integrated"
    row["wiki_page_paths"] = ["wiki/pages/linked.md"]
    write_registry_rows(reg, [row])

    report = lint_wiki(site, now=NOW)

    assert "wiki/pages/orphan.md" in report["orphan_pages"]
    assert report["stale_source_checksums"] == ["web_stale"]


def test_launch_wiki_builder_uses_pi_pipeline(tmp_path: Path, monkeypatch) -> None:
    from src.scrape_planner.wiki.llm_wiki_builder import launch_wiki_builder

    class Runner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        def start(self, name: str, command: str, workdir: str, **kwargs):
            self.calls.append((name, command, workdir))
            return {"ok": True, "tmux_grace_seconds": 1800}

    monkeypatch.setattr("src.scrape_planner.wiki.wiki_launcher.shutil.which", lambda name: "/usr/bin/pi" if name == "pi" else None)
    runner = Runner()
    result = launch_wiki_builder(tmp_path / "site", runner=runner, runtime="pi")

    assert result["ok"] is True
    assert result["runtime"] == "pi"
    assert "llm-wiki-noninteractive/scripts/build_wiki.sh" in runner.calls[0][1]


def test_launch_wiki_builder_python_runtime(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_builder import launch_wiki_builder

    class Runner:
        def start(self, name: str, command: str, workdir: str, **kwargs):
            return {"ok": True, "tmux_grace_seconds": 1800}

    result = launch_wiki_builder(tmp_path / "site", runner=Runner(), runtime="python")
    assert result["runtime"] == "python"


def test_launch_rejects_unknown_runtime(tmp_path: Path) -> None:
    from src.scrape_planner.wiki.llm_wiki_builder import launch_wiki_builder

    result = launch_wiki_builder(tmp_path / "site", runner=object(), runtime="agent")
    assert result["ok"] is False


def test_cli_requires_no_input(tmp_path: Path) -> None:
    import subprocess
    import sys

    proc = subprocess.run([sys.executable, "-m", "src.scrape_planner.wiki.llm_wiki_builder", "--site-root", str(tmp_path)], capture_output=True, text=True)
    assert proc.returncode != 0
    assert "--no-input" in proc.stderr
