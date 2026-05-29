# Agent Operating Guide

This file defines how coding agents must behave in this repository. It is intentionally prescriptive: protect user work, keep changes reviewable, and prefer evidence over guesses.

## Operating character

- Be careful, direct, and accountable. If you make a mistake, say so plainly and fix it with the smallest safe change.
- Do not turn explanations, reports, diagrams, or brainstorming into code changes unless the user explicitly asks for an implementation.
- Treat the main thread as the orchestrator: gather evidence, summarize clearly, and ask before broad or destructive changes.
- Prefer boring, maintainable solutions over clever rewrites.
- Preserve user intent and existing work. Never overwrite, revert, or clean files just to make your own path easier.

## Mandatory git-first workflow

Before every code/doc/config change:

1. Run `git status --short`.
2. Inspect relevant diffs before editing (`git diff -- <path>` when a file is already modified).
3. Identify which changes are pre-existing and do not touch unrelated user work.
4. Make one focused logical change.
5. Run relevant verification.
6. Run `git status --short` again.
7. Commit only the approved/relevant files for that logical change when the user has requested a change workflow that includes commits.

Git rules:

- Use small GitHub-style commits: one concern per commit, clear imperative message, no unrelated files.
- Commit only explicit paths/hunks. Do not `git add .` in this repo.
- Never stage, revert, reset, rebase, clean, amend, push, or rewrite history unless explicitly authorized.
- If the worktree contains many unrelated changes, keep your commit scoped to your files and report the remaining unrelated changes.
- Before a commit: inspect the diff and run verification. If verification cannot run, state that clearly before committing.

## Approval boundary

- Read-only investigation/reporting does not imply permission to edit.
- User-facing app changes, UI diagrams, generated artifacts, data purges, and broad refactors require explicit approval.
- If the user asks “what/why/how” or asks for a diagram “for understanding,” answer in chat first; do not modify the app.
- If requirements are ambiguous, propose the change plan and wait for confirmation.

## Skill routing

- At the start of nontrivial work, or when unsure which workflow applies, read and follow `.cursor/skills/skill-router/SKILL.md` (`skill-router`).
- That skill maps task types to installed plugin skills, Pi skills, and Ralph modes. Do not guess—route first, then load the chosen skill in full.

## Cursor Engineering Plugins

Installed under `~/.cursor/plugins/local/` from [cursor/plugins](https://github.com/cursor/plugins). Reload Cursor after install changes.

| Plugin | Invoke when |
|--------|-------------|
| **pstack** | Rigorous engineering: `/poteto-mode`, `architect`, `how`, `principle-prove-it-works`, `show-me-your-work` for long autonomous runs |
| **ralph-loop** | Cursor IDE Ralph loop: start with `ralph-loop` skill; state in `.cursor/ralph/scratchpad.md`; cancel with `cancel-ralph` |
| **continual-learning** | Hook-driven; mines transcripts into `AGENTS.md` (`## Learned User Preferences`, `## Learned Workspace Facts`) |
| **cli-for-agent** | Designing or reviewing agent-friendly CLIs (`scripts/ralph-loop*.sh`, wiki build scripts) |
| **thermos** | Deep branch audit: `thermos`, `thermo-nuclear-review`, `thermo-nuclear-code-quality-review` |
| **agent-compatibility** | One-shot repo audit: `check-agent-compatibility` |
| **cursor-team-kit** | Engineering subset only: `verify-this`, `check-compiler-errors`, `deslop`, `control-ui`, `control-cli` |
| **teaching** | Learning paths: `create-learning-path`, `run-learning-retrospective` |

**Ralph split:** Pi headless loops use `scripts/ralph-loop-pi.sh` + `.specify/memory/constitution.md`. Cursor IDE loops use the **ralph-loop** plugin hooks. Both can coexist.

**Not in scope:** cloud agents (`orchestrate`, `cursor-sdk`), GTM/sales, git/PR shipping skills (`fix-ci`, `review-and-ship`, etc.) unless explicitly requested.

## Repository layout

- Keep the repository root limited to app entrypoints, dependency manifests, and agent pointers.
- Planning docs live under `docs/planning/`; feature specs live under `specs/`.
- UI simplification plan: `docs/planning/ui-simplification-plan.md`.

## Codebase layout

Product code is under `src/scrape_planner/` in domain subpackages:

- `core`, `scrape`, `pdf`, `sources`, `wiki`, `graph`, `index`, `tracer`, `runtime`, `ui`, `app`, `infra`

See `docs/CODEBASE.md` for the full module map.

## Ralph Wiggum

- For Ralph Wiggum/spec-driven autonomous loops, read `.specify/memory/constitution.md` first; it is the project-level Ralph source of truth.
- The Pi-specific Ralph entrypoint is `scripts/ralph-loop-pi.sh`; Pi prompt templates are available as `/ralph-build` and `/ralph-plan` after `/reload`.
- For in-IDE Ralph loops, use the **ralph-loop** plugin (`ralph-loop` / `cancel-ralph` skills).

## Exploration preference

- When the user asks to explore, audit, scan, investigate, or review a broad repo/data/workflow question, use subagents by default.
- If the codebase needs to be explored, use the `explorer` tool by default (or `/explorer` in the interactive TUI).
- Prefer CodeGraph for code search, symbol lookup, dependency/impact analysis, and affected-test discovery.
- Use plain text search only when CodeGraph cannot answer the question or for non-indexed files/data.
- Keep the main thread light: delegate broad scans and summarize only high-signal findings, evidence, and recommended next steps.
- Do not jump from exploration into implementation unless explicitly asked.

## CodeGraph index hygiene

- Use CodeGraph as the first-choice codebase search/index for symbol lookup, call graphs, dependency/impact analysis, affected-test discovery, and broad code mapping.
- After any agent-made source/config/test/doc change in this repository, run `codegraph sync` before further CodeGraph queries and before reporting completion.
- If `codegraph sync` or `codegraph status` reports problems, stop relying on the index for that area and report the issue.
- When delegating to explorer, ask it to use CodeGraph-first searches and to sync/check the index when the task depends on recent changes.

## Verification before completion

- Before saying a fix is done, run a compile/syntax check for changed code paths.
- If the change affects a running app/service, also run a runtime sanity check or smoke test and confirm no new exceptions.
- For docs-only changes, at minimum inspect the rendered/diffed Markdown structure when practical.
- Report completion only after checks pass, or clearly state what could not be verified.

## Student wiki content policy

The student wiki should prioritize current, canonical, student-actionable information.

Keep/promote:

- Registrar, enrollment, academic calendars, final exams
- Course catalog, degree/program requirements, courses
- Grades, GPA, probation/suspension, withdrawal/drop policies
- Tuition, financial aid, scholarships, billing/payment
- Housing, dining, health, counseling, parking, orientation, accessibility

Exclude/demote:

- Class notes, alumni updates, old dated news/magazine articles
- Donor/giving/advancement pages, annual reports, president/trustee/admin pages
- Staff bios unless they are clearly student-support contact pages
- Design/component/template/demo/search pages
- Corrupted extraction artifacts or mostly navigation/boilerplate pages

For stale-content questions, recommend refresh discovery/scrape, re-normalize sources, purge excluded artifacts, and rebuild the wiki/index cleanly.

## Learned user preferences

- The user expects a git-first workflow for all changes: status/diff first, small focused edits, verification, and scoped commits following GitHub hygiene.
- Do not add explanatory UI/code artifacts, such as diagrams, unless the user explicitly asks to implement them in the product.
- The user prefers concise, evidence-backed reports with clear “keep/remove/next action” recommendations.
