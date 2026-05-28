# Skill inventory reference

Complete list of installed plugin skills for lookup. Prefer the decision tables in `SKILL.md` for routing.

## pstack (32 skills)

| Skill | Use when |
|-------|----------|
| `poteto-mode` | Main engineering router (`/poteto-mode`) |
| `architect` | Design types/modules before code |
| `how` | Runtime behavior and call paths |
| `why` | Rationale, postmortems, thresholds |
| `arena` | Multi-model design comparison (via architect) |
| `interrogate` | Adversarial review of a design |
| `figure-it-out` | Unknown problem space; structured discovery |
| `reflect` | Mine transcript for skill improvements |
| `show-me-your-work` | Decision TSV for long runs |
| `tdd` | Explicit TDD or cheap regression |
| `unslop` | Strip AI tells from prose |
| `automate-me` | Draft personal mode skill from transcripts |
| `typescript-best-practices` | Editing `.ts` / `.tsx` (not primary for this Python repo) |
| `principle-prove-it-works` | Before declaring done |
| `principle-fix-root-causes` | Debugging |
| `principle-foundational-thinking` | Data structures before logic |
| `principle-laziness-protocol` | Smallest diff |
| `principle-subtract-before-you-add` | Remove dead weight first |
| `principle-minimize-reader-load` | Hard-to-trace code |
| `principle-boundary-discipline` | Validation at system edges |
| `principle-make-operations-idempotent` | Retry-safe operations |
| `principle-guard-the-context-window` | Large context; subagents |
| `principle-never-block-on-the-human` | Reversible work without asking |
| `principle-outcome-oriented-execution` | Migrations with phase boundaries |
| `principle-experience-first` | UX vs implementation convenience |
| `principle-exhaust-the-design-space` | Novel UI/architecture |
| `principle-redesign-from-first-principles` | New requirement on old design |
| `principle-migrate-callers-then-delete-legacy-apis` | API replacement |
| `principle-separate-before-serializing-shared-state` | Concurrent writers |
| `principle-encode-lessons-in-structure` | Repeated instructions → lint/check |
| `principle-build-the-lever` | Repetitive bulk → script/codemod |
| `principle-type-system-discipline` | Static types (secondary in Python repo) |

## ralph-loop (3)

`ralph-loop`, `cancel-ralph`, `ralph-loop-help`

## cursor-team-kit (18) — engineering subset bolded

**`verify-this`**, **`check-compiler-errors`**, **`deslop`**, **`control-ui`**, **`control-cli`**, `run-smoke-tests`, `thermo-nuclear-code-quality-review`, `workflow-from-chats`, `fix-ci`, `loop-on-ci`, `review-and-ship`, `new-branch-and-pr`, `get-pr-comments`, `make-pr-easy-to-review`, `fix-merge-conflicts`, `pr-review-canvas`, `what-did-i-get-done`, `weekly-review`

## thermos (3)

`thermos`, `thermo-nuclear-review`, `thermo-nuclear-code-quality-review`

## teaching (2)

`create-learning-path`, `run-learning-retrospective`

## Single-skill plugins

`cli-for-agents`, `check-agent-compatibility`, `continual-learning`

## Project / Pi

| Name | Location |
|------|----------|
| `llm-wiki-noninteractive` | `.pi/skills/llm-wiki-noninteractive/` |
| `skill-router` | `.cursor/skills/skill-router/` |
