# OpenSpec workflow (opsx)

Use OpenSpec when a feature needs a written proposal, design, specs, and tasks before code lands.

## Commands (conceptual)

| Step | Action |
| --- | --- |
| Explore | Investigate options; do not implement product code |
| Propose | Scaffold `openspec/changes/<change-name>/` with `proposal.md`, `design.md`, `specs/`, `tasks.md` |
| Apply | Implement from `tasks.md`; mark tasks complete as you go |
| Archive | After validation, move the change under `openspec/changes/archive/` |

CLI (when installed):

```bash
openspec new change <change-name>
openspec validate <change-name> --strict
openspec status --change <change-name>
```

## Active changes (check repo for current list)

```bash
ls openspec/changes/
```

Examples in this repository:

- `operator-agent-runtime` — Pi jobs API and skill registry
- `streamlit-removal-debloat` — React-only operator surface
- `code-review-hardening` — reliability specs (prefer folding fixes into agent-runtime where possible)

See `AGENTS.md` for the full feature pipeline (OpenSpec → interrogate → TDD → Ralph → verify).
