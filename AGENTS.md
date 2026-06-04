# Agent Operating Guide

This root guide must stay under 50 lines. It is the router, not the handbook.
Read the linked docs before acting, then keep changes small, verified, reviewed,
and committed.

## Required Reading

1. Read [docs/agents/operating-guide.md](docs/agents/operating-guide.md) for git, review, verification, skill, and delegation rules.
2. Read [docs/agents/ai-development.md](docs/agents/ai-development.md) before building any AI-assisted app or substantial feature.
3. Read [docs/agents/codegraph.md](docs/agents/codegraph.md) before structural code exploration.
4. Read [docs/agents/repo-context.md](docs/agents/repo-context.md) for repo layout, UI/runtime facts, and durable user preferences.
5. Read [docs/agents/student-wiki-policy.md](docs/agents/student-wiki-policy.md) before changing wiki discovery, curation, scrape, index, or answer behavior.

## Non-Negotiables

- Protect user work: run `git status --short`, inspect relevant diffs, and never overwrite unrelated changes.
- Use `.cursor/skills/skill-router/SKILL.md`, then apply `$karpathy` as the default restraint-and-verification discipline.
- Codex is manager/supervisor in this repo: delegate substantive product edits through the trusted workspace handoff unless the user explicitly overrides.
- For each logical change: verify, run subagent `/code-review`, resolve blockers, then commit only explicit paths or hunks.
- New feature or behavior-change work starts on its own GitHub-ready branch with the `codex/` prefix unless the user asks otherwise.
- Use the user's `shenoyabhijith` GitHub context; file/update concise no-secret bug issues for reproducible bugs found during assigned work.
- Never push, amend, rebase, reset, clean, revert, rewrite history, or stage unrelated work without explicit current-thread approval.

## Verification

- Frontend: run TypeScript/compile check and production build when available, such as `npx tsc --noEmit` and `npm run build`.
- Backend: run Python syntax/compile checks and focused tests for changed modules.
- Running app/service changes also need a runtime smoke or log check with no new exceptions.
- Docs-only changes need Markdown/diff sanity checks and `codegraph sync` when the repo index exists.

## Repo Boundaries

- Trusted workspace: `/Users/abhsheno/Desktop/Projects/ultra-fast-rag`.
- React/FastAPI is the operator UI; Streamlit is removed and must not be reintroduced.
- Root stays minimal: `README.md`, `AGENTS.md`, `CLAUDE.md`, dependency manifests, `start.sh`, `stop.sh`, `status.sh`, and prompt seeds only.

## Learned User Preferences

- Structural code questions: CodeGraph first; use `rg` only for literal strings, policy text, configs, markdown, and logs.
- After source, config, test, or doc edits: run `codegraph sync` before further CodeGraph queries or completion reports.
- Never print or log real API keys; in tests and reports use fake keys or only presence/empty/length.
- Assigned `docs/superpowers/plans/*.md` work: implement the plan exactly, one focused logical change at a time.
- Sources-tab edits in `frontend/src/main.tsx`: preserve WorkspaceDashboard, workspace return (X), durable agent panel, and dynamic Available-areas picker unless explicitly asked otherwise.
- `uops` MCP is read-only retrieval (`query_wiki`, `get_wiki_page`, `search_sources`) unless the user explicitly requests ingest, rebuild, or operator refresh.
- Operator workspace UI: Inter/sans on cards and metadata (not monospace); Sources/Wiki/runs as neutral flat labels, not colored pills; hero data-root shows only a short project-relative tail (e.g. `repo-name/data`) with no absolute path or hover tooltip.

## Learned Workspace Facts

- Metrics tab covers Pi agent and embedding-index jobs only; scrape run outcomes stay on Runs.
- OpenRouter key saved in Settings must flow through app-state persistence into Pi/wiki build and MCP launch environment.
- Sources URL curation uses `POST /api/sites/{site_id}/approved-urls/chat` for realtime group approve/preview updates.
- Raw source registry rows need click-to-inspect via document-preview, not opaque IDs alone.
- Wiki Settings should expose a single LLM Wiki compile path; avoid redundant fallback compile modes in the operator UI.
