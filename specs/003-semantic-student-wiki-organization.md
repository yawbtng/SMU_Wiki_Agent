# Semantic Student Wiki Organization

## Goal

Use the Ralph loop to keep iterating until the generated wiki is a rich, student-question-oriented Markdown knowledge structure, not a source-page dump or simple BM25-friendly text corpus. The wiki should organize meaning and relationships so student questions retrieve coherent answer pages.

The target style is **Karpathy-style knowledge organization**: dense, readable, hierarchical, concept-first notes with clear entry points, backlinks/related links, citations, and progressive detail. Prefer a high-signal map of the institution over a flat pile of documents.

Example target question:

> I am a new grad who will likely be joining Cox. Tell me about the courses, course fee, and admission process.

A good response path should surface organized Cox/graduate pages that cover curriculum/courses, costs/fees/aid, admissions/process/deadlines, contacts, and citations.

## Ralph Loop Behavior

Ralph should churn on this spec until the wiki organization passes the acceptance criteria. Each iteration should:

1. Inspect the generated wiki structure and MCP/query results.
2. Identify the weakest organizational gap.
3. Improve the builder/index/query logic or generated content structure.
4. Rebuild or resume-build the wiki.
5. Rebuild the index.
6. Run the Cox graduate student smoke query.
7. Stop only when the generated wiki is organized enough to answer the target question with coherent semantic pages and citations.

Do not mark this spec complete just because files were generated. Fast deterministic source-card generation (even thousands of `.md` files in seconds) is only the raw materialization stage, not the semantic wiki. Completion requires qualitative organization and retrieval success.

## Requirements

1. Generate semantic Markdown entry points in addition to per-source pages:
   - `wiki/pages/schools/<school>.md`
   - `wiki/pages/schools/<school>/graduate.md` where evidence exists
   - `wiki/pages/schools/<school>/admissions.md`
   - `wiki/pages/schools/<school>/courses.md`
   - `wiki/pages/schools/<school>/costs-and-aid.md`
   - analogous pages for other schools/colleges when evidence exists.
2. Generate intent/persona pages where useful:
   - prospective graduate student
   - new student
   - current student
   - international student, if source evidence exists
3. Use Karpathy-style organization principles:
   - concept-first hierarchy, not source-first hierarchy,
   - compact summaries before details,
   - related links/backlinks between concepts,
   - high-signal headings,
   - explicit assumptions and scope,
   - citations kept close to claims,
   - progressive disclosure from overview → details → source evidence.
4. Each semantic page should use a stable student-friendly structure:
   - `Fast Answer`
   - `Who This Applies To`
   - `Courses / Curriculum`
   - `Costs / Fees / Aid`
   - `Admissions / Requirements / Deadlines`
   - `Contacts / Offices`
   - `Related Pages`
   - `Sources`
4. Add relationship metadata/frontmatter to semantic pages:
   - `page_type: semantic`
   - `audiences`
   - `school`
   - `programs`
   - `degree_levels`
   - `intents`
   - `topics`
   - `related_pages`
   - `source_ids`
   - `source_paths`
5. Retrieval/indexing must include these semantic pages and weight them as high-value wiki pages.
6. MCP query results should be able to cite semantic wiki pages as organized evidence, not just raw source chunks.
7. Keep per-source categorized Markdown pages for traceability, but student Q&A should prefer semantic pages when they answer the question.

## Acceptance Criteria

- [ ] Ralph has iterated/rebuilt until the semantic organization is visibly better than flat source pages.
- [ ] A fast run that only reports thousands of generated source `.md` files is treated as incomplete unless semantic pages and query results prove organization quality.
- [ ] The SMU wiki includes Cox-specific semantic Markdown pages when Cox evidence exists.
- [ ] A query about a new graduate student joining Cox retrieves pages covering courses/curriculum, fees/costs, and admissions/process.
- [ ] Semantic pages include source-backed citations and related page links.
- [ ] Semantic pages are indexed into `llm_wiki_documents.jsonl` with metadata marking them as semantic/high-value wiki pages.
- [ ] MCP `query_wiki` or equivalent query path returns organized wiki evidence for the Cox graduate question.
- [ ] The generated pages follow Karpathy-style organization: overview first, hierarchy, related links, concise but rich summaries, and citations close to claims.
- [ ] Tests cover semantic page generation and nested semantic page indexing.

## Status: TODO

<!-- NR_OF_TRIES: 0 -->
