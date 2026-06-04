# AI-Assisted App Development

Before building an AI-assisted app or substantial AI feature, prepare the planning packet first. Do not start implementation until the packet exists, is internally consistent, and has an explicit verification path.

## Required Planning Packet

Create or update these docs under `docs/planning/<change-name>/` or the matching `openspec/changes/<change-name>/` folder:

1. PRD (`prd.md`) - product problem, users, goals, non-goals, success metrics, rollout, and open questions.
2. `technical-architecture.md` - system boundaries, data flow, model/provider choices, APIs, storage, queues/jobs, observability, failure modes, and migration plan.
3. `security-access.md` - auth, authorization, secrets, data retention, prompt/data exposure, abuse controls, rate limits, audit logs, and dependency risks.
4. `frontend-spec.md` - target users, workflows, routes/views, states, empty/error/loading behavior, accessibility, responsive behavior, and UI verification plan.
5. `feature-tickets.md` - thin vertical tickets with acceptance criteria, affected files/modules, tests, smoke checks, and rollback notes.

## AI-Specific Requirements

- Name the source of truth for prompts, tools, model calls, retrieval/index inputs, and user-visible citations.
- Define deterministic boundaries: what code decides, what the model decides, and what must be validated after model output.
- Include cost, latency, retry, timeout, and fallback expectations.
- Include privacy boundaries for logs, traces, prompts, uploaded files, and generated artifacts.
- Include evaluation: fixtures, golden examples, hallucination checks, red-team cases, and production smoke paths.

## Ticket Rules

- Each ticket should be independently reviewable and commit-sized.
- Each ticket needs tests or an executable check before implementation starts.
- Frontend tickets include browser-smoke steps.
- Backend tickets include compile and focused pytest commands.
- Cross-cutting tickets call out integration points and rollback.

## Implementation Gate

Implementation may start only after:

- The planning packet exists.
- Open questions are either resolved or explicitly deferred.
- The first ticket has a narrow verification path.
- The branch name, GitHub issue/PR target, and owner context are clear.
