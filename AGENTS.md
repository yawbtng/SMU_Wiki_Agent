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
