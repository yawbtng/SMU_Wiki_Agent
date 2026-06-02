# Documentation

Project documentation lives here. The repository root stays limited to **README**, **AGENTS**, agent entrypoints, and Ralph prompt seeds.

## Start here

| Doc | Audience | Contents |
| --- | --- | --- |
| [../README.md](../README.md) | Everyone | Quickstart, operator workflow, MCP, Docker, production query |
| [CODEBASE.md](CODEBASE.md) | Developers | Module map under `src/scrape_planner/` |
| [cursor-mcp-setup.md](cursor-mcp-setup.md) | Cursor users | Install and smoke-test the llm-wiki MCP server |

## Operator and production

| Doc | Contents |
| --- | --- |
| [cursor-mcp-setup.md](cursor-mcp-setup.md) | Local and production MCP wiring |
| [llm-wiki-stepper-runbook.md](llm-wiki-stepper-runbook.md) | Wiki build / index stepper operations |
| [raw-sources-artifact-audit.md](raw-sources-artifact-audit.md) | Source artifact layout and contracts |
| [migration/streamlit-to-fastapi-react-audit.md](migration/streamlit-to-fastapi-react-audit.md) | Streamlit → React/FastAPI migration notes |

## Planning and specs

| Doc | Contents |
| --- | --- |
| [planning/work-index.md](planning/work-index.md) | Ralph queue, stop rule, completion ledger |
| [planning/implementation-plan.md](planning/implementation-plan.md) | Prioritized Ralph task breakdown (planning mode) |
| [planning/history.md](planning/history.md) | One-line log after each completed spec |
| [planning/completion_log/](planning/completion_log/) | Timestamped completion notes |
| [planning/pdf-extraction-blueprint.md](planning/pdf-extraction-blueprint.md) | PDF page-probe and Docling/PyMuPDF design |
| [planning/ui-simplification-plan.md](planning/ui-simplification-plan.md) | Operator UI simplification (React-era) |
| [../specs/](../specs/) | Feature specifications and acceptance criteria |

## OpenSpec and agents

| Doc | Contents |
| --- | --- |
| [openspec/opsx-quickstart.md](openspec/opsx-quickstart.md) | OpenSpec change workflow (`openspec/changes/`) |
| [ralph/master-prompt.md](ralph/master-prompt.md) | Generic Ralph master prompt template |
| [../.specify/memory/constitution.md](../.specify/memory/constitution.md) | Project Ralph constitution |
| [../AGENTS.md](../AGENTS.md) | Agent operating guide |

## Audits and archive

| Doc | Contents |
| --- | --- |
| [audit/mcp-retrieval-workflow-analysis.md](audit/mcp-retrieval-workflow-analysis.md) | MCP retrieval and confidence-gating deep dive |
| [archive/streamlit/simple-ui-cleanup-plan.md](archive/streamlit/simple-ui-cleanup-plan.md) | Legacy Streamlit UI plan (historical) |
| [superpowers/](superpowers/) | Older design/planning notes (reference) |

## Related trees

- `openspec/changes/` — active OpenSpec change proposals and tasks
- `.pi/skills/` — Pi operator skills (discovery, curation, wiki build)
