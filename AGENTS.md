# Agent Operating Guide

This file defines how coding agents must behave in this repository. It is intentionally prescriptive: protect user work, keep changes reviewable, and prefer evidence over guesses.

## Operating character

- Be careful, direct, and accountable. If you make a mistake, say so plainly and fix it with the smallest safe change.
- Do not turn explanations, reports, diagrams, or brainstorming into code changes unless the user explicitly asks for an implementation.
- Treat the main thread as the orchestrator: gather evidence, summarize clearly, and ask before broad or destructive changes.
- Prefer boring, maintainable solutions over clever rewrites.
- Preserve user intent and existing work. Never overwrite, revert, or clean files just to make your own path easier.

## Codex manager handoff

When **Codex** supervises multi-step work in this repo, read `.cursor/skills/cursor-agent-handoff/SKILL.md` first. Codex is manager/supervisor only: delegate substantive edits to Cursor Agent with `--workspace /Users/abhsheno/Desktop/Projects/ultra-fast-rag` (see the skill for the exact `agent` invocation). Codex may write plans/prompts and run lightweight verification; it must not edit product source, tests, configs, or `data/` unless the user explicitly overrides in-thread.

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
- Never push to any remote without a fresh, explicit manual approval in the current thread, even if the user previously asked to merge or an approved command prefix exists.
- Never swap, repoint, or replace the active workspace while inside it. Exit the workspace first, then perform an explicit workspace switch as the only operation.
- If the worktree contains many unrelated changes, keep your commit scoped to your files and report the remaining unrelated changes.
- Before a commit: inspect the diff and run verification. If verification cannot run, state that clearly before committing.

## Approval boundary

- Read-only investigation/reporting does not imply permission to edit.
- User-facing app changes, UI diagrams, generated artifacts, data purges, and broad refactors require explicit approval.
- If the user asks “what/why/how” or asks for a diagram “for understanding,” answer in chat first; do not modify the app.
- If requirements are ambiguous, propose the change plan and wait for confirmation.

## Skill routing

Use the skill router as the source of truth. Do not choose skills from memory or invent unavailable tools/services.

Protocol:

1. For any nontrivial task, ambiguous request, multi-step implementation, broad investigation, verification request, or autonomous loop, read `.cursor/skills/skill-router/SKILL.md` first.
2. Classify the user request using the router's task table and quick-decision rules.
3. Pick one primary skill, plus only the optional chain the router explicitly recommends.
4. Read the chosen skill's `SKILL.md` in full before acting.
5. Follow that skill's workflow exactly, while still obeying this `AGENTS.md` file.
6. If no skill clearly applies, say so briefly and proceed with the default git-first + verify workflow.

Default routing reminders:

- Broad explore/audit/investigation → use `explorer` and CodeGraph-first searches.
- Design/API shape before coding → route through the architect/pstack guidance.
- Bug/fix/prove-it work → route through fix-root-cause + prove-it/verification guidance.
- Streamlit or UI behavior changes → route through UI verification guidance, but ask before implementing visual/product changes.
- Wiki build/refresh work → use the project Pi wiki skills when the user asks to build/refresh/run the wiki.
- Ralph/autonomous loops → use the Pi Ralph or Cursor Ralph path exactly as routed.

Do not add Tavily, external search, cloud-agent, GTM/sales, PR/CI shipping, or other plugin/tool assumptions unless the router and the user's request explicitly call for them.

## Standard feature workflow

For any nontrivial feature, behavior change, or bug fix, follow this ordered pipeline. Each stage gates the next: do not start a stage until the previous one is complete and its output reviewed.

