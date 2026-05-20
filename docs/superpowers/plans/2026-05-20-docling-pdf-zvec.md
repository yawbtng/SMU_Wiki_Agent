# Docling PDF Zvec Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current low-level PDF text extraction with a strict Docling-only PDF ingestion path that produces chunks ready for Zvec embedding.

**Architecture:** PDF parsing has one parser boundary: `src/scrape_planner/pdf_ingest.py` calls Docling, validates the markdown output, and chunks that output. No pypdf, PyMuPDF, pdfplumber, OCR, or fallback parser remains in the ingestion path. Zvec indexing gets a small PDF document loader that can include accepted PDF chunks beside existing markdown/wiki documents.

**Tech Stack:** Python, pytest, Docling, Ollama embeddings, Zvec, existing `PdfSourceRow`/`PdfChunkRow`/`PdfQuarantineRow` contracts.

---

## File Structure

- Modify `requirements-pdf.txt`: replace MarkItDown with Docling as the one PDF/document parser dependency.
- Modify `src/scrape_planner/pdf_contracts.py`: add parser/source metadata to PDF chunks without creating a second contract model.
- Modify `src/scrape_planner/pdf_ingest.py`: remove `pypdf` usage and implement strict Docling conversion, validation, and chunking.
- Modify `tests/test_pdf_ingest.py`: rewrite tests around a monkeypatched Docling conversion boundary instead of `PdfReader`.
- Modify `scripts/zvec_index_run.py`: load accepted PDF chunks from a run/site directory and index them into the same Zvec collection as markdown/wiki chunks.
- Create `tests/test_zvec_index_run.py`: verify PDF chunks are loaded as Zvec documents without invoking Ollama or Zvec.

## Non-Goals

- Do not add OCR.
- Do not add fallback parsing libraries.
- Do not preserve the old pypdf extraction path.
- Do not redesign the Streamlit page in this plan.

---

### Task 1: Make Docling The PDF Parser Dependency

**Files:**
- Modify: `requirements-pdf.txt`

- [ ] **Step 1: Replace the PDF dependency file**

Set `requirements-pdf.txt` to exactly:

```text
# PDF/document ingestion dependencies.
# Docling is the only supported PDF parser for this project.
docling>=2.31.0
```

- [ ] **Step 2: Run dependency file smoke check**

Run: `python -m pip install -r requirements-pdf.txt --dry-run`

Expected: command resolves `docling` or fails because the local pip version does not support `--dry-run`. If `--dry-run` is unsupported, run `python -m pip --version` and note the unsupported dry-run in the implementation summary.

- [ ] **Step 3: Commit**

```bash
git add requirements-pdf.txt
git commit -m "chore: use docling for pdf ingestion"
```

---

### Task 2: Extend PDF Chunk Metadata For Parser Provenance

**Files:**
- Modify: `src/scrape_planner/pdf_contracts.py`
- Modify: `tests/test_pdf_ingest.py`

- [ ] **Step 1: Write the failing contract test**

Add this test to `tests/test_pdf_ingest.py`:

```python
def test_pdf_chunks_include_docling_parser_metadata(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "catalog.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")

    monkeypatch.setattr(
        "src.scrape_planner.pdf_ingest._parse_pdf_with_docling",
        lambda path: "# Catalog\n\nAdmissions requirements and tuition information for students.",
    )

    result = ingest_pdfs([pdf_path], PdfIngestConfig(min_meaningful_chars=20))

    assert result.quarantine == []
    assert result.chunks[0].parser == "docling"
    assert result.chunks[0].source_path == str(pdf_path)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_pdf_ingest.py::test_pdf_chunks_include_docling_parser_metadata -v`

Expected: FAIL because `PdfChunkRow` has no `parser` or `source_path` fields, and `_parse_pdf_with_docling` does not exist yet.

- [ ] **Step 3: Update `PdfChunkRow`**

