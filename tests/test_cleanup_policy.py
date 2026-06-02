from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_pdf_ingest_is_docling_only() -> None:
    pdf_source = read_repo_file("src/scrape_planner/pdf/pdf_ingest.py")
    requirements = read_repo_file("requirements-pdf.txt")

    assert "pypdf" not in pdf_source.lower()
    assert "pypdf" not in requirements.lower()
    assert "_parse_pdf_auto" not in pdf_source
    assert "_parse_pdf_with_docling" in pdf_source


def test_ignore_policy_has_no_conflict_markers_and_ignores_generated_tool_output() -> None:
    gitignore = read_repo_file(".gitignore")

    for marker in ("<<<<<<<", "=======", ">>>>>>>"):
        assert marker not in gitignore

    for pattern in (".gsd/", ".codex/", ".opencode/", ".pycache_compile/", "tests/docling_sample_output/"):
        assert pattern in gitignore
