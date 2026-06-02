# PDF Extraction Blueprint

## Goal

Create a deterministic extraction plan before parsing a PDF. The system should first inspect the document quickly, write a per-PDF blueprint record (see this doc) that decides which pages or page ranges use the fast text parser and which pages use Docling, then parse by following that blueprint exactly.

This prevents hidden fallback behavior. Parser choice becomes reviewable, testable, and visible in the UI.

## Pipeline

```text
PDF upload
  |
  v
Fast page probe
  |
  v
Blueprint generation
  |
  v
Human/system review if confidence is low
  |
  v
Parse by blueprint
  |
  v
Merge normalized markdown + page metadata
```

## Parser Roles

| Parser | Role | Use When |
| --- | --- | --- |
| PyPDF or PyMuPDF fast text | Cheap first pass and text-heavy extraction | Pages have clean text density, simple layout, and low structure risk |
| Docling | Structure-aware extraction | Pages contain tables, dense layout, image-heavy regions, scanned/low-text content, or uncertain extraction quality |

PyMuPDF is preferred for the probe when available because it exposes coordinates, blocks, images, and page geometry. PyPDF can still be used as the minimum available fast text path.

## Blueprint Contract

Each PDF should produce a blueprint before full extraction.

```json
{
  "pdf_source_id": "sha-or-stable-id",
  "path": "sources/pdf_uploads/catalog.pdf",
  "page_count": 1165,
  "created_at": "2026-05-20T00:00:00Z",
  "mode": "hybrid",
  "confidence": 0.91,
  "ranges": [
    {
      "start_page": 1,
      "end_page": 20,
      "parser": "docling",
      "reason": "toc_and_table_heavy",
      "confidence": 0.94
    },
    {
      "start_page": 21,
      "end_page": 700,
      "parser": "fast_text",
      "reason": "clean_text_dense_pages",
      "confidence": 0.88
    }
  ],
  "review_required": false,
  "warnings": []
}
```

## Page Probe Features

The probe should score every page with cheap signals before choosing a parser.

| Feature | Meaning |
| --- | --- |
| `text_chars` | Raw extracted text length |
| `words` | Extracted word count |
| `chars_per_page` | Text density |
| `image_count` | Number of embedded images |
| `image_area_ratio` | Approximate image coverage on the page |
| `text_block_count` | Number of detected text blocks |
| `column_count_estimate` | Whether content appears multi-column |
| `alignment_score` | Repeated x-position / column-like text alignment |
| `numeric_column_score` | Dense numeric/page-number columns |
| `table_region_score` | Likelihood of tables or table-like regions |
| `weirdness_score` | Garbled extraction, repeated spacing, broken words, low readable token ratio |

## Routing Policy

Parser choice should be based on page-level scores, then compressed into ranges.

```text
Use fast_text when:
  - text density is high
  - readable token ratio is high
  - layout complexity is low
  - table/image scores are low

Use docling when:
  - table_region_score is high
  - image_area_ratio is high
  - text density is low
  - layout complexity is high
  - extraction weirdness is high
  - confidence is uncertain and sample comparison favors Docling
```

Suggested initial scoring:

```text
docling_score =
  image_area_ratio * 3
  + table_region_score * 3
  + layout_complexity * 2
  + column_count_estimate * 1.5
  + numeric_column_score * 1.5
  + weirdness_score * 2
  - clean_text_density * 2
```

Initial thresholds:

| Score | Decision |
| --- | --- |
| `>= 3.0` | Docling |
| `<= 1.0` | fast_text |
| `1.0 - 3.0` | uncertain; compare both parsers on representative sampled pages |

## Blueprint Markdown Shape

The UI can render the blueprint as markdown for review:

```markdown
# Extraction Blueprint: catalog.pdf

Decision: Hybrid
Confidence: 0.91
Pages: 1165

| Pages | Parser | Reason | Confidence |
| --- | --- | --- | --- |
| 1-20 | Docling | TOC/table-heavy | 0.94 |
| 21-700 | Fast text | Clean dense prose | 0.88 |
| 701-760 | Docling | Course tables | 0.92 |

## Warnings

- None
```

## Parsing Rule

The parser stage must not decide parser choice on its own.

```text
Allowed:
  - Read blueprint
  - Extract each range using the assigned parser
  - Record parser, reason, confidence, and timing per page/range
  - Fail clearly if a parser required by the blueprint is unavailable

Not allowed:
  - Silently fall back from Docling to fast text
  - Silently upgrade fast text pages to Docling
  - Hide parser choice from downstream chunks or UI
```

If parsing fails for a blueprint range, mark that range as failed and require regeneration or review.

## Output Contract

Every extracted page should preserve provenance.

```json
{
  "pdf_source_id": "catalog",
  "page_number": 42,
  "parser": "fast_text",
  "blueprint_reason": "clean_text_dense_pages",
  "blueprint_confidence": 0.88,
  "markdown_path": "sources/pdf_pages/catalog/page-0042.md",
  "char_count": 3812,
  "extract_seconds": 0.04
}
```

Chunks should carry the same parser and page provenance so retrieval/debugging can explain why a fact came from PyPDF/PyMuPDF or Docling.

## UI Behavior

The PDF Sources tab should show blueprint status before extraction:

```text
Catalog.pdf
Blueprint: Hybrid
Fast pages: 812
Docling pages: 353
Confidence: 0.91
Review: Not required
```

For low-confidence documents:

```text
Catalog.pdf
Blueprint: Review required
Uncertain pages: 44
Action: compare sample output / override ranges
```

## Test Strategy

Use labeled PDF fixtures to validate the router:

| Fixture | Expected Blueprint |
| --- | --- |
| simple-policy.pdf | all fast_text |
| catalog-toc.pdf | Docling for TOC/table pages |
| course-table.pdf | Docling |
| prose-chapter.pdf | fast_text |
| scanned-form.pdf | Docling or OCR-needed |
| mixed-catalog.pdf | hybrid page ranges |

Tests should verify:

- Blueprint is created before parsing.
- Parser stage follows blueprint exactly.
- Low-confidence pages require review or sample comparison.
- Output rows include parser, reason, confidence, and timing.
- No silent fallback occurs.

