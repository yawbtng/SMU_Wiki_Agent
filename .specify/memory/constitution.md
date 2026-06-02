# Ultra Fast RAG Constitution

> Ultra Fast RAG is a local Streamlit app for building content-first university knowledge bases from website URLs, PDF sources, and tabular/markdown artifacts. It scrapes and normalizes sources, builds local LLM Wiki pages, and exposes graph, embedding, rerank, and MCP query surfaces.

Ralph Wiggum setup source: https://github.com/fstandhartinger/ralph-wiggum @ `3f15f0fb83b8c2e0ac8d11abdae0e83ab8204981`.

---

## Context Detection

**Ralph Loop Mode** (started by `scripts/ralph-loop*.sh`):
- Pick the highest-priority incomplete spec from `specs/`.
- Implement one complete work item at a time.
- Verify acceptance criteria and the changed code path before signaling completion.
- Output `<promise>DONE</promise>` only when the current item is 100% complete.
- Output `<promise>ALL_DONE</promise>` when no work remains.

**Interactive Mode** (normal Pi conversation):
- Be helpful, guide decisions, and create or refine specs before implementation.
- Do not jump from broad exploration into implementation unless explicitly asked.

---

## Core Principles

- **Local-first and reproducible:** Prefer deterministic local workflows, clear artifacts, and documented commands.
- **Content quality first:** Preserve source provenance, normalization quality, and traceability from raw sources to wiki/index outputs.
- **Verification before completion:** Run syntax/compile checks for changed paths and a relevant smoke/runtime sanity check when app or service behavior changes.
- **Protect existing work:** Treat pre-existing user changes as untouchable; keep changes small and reviewable.

---

## Technical Stack

Detected from the repository:
- Python Streamlit app (`app.py`) for the UI.
- Scrape, PDF ingest, LLM Wiki, indexing, and status modules under `src/scrape_planner/`.
- MCP servers under `mcp_servers/`.
- Pytest test suite under `tests/`.
- Docker Compose support for app/container runs.
- Pi project resources under `.pi/` including CodeGraph and knowledge-search packages.

---

## Autonomy

YOLO Mode: ENABLED for local command execution and file edits inside the Ralph loop.
Git Autonomy: DISABLED by default in this project. Ralph may prepare commits, but do not commit, push, rewrite history, stage unrelated files, or alter pre-existing user changes unless the user explicitly enables Git Autonomy in this constitution or asks for that specific git operation.

Model Budget: Use `gpt-5.4-mini` as the default Ralph loop model with high reasoning. Avoid GPT-5.5-class models for routine loop churn. For Pi, override only when needed with `RALPH_PI_MODEL`/`PI_MODEL` and `RALPH_PI_THINKING`.

---

## Specs

Specs live in `specs/` as markdown files. Pick the highest-priority incomplete spec (lower number = higher priority). A spec is incomplete if it lacks `## Status: COMPLETE`.

Spec template: https://raw.githubusercontent.com/github/spec-kit/refs/heads/main/templates/spec-template.md

When all specs are complete, re-verify a random completed spec before signaling done.

---

## NR_OF_TRIES

Track attempts per spec via `<!-- NR_OF_TRIES: N -->` at the bottom of the spec file. Increment each attempt. At 10+, the spec is too hard — split it into smaller specs.

---

## Work Index and History

`docs/planning/work-index.md` is the human-readable index of Ralph work, queue status, completion ledger, and stop rule. Check it before starting work.

Append a 1-line summary to `docs/planning/history.md` after each spec completion. For details, create `docs/planning/completion_log/YYYY-MM-DD--HH-MM-SS--spec-name.md` with lessons learned, decisions made, and issues encountered. Check history before starting work on any spec.

After each completed spec, update `docs/planning/work-index.md`, `docs/planning/history.md`, and a timestamped `docs/planning/completion_log/` entry. When every spec in `specs/` has `## Status: COMPLETE`, re-verify one completed spec and output `<promise>ALL_DONE</promise>`.

Planning mode writes or updates `docs/planning/implementation-plan.md` (not a root-level plan file).

For semantic wiki organization specs, Ralph must keep iterating until the generated Markdown wiki is concept-first, hierarchical, citation-backed, and retrieval-verified against student questions. Do not mark those specs complete just because the builder emitted files.

---

## Completion Logs

After each completed spec, create `docs/planning/completion_log/YYYY-MM-DD--HH-MM-SS--spec-name.md` with a brief summary of what changed, how it was verified, and any follow-up risks.

---

## Completion Signal

Only output `<promise>DONE</promise>` after all of the following are true:
- The chosen spec's acceptance criteria are satisfied.
- Required syntax/compile checks pass.
- Relevant tests pass.
- Runtime or app/service smoke checks pass when behavior changed, or the reason they could not run is documented.
- History/completion log updates are written.
- Git requirements match the current Autonomy section.

Never output `<promise>DONE</promise>` until truly complete.