Change `PdfChunkRow` in `src/scrape_planner/pdf_contracts.py` to:

```python
@dataclass(frozen=True)
class PdfChunkRow:
    chunk_id: str
    pdf_source_id: str
    page_number: int
    chunk_index: int
    text: str
    char_count: int
    created_at: str
    parser: str = "docling"
    source_path: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "pdf_source_id": self.pdf_source_id,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "char_count": self.char_count,
            "created_at": self.created_at,
            "parser": self.parser,
            "source_path": self.source_path,
        }
```

- [ ] **Step 4: Run the focused test again**

Run: `pytest tests/test_pdf_ingest.py::test_pdf_chunks_include_docling_parser_metadata -v`

Expected: still FAIL because the ingestion implementation has not been updated yet.

- [ ] **Step 5: Commit the contract change**

```bash
git add src/scrape_planner/pdf_contracts.py tests/test_pdf_ingest.py
git commit -m "test: require pdf parser metadata"
```

---

### Task 3: Replace `pypdf` Ingestion With Strict Docling Parsing

**Files:**
- Modify: `src/scrape_planner/pdf_ingest.py`
- Modify: `tests/test_pdf_ingest.py`

- [ ] **Step 1: Replace pypdf-specific tests with Docling-boundary tests**

Update `tests/test_pdf_ingest.py` so it imports only:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from src.scrape_planner.pdf_ingest import PdfIngestConfig, PdfParserUnavailableError, ingest_pdfs
```

Keep `test_empty_input_returns_no_rows`, `test_nonexistent_file_is_malformed`, and `test_too_large_boundary`.

Delete tests that monkeypatch `PdfReader`.

Add these tests:

```python
def test_docling_parse_failure_is_recorded_without_fallback(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "bad.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")

    def fail(_path: Path) -> str:
        raise RuntimeError("docling could not parse layout")

    monkeypatch.setattr("src.scrape_planner.pdf_ingest._parse_pdf_with_docling", fail)

    result = ingest_pdfs([pdf_path])

    assert result.sources[0].accepted is False
    assert result.quarantine[0].reason == "parse_failed"
    assert "docling could not parse layout" in result.quarantine[0].detail
    assert result.chunks == []


def test_docling_empty_output_is_low_text(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "empty.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")

    monkeypatch.setattr("src.scrape_planner.pdf_ingest._parse_pdf_with_docling", lambda _path: "   ")

    result = ingest_pdfs([pdf_path], PdfIngestConfig(min_meaningful_chars=20))

    assert result.sources[0].accepted is False
    assert result.quarantine[0].reason == "low_text"
    assert result.chunks == []


def test_docling_happy_path_chunks_deterministically(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "catalog.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")
    markdown = "# Catalog\n\n" + "Admissions tuition registrar housing. " * 20

    monkeypatch.setattr("src.scrape_planner.pdf_ingest._parse_pdf_with_docling", lambda _path: markdown)

    cfg = PdfIngestConfig(chunk_size=80, chunk_overlap=20, min_meaningful_chars=20)
    r1 = ingest_pdfs([pdf_path], cfg)
    r2 = ingest_pdfs([pdf_path], cfg)

    assert r1.quarantine == []
    assert r1.sources[0].accepted is True
    assert all(c.page_number == 1 for c in r1.chunks)
    assert all(c.parser == "docling" for c in r1.chunks)
    assert all(c.source_path == str(pdf_path) for c in r1.chunks)
    assert [c.chunk_id for c in r1.chunks] == [c.chunk_id for c in r2.chunks]


