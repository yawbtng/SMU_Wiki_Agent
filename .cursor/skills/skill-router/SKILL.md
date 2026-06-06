---
name: skill-router
description: >-
  Routes agents to the right skill for ultra-fast-rag. Use at the start of
  nontrivial work, when unsure which skill applies, when the user asks
  "which skill", or before picking a workflow. Covers installed Cursor plugins,
  project Pi skills, Ralph modes, verification, exploration, and teaching.
---

# Skill Router

Pick **one primary skill** (or a short chain), then read that skill's `SKILL.md` in full before acting.

## Quick decision

```
User intent unclear or multi-step?
  → Read this skill, then /poteto-mode (pstack router for rigorous engineering)

Autonomous spec/build loop?
  → Pi: scripts/ralph-loop-pi.sh + .specify/memory/constitution.md
  → Cursor IDE: ralph-loop skill (cancel with cancel-ralph)

Wiki build/refresh non-interactively?
  → .pi/skills/llm-wiki-noninteractive (Pi only)

Broad explore / audit / "how does X work"?
  → Subagents + codegraph (AGENTS.md Exploration Preference)
  → rtk for noisy shell output when exact raw output is not required
  → pstack how skill for traced runtime model
  → teaching create-learning-path if user wants to learn the area

Design before code (cross-module, new API shape)?
  → pstack architect

Bug or "prove it works"?
  → pstack principle-fix-root-causes + principle-prove-it-works
  → cursor-team-kit verify-this for falsifiable before/after evidence

About to declare done?
  → check-compiler-errors → principle-prove-it-works → verify-this (if claim is measurable)

Streamlit / web UI change?
  → cursor-team-kit control-ui

Shell script / CLI change?
  → cli-for-agent (+ control-cli if interactive TUI)

Deep review of a large diff?
  → thermos (both review subagents)

Repo agent-readiness audit?
  → agent-compatibility check-agent-compatibility

Learning a codebase area over time?
  → teaching create-learning-path, then run-learning-retrospective

Long unattended run?
  → pstack show-me-your-work (decision TSV) + ralph-loop or ralph-loop-pi.sh

Clean AI slop from a diff?
  → cursor-team-kit deslop

Explicit TDD / regression test request?
  → pstack tdd
```

## By task type

| Task | Primary skill | Also consider |
|------|---------------|---------------|
| New feature / behavior change | `/poteto-mode` (feature playbook) | `architect`, `principle-foundational-thinking` |
| Refactor (same behavior) | `/poteto-mode` (refactoring playbook) | `principle-laziness-protocol`, `deslop` |
| Investigation (read-only) | `/poteto-mode` (investigation) or `how` | subagents, `codegraph` |
| Performance | `/poteto-mode` (perf playbook) | `verify-this` with baseline/treatment |
| Wiki ingest / index pipeline | `llm-wiki-noninteractive` | `cli-for-agent`, `principle-make-operations-idempotent` |
| Spec-driven Ralph build | `ralph-loop` (IDE) or Pi `ralph-loop-pi.sh` | constitution, `show-me-your-work` |
| Verify a specific claim | `verify-this` | `principle-prove-it-works` |
| Syntax / compile / pytest gate | `check-compiler-errors` | project tests under `tests/` |
| UI smoke / repro | `control-ui` | Streamlit `app.py` |
| CLI harness / Ralph scripts | `control-cli` | `cli-for-agent` |
| Harsh maintainability audit | `thermo-nuclear-code-quality-review` or `thermos` | — |
| Security / correctness audit | `thermo-nuclear-review` or `thermos` | — |
| Learn a subsystem | `create-learning-path` | `how`, `run-learning-retrospective` |
| Update AGENTS.md from chats | `continual-learning` | hook-driven; do not run manually unless asked |

## Project-specific (this repo)

| Skill | Path | When |
|-------|------|------|
| **cursor-agent-handoff** | `.cursor/skills/cursor-agent-handoff/` | Codex manager-only: delegate implementation to Cursor Agent in trusted workspace `/Users/abhsheno/Desktop/Projects/ultra-fast-rag` |
| **llm-wiki-noninteractive** | `.pi/skills/llm-wiki-noninteractive/` | Non-interactive wiki rebuild/resume from Pi |
| **constitution** | `.specify/memory/constitution.md` | Ralph loop mode, specs, autonomy rules |
| **skill-router** | `.cursor/skills/skill-router/` | This file — routing only |