1. **Plan with OpenSpec.** Turn the idea into OpenSpec artifacts before writing code. Scaffold with `openspec new change <change-name>`, then author `proposal.md`, `design.md`, `specs/<capability>/spec.md`, and `tasks.md`. Validate with `openspec validate <change-name> --strict` and confirm `openspec status --change <change-name>` shows all artifacts complete. Plans are written, not improvised.
2. **Interrogate the plan.** Run the pstack `interrogate` skill (`/interrogate`) to spawn the four-model adversarial review over the proposal/design/specs (or the diff once code exists). Synthesize the verdict and resolve every "Act on" finding before implementing. Do not auto-apply reviewer suggestions; fold accepted findings back into the OpenSpec artifacts.
3. **Write the failing test first (TDD).** Use the pstack `tdd` skill (`/tdd`): for each task with a practical test path, add the narrowest regression test that encodes intended behavior and confirm it fails for the right reason before touching production code. If a failing test is impractical, say why and name the closest executable check instead.
4. **Implement with Ralph.** Drive the implementation through the **ralph-loop** plugin against the OpenSpec change, e.g.:

   ```
   /ralph-loop:ralph-loop "Implement spec {change-name} from openspec/changes/{change-name}/.
   Complete ALL tasks in tasks.md and satisfy every spec scenario.
   Output <promise>DONE</promise> when complete." --completion-promise "DONE" --max-iterations 30
   ```

   Mark `tasks.md` items complete as they land; keep the loop scoped to the change's tasks and specs.
5. **Deslop.** Run the cursor-team-kit `deslop` skill (`/deslop`) on the branch diff to strip AI-generated slop (redundant comments, abnormal defensive blocks, `any` casts, needless nesting) without changing behavior.
6. **Adversarial branch audit.** Delegate to the `thermo-nuclear-review-subagent` (via the Task tool) for a deep bugs/breaking-changes/security/feature-gate audit scoped to the diff. Resolve blocking findings.
7. **Verify the UI.** Use `agent-browser` to exercise the running app for any change that touches UI/behavior: navigate the affected flows, take screenshots, and confirm no new errors. For Streamlit/web specifics, pair with the UI verification guidance from the router.

This pipeline does not replace the mandatory git-first workflow, the approval boundary, or verification-before-completion rules above; it runs inside them. Skip a stage only when it is genuinely inapplicable (e.g., docs-only changes), and say so explicitly.

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

- Keep the repository root limited to **README.md**, **AGENTS.md**, **CLAUDE.md**, dependency manifests, `start.sh` / `stop.sh` / `status.sh`, and Ralph prompt seeds (`PROMPT_build.md`, `PROMPT_plan.md`).
- All other documentation lives under **`docs/`** — see [docs/README.md](docs/README.md).
- Planning: `docs/planning/work-index.md`, `history.md`, `implementation-plan.md`, `completion_log/`.
- Feature specs: `specs/`.
- UI simplification: `docs/planning/ui-simplification-plan.md`.

## Codebase layout

Product code is under `src/scrape_planner/` in domain subpackages:

- `core`, `scrape`, `pdf`, `sources`, `wiki`, `graph`, `index`, `tracer`, `runtime`, `ui`, `app`, `infra`

See `docs/CODEBASE.md` for the full module map.

## Ralph Wiggum

- For Ralph Wiggum/spec-driven autonomous loops, read `.specify/memory/constitution.md` first; it is the project-level Ralph source of truth.
- Queue and history: `docs/planning/work-index.md`, `docs/planning/history.md`, `docs/planning/implementation-plan.md`.
- The Pi-specific Ralph entrypoint is `scripts/ralph-loop-pi.sh`; Pi prompt templates are available as `/ralph-build` and `/ralph-plan` after `/reload`.
- For in-IDE Ralph loops, use the **ralph-loop** plugin (`ralph-loop` / `cancel-ralph` skills).
- Generic master prompt template: `docs/ralph/master-prompt.md`.

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

## Learned User Preferences

