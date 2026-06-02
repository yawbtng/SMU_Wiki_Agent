"""Scrape planner — categorized subpackages for the Ultra Fast RAG pipeline.

Subpackages
-----------
core      Shared models, storage, data paths, site layout
scrape    Discovery, fetch, HTML extraction, scrape worker
pdf       PDF contracts and Docling ingest
sources   Raw source registry, normalization, quality
wiki      LLM wiki build, hybrid index, ingestion pipeline
index     Embedding / vector indexes
tracer    Stale-page evaluation and maintenance
runtime   Run queue, persistence, analytics, observability
app       App context, repositories, artifact contracts, webapp
infra     tmux and other process runners

See docs/CODEBASE.md for the full module map.
"""

from .tracer_dependencies import (
    StaleEvaluationResult,
    StaleTransitionRecord,
    evaluate_stale_dependencies,
)

__all__ = [
    "evaluate_stale_dependencies",
    "StaleTransitionRecord",
    "StaleEvaluationResult",
]