def test_missing_docling_raises_setup_error(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "catalog.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")

    def unavailable(_path: Path) -> str:
        raise PdfParserUnavailableError("Docling is not installed. Install requirements-pdf.txt.")

    monkeypatch.setattr("src.scrape_planner.pdf_ingest._parse_pdf_with_docling", unavailable)

    with pytest.raises(PdfParserUnavailableError, match="Docling is not installed"):
        ingest_pdfs([pdf_path])
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_pdf_ingest.py -v`

Expected: FAIL because the implementation still imports `pypdf`, lacks `PdfParserUnavailableError`, and lacks `_parse_pdf_with_docling`.

- [ ] **Step 3: Replace `pdf_ingest.py` implementation**

Update `src/scrape_planner/pdf_ingest.py` imports and add the parser error class:

```python
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .pdf_contracts import PdfChunkRow, PdfQuarantineRow, PdfSourceRow, utc_now_iso


class PdfParserUnavailableError(RuntimeError):
    """Raised when the only supported PDF parser cannot be imported."""
```

Add the Docling parser boundary:

```python
def _parse_pdf_with_docling(path: Path) -> str:
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise PdfParserUnavailableError("Docling is not installed. Install requirements-pdf.txt.") from exc

    converter = DocumentConverter()
    result = converter.convert(str(path))
    document = getattr(result, "document", None)
    if document is None:
        raise RuntimeError("Docling returned no document")
    if not hasattr(document, "export_to_markdown"):
        raise RuntimeError("Docling document cannot export markdown")
    return str(document.export_to_markdown() or "")
```

Replace the file handling loop inside `ingest_pdfs` with this behavior:

```python
        try:
            markdown = _parse_pdf_with_docling(path).strip()
        except PdfParserUnavailableError:
            raise
        except Exception as exc:
            quarantine.append(PdfQuarantineRow(source_id, str(path), "parse_failed", str(exc), utc_now_iso()))
            sources.append(PdfSourceRow(source_id, str(path), size, None, False, utc_now_iso()))
            continue

        total_chars = _meaningful_chars(markdown)
        reason = _classify_low_text(total_chars, 1, cfg)
        if reason is not None:
            quarantine.append(
                PdfQuarantineRow(source_id, str(path), reason, f"meaningful_chars={total_chars} pages=1", utc_now_iso())
            )
            sources.append(PdfSourceRow(source_id, str(path), size, 1, False, utc_now_iso()))
            continue

        sources.append(PdfSourceRow(source_id, str(path), size, 1, True, utc_now_iso()))
        for chunk_index, chunk_text in enumerate(_chunk_text(markdown, cfg), start=0):
            chunk_id = _chunk_id(source_id, 1, chunk_index, chunk_text)
            chunks.append(
                PdfChunkRow(
                    chunk_id=chunk_id,
                    pdf_source_id=source_id,
                    page_number=1,
                    chunk_index=chunk_index,
                    text=chunk_text,
                    char_count=len(chunk_text),
                    created_at=utc_now_iso(),
                    parser="docling",
                    source_path=str(path),
                )
            )
```

Keep `_source_id`, `_chunk_id`, `_meaningful_chars`, `_classify_low_text`, and `_chunk_text`, but remove all `PdfReader`, `PdfReadError`, `reader.is_encrypted`, and page iteration code.

- [ ] **Step 4: Run PDF ingest tests**

Run: `pytest tests/test_pdf_ingest.py -v`

Expected: PASS.

- [ ] **Step 5: Run PDF contract proof tests**

Run: `pytest tests/test_m001_proof_command.py tests/test_pdf_ingest.py -v`

Expected: PASS. If proof fixtures construct `PdfChunkRow` positionally, update them to include only existing positional fields and rely on defaults for `parser` and `source_path`.

- [ ] **Step 6: Commit**

```bash
git add src/scrape_planner/pdf_ingest.py src/scrape_planner/pdf_contracts.py tests/test_pdf_ingest.py tests/test_m001_proof_command.py
git commit -m "feat: parse pdfs with docling only"
```

---

### Task 4: Add PDF Chunks To Zvec Document Loading

**Files:**
- Modify: `scripts/zvec_index_run.py`
- Create: `tests/test_zvec_index_run.py`

- [ ] **Step 1: Write failing tests for PDF chunk loading**

Create `tests/test_zvec_index_run.py` with:

```python
from __future__ import annotations