- The user expects a git-first workflow for all changes: status/diff first, small focused edits, verification, and scoped commits following GitHub hygiene.
- Do not add explanatory UI/code artifacts, such as diagrams, unless the user explicitly asks to implement them in the product.
- The user prefers concise, evidence-backed reports with clear “keep/remove/next action” recommendations.
- The user expects agents to choose skills by reading the skill router first, not by guessing or adding unrelated services/tools.
- The React/FastAPI app is the only operator UI; Streamlit is removed—do not reintroduce it. When asked to start the app, use `./start.sh` from the repo root (not `streamlit run app.py`).
- Prefer Pi skills (`.pi/skills/`) for operator workflows—URL discovery, curation, wiki compile, scrape planning—launched via tmux with `pi --mode json` for live event streaming into the UI. Keep FastAPI thin: job launch, artifact I/O, and validators only; avoid expanding deterministic regex/policy Python or inline LLM calls in API routes.
- For multi-step work, take autonomous end-to-end decisions following best practices and only ask the user when blocked or fully complete.
- Verify UI/operator changes with `agent-browser` on the running app before declaring work complete.
- Keep the operator UI minimal—show actionable status (Pi progress, jobs, embeddings, MCP) without clutter or debug-only panels.
- Prefer de-bloating (delete legacy modules, split god files, remove duplicate policy, lean production Docker/API images without CUDA or bundled local LLM wheels) over large deterministic hardening patch lists; use OpenSpec with agent-runtime boundaries before big changes.
- Keep public README and root docs professional—omit program credits, personal attribution, and informal sponsor lines.
- Student-facing answers must be cite-backed with low hallucination tolerance; URL discovery/curation must demote stale or outdated sources before scrape. When confidence is low, plan for web search plus self-improving source/wiki rebuild rather than guessing.

## Learned Workspace Facts

- The React/FastAPI app (`frontend/`, `src/scrape_planner/webapp/`) lives in this repo; webapp code is split (`routes.py`, `jobs.py`, `deps.py`, `schemas.py`, thin `api.py`). Streamlit (`app.py`, `ui_*.py`) has been removed. Run `./start.sh`, `./stop.sh`, and `./status.sh` from the repo root (tmux session `ultra-fast-rag-webapp`).
- Vite on port `5173`, backend API on port `8000`. Default data root is `data/` in this checkout (`SCRAPE_PLANNER_DATA_ROOT` optional).
- Legacy sibling worktree `/Users/abhsheno/Desktop/Projects/ultra-fast-rag-webapp` may still hold site artifacts until moved into `data/sites/` here; `start.sh` resolves populated data across worktrees when needed.
- Operator Pi jobs: `POST /api/sites/{site_id}/jobs` with `{ skill, prompt }` launches tmux + Pi; status via `GET /api/sites/{site_id}/jobs/{skill}`; catalog at `GET /api/operator/skills`. Registered skills include `site-discovery`, `site-url-curation`, and `llm-wiki-noninteractive`.
- `repo_root()` resolves via `start.sh` and `src/`, not `app.py`. `./scripts/verify-webapp.sh` is the primary webapp CI gate.
- OpenSpec `operator-agent-runtime` defines the Pi jobs API and skill registry (validated strict). `code-review-hardening` was interrogate-reviewed but should not be implemented as a deterministic patch list—fold reliability fixes into agent-runtime specs instead.
- Tmux operator sessions should auto-kill after a configurable grace period (~30 minutes default) post-execution; the React Settings pane should list active sessions with archive/stop, expose lifecycle settings, and provide MCP server start/stop controls.
- uops MCP is the local wiki-query MCP for Cursor testing; configure per `docs/cursor-mcp-setup.md` and `configs/cursor-mcp-llm-wiki.example.json` (not Playwright MCP).
- Legacy `markdown_graph` and root `scrape_planner/*.py` import shims are removed; use canonical subpackage imports (`wiki.*`, `scrape.*`, `core.*`). `docs/CODEBASE.md` is the module map.
- Production query/deploy uses OpenRouter/API LLMs and MCP over pre-built `data/sites/<site_id>/` wiki and hybrid indexes on a small host; Ollama, Docling, PDF ingest, scrape, and Pi jobs stay on the local operator path.