## Installed plugins (`~/.cursor/plugins/local/`)

### pstack — engineering router and principles

| Invoke | When |
|--------|------|
| **`/poteto-mode`** | Default for nontrivial engineering; picks playbook internally |
| **`architect`** | Cross-boundary design; types/signatures before implementation |
| **`how`** | Runtime behavior, call paths, "what happens when" |
| **`why`** | Design rationale, regressions, postmortems |
| **`show-me-your-work`** | Long/autonomous runs; TSV decision log |
| **`principle-prove-it-works`** | Before declaring any task done |
| **`principle-fix-root-causes`** | Debugging; no nil-guard band-aids |
| **`principle-make-operations-idempotent`** | Rebuild/resume pipelines, retry-safe commands |
| **`principle-guard-the-context-window`** | Large exploration; fan out to subagents |
| **`principle-laziness-protocol`** | Refactors; smallest diff that works |
| **`tdd`** | Only when user asks for TDD or obvious cheap regression target |
| **`deslop`** (via poteto-mode) | Before finishing; strips AI slop |

Full principle list: see `reference.md` in this skill directory.

### ralph-loop — Cursor IDE iteration

| Skill | When |
|-------|------|
| **`ralph-loop`** | User wants repeated IDE iterations until `<promise>` met |
| **`cancel-ralph`** | Stop an active loop |
| **`ralph-loop-help`** | Explain the technique |

State: `.cursor/ralph/scratchpad.md`. Does **not** replace Pi `scripts/ralph-loop-pi.sh`.

### cursor-team-kit — engineering subset only

| Use | Skip unless user asks |
|-----|------------------------|
| `verify-this`, `check-compiler-errors`, `deslop`, `control-ui`, `control-cli` | `fix-ci`, `loop-on-ci`, `review-and-ship`, `new-branch-and-pr`, `get-pr-comments`, `make-pr-easy-to-review`, `fix-merge-conflicts`, `pr-review-canvas`, `what-did-i-get-done`, `weekly-review` |

### thermos — deep branch review

| Skill | When |
|-------|------|
| **`thermos`** | Combined security + code-quality audit (parallel subagents) |
| **`thermo-nuclear-review`** | Bugs, breaking changes, security, feature gates |
| **`thermo-nuclear-code-quality-review`** | Maintainability, giant files, spaghetti |

### Other plugins

| Plugin | Skill | When |
|--------|-------|------|
| **cli-for-agent** | `cli-for-agents` | New flags, `--help`, idempotent/dry-run CLI design |
| **agent-compatibility** | `check-agent-compatibility` | Score repo agent-readiness; startup/validation/docs |
| **continual-learning** | `continual-learning` | Hook triggers; mines transcripts → `AGENTS.md` |
| **teaching** | `create-learning-path` | Structured learning roadmap for a topic |
| **teaching** | `run-learning-retrospective` | Review progress; adjust the plan |

## Do not use (unless explicitly requested)

- **founder-gtm** — sales/outbound
- **orchestrate**, **cursor-sdk** — cloud agent automation
- **cursor-team-kit** git/PR/CI skills — user is not focused on commits/PRs

## Typical chains

**Feature in wiki pipeline**
1. `/poteto-mode` or `architect`
2. implement
3. `check-compiler-errors`
4. `llm-wiki-noninteractive` or manual smoke query
5. `principle-prove-it-works`

**Autonomous spec item**
1. Read constitution + highest-priority incomplete spec in `specs/`
2. `ralph-loop` (IDE) or `ralph-loop-pi.sh` (Pi)
3. `show-me-your-work` for decision trail
4. `principle-prove-it-works` before `<promise>DONE</promise>`

**"Is this repo agent-friendly?"**
1. `check-agent-compatibility`
2. Fix top items from the score report

## Output when routing

When this skill is invoked explicitly, respond with:

1. **Recommended skill(s)** — primary + optional chain
2. **Why** — one line each
3. **Next step** — read named skill's `SKILL.md`, then act

Do not implement the underlying task until the chosen skill is loaded.