import json
from pathlib import Path

from scripts.zvec_index_run import _load_docs_for_indexing


def test_load_docs_for_indexing_includes_pdf_chunks(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    s05 = run_root / "s05"
    s05.mkdir(parents=True)
    chunks_path = s05 / "pdf_chunks.jsonl"
    chunks_path.write_text(
        json.dumps(
            {
                "chunk_id": "pdf1-p0001-c0000-abc",
                "pdf_source_id": "pdf1",
                "page_number": 1,
                "chunk_index": 0,
                "text": "Admissions catalog PDF chunk text",
                "char_count": 33,
                "created_at": "2026-05-20T00:00:00+00:00",
                "parser": "docling",
                "source_path": "/tmp/catalog.pdf",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    docs = _load_docs_for_indexing(run_root)

    assert docs == [
        {
            "url": "",
            "title": "catalog.pdf page 1",
            "path": "/tmp/catalog.pdf#page=1&chunk=0",
            "text": "Admissions catalog PDF chunk text",
        }
    ]


def test_load_docs_for_indexing_skips_bad_pdf_chunk_rows(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    s05 = run_root / "s05"
    s05.mkdir(parents=True)
    (s05 / "pdf_chunks.jsonl").write_text('{"text": ""}\nnot-json\n', encoding="utf-8")

    assert _load_docs_for_indexing(run_root) == []
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_zvec_index_run.py -v`

Expected: FAIL because `_load_docs_for_indexing` does not exist.

- [ ] **Step 3: Refactor zvec document loading**

In `scripts/zvec_index_run.py`, add:

```python
def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _load_pdf_chunk_docs(run_root: Path) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for row in _read_jsonl(run_root / "s05" / "pdf_chunks.jsonl"):
        text = str(row.get("text") or "").strip()
        source_path = str(row.get("source_path") or "").strip()
        if not text or not source_path:
            continue
        try:
            page_number = int(row.get("page_number") or 1)
            chunk_index = int(row.get("chunk_index") or 0)
        except Exception:
            continue
        title = f"{Path(source_path).name} page {page_number}"
        docs.append(
            {
                "url": "",
                "title": title,
                "path": f"{source_path}#page={page_number}&chunk={chunk_index}",
                "text": text,
            }
        )
    return docs


def _load_docs_for_indexing(run_root: Path) -> list[dict[str, str]]:
    return _load_cleaned_docs(run_root) + _load_pdf_chunk_docs(run_root)
```

Then change `main()` from:

```python
docs = _load_cleaned_docs(run_root)
```

to:

```python
docs = _load_docs_for_indexing(run_root)
```

- [ ] **Step 4: Run focused zvec loader tests**

Run: `pytest tests/test_zvec_index_run.py -v`

Expected: PASS.

- [ ] **Step 5: Run related tests**

Run: `pytest tests/test_zvec_index_run.py tests/test_pdf_ingest.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/zvec_index_run.py tests/test_zvec_index_run.py
git commit -m "feat: index docling pdf chunks in zvec"
```

---

### Task 5: Add A Small PDF-to-Zvec Smoke Fixture Path

**Files:**
- Modify: `tests/test_zvec_index_run.py`
- Modify: `scripts/zvec_index_run.py`

- [ ] **Step 1: Add a test that markdown and PDF docs are both loaded**

Append this test to `tests/test_zvec_index_run.py`:

```python
def test_load_docs_for_indexing_keeps_markdown_and_pdf_docs(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    md_dir = run_root / "wiki"
    md_dir.mkdir(parents=True)
    (md_dir / "admissions.md").write_text("Admissions markdown page", encoding="utf-8")

    s05 = run_root / "s05"
    s05.mkdir(parents=True)
    (s05 / "pdf_chunks.jsonl").write_text(
        json.dumps(
            {
                "chunk_id": "pdf1-p0002-c0001-def",
                "pdf_source_id": "pdf1",
                "page_number": 2,
                "chunk_index": 1,
                "text": "Tuition PDF chunk",
                "char_count": 17,
                "created_at": "2026-05-20T00:00:00+00:00",
                "parser": "docling",
                "source_path": "/tmp/tuition.pdf",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    docs = _load_docs_for_indexing(run_root)

    assert [doc["title"] for doc in docs] == ["admissions", "tuition.pdf page 2"]
    assert [doc["text"] for doc in docs] == ["Admissions markdown page", "Tuition PDF chunk"]
```

- [ ] **Step 2: Run combined loader tests**

Run: `pytest tests/test_zvec_index_run.py -v`

Expected: PASS.

- [ ] **Step 3: Run the full non-network PDF/Zvec subset**

Run: `pytest tests/test_pdf_ingest.py tests/test_zvec_index_run.py tests/test_m001_proof_command.py -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_zvec_index_run.py scripts/zvec_index_run.py
git commit -m "test: cover pdf chunks in zvec loader"
```

---

### Task 6: Manual Docling Smoke Test With A Real PDF

**Files:**
- No source files required unless the smoke test exposes a bug.

- [ ] **Step 1: Install PDF dependencies**

Run: `python -m pip install -r requirements-pdf.txt`

Expected: Docling installs successfully.

- [ ] **Step 2: Run PDF ingestion from a Python one-liner**

Replace `<PDF_PATH>` with one uploaded/real PDF path under `data/sites/<site_id>/sources/pdf_uploads/`.

Run:

```bash
python - <<'PY'
from pathlib import Path
from src.scrape_planner.pdf_ingest import ingest_pdfs

path = Path("<PDF_PATH>")
result = ingest_pdfs([path])
print({
    "sources": len(result.sources),
    "chunks": len(result.chunks),
    "quarantine": [row.to_dict() for row in result.quarantine],
    "first_chunk": result.chunks[0].to_dict() if result.chunks else None,
})
PY
```

Expected: For a digital text PDF, `chunks` is greater than `0` and `quarantine` is empty. For a PDF Docling cannot parse, `chunks` is `0` and `quarantine[0].reason` is `parse_failed` or `low_text`.

- [ ] **Step 3: Run zvec loader smoke test without embedding calls**

If the ingestion output is written to `run_root/s05/pdf_chunks.jsonl`, run:

```bash
python - <<'PY'
from pathlib import Path
from scripts.zvec_index_run import _load_docs_for_indexing

run_root = Path("<RUN_ROOT>")
docs = _load_docs_for_indexing(run_root)
print({"docs": len(docs), "first": docs[0] if docs else None})
PY
```

Expected: PDF chunks appear as docs with `title` like `catalog.pdf page 1` and `path` ending in `#page=<n>&chunk=<n>`.

- [ ] **Step 4: Final verification**

Run: `pytest tests/test_pdf_ingest.py tests/test_zvec_index_run.py tests/test_m001_proof_command.py -v`

Expected: PASS.

- [ ] **Step 5: Commit any smoke-test fixes**

Only if source changes were needed:

```bash
git add src/scrape_planner/pdf_ingest.py scripts/zvec_index_run.py tests/test_pdf_ingest.py tests/test_zvec_index_run.py
git commit -m "fix: stabilize docling pdf ingestion"
```

---

## Self-Review Notes

- Spec coverage: the plan removes the old parser path, uses Docling only, validates text output, chunks parsed markdown, and adds PDF chunks to Zvec loading.
- Placeholder scan: no TBD/TODO/implement-later placeholders remain.
- Type consistency: `PdfChunkRow.parser`, `PdfChunkRow.source_path`, `_parse_pdf_with_docling`, `PdfParserUnavailableError`, and `_load_docs_for_indexing` are introduced before later tasks reference them.
