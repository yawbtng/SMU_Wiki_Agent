from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OperatorRunStatus:
    state: str
    state_label: str
    primary_action: str
    attention_level: str
    message: str
    done: int
    total: int
    running: int
    failed: int
    queued: int


@dataclass(frozen=True)
class OperatorSourceStatus:
    readiness: str
    primary_count: int
    pdf_detail: str
    message: str
    selected_url_count: int
    pdf_count: int
    raw_source_count: int
    raw_ready_count: int
    raw_failed_count: int
    raw_review_count: int
    pdf_page_count: int
    pdf_chunk_count: int


def _label(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").strip().title()


def build_operator_run_status(
    *,
    state: str,
    done: int,
    total: int,
    running: int,
    failed: int,
    queued: int,
    has_live_runner: bool,
) -> OperatorRunStatus:
    normalized = (state or "none").strip().lower()
    if normalized in {"running", "pausing", "initializing"} and not has_live_runner:
        return OperatorRunStatus(
            state="paused",
            state_label="Paused",
            primary_action="Resume run",
            attention_level="warning",
            message="This run is paused in the UI. Resume it to continue from saved progress.",
            done=done,
            total=total,
            running=0,
            failed=failed,
            queued=queued,
        )
    if normalized == "running":
        return OperatorRunStatus(
            state="running",
            state_label="Running",
            primary_action="Monitor run",
            attention_level="active",
            message="Scrape is actively processing queued sources.",
            done=done,
            total=total,
            running=running,
            failed=failed,
            queued=queued,
        )
    if normalized == "initializing":
        return OperatorRunStatus(
            state="initializing",
            state_label="Initializing",
            primary_action="Monitor startup",
            attention_level="active",
            message="Scrape startup is preparing workers before queued sources begin processing.",
            done=done,
            total=total,
            running=running,
            failed=failed,
            queued=queued,
        )
    if normalized == "pausing":
        return OperatorRunStatus(
            state="pausing",
            state_label="Pausing",
            primary_action="Monitor run",
            attention_level="warning",
            message="Pause is in progress. Monitor the run until workers finish their current pages.",
            done=done,
            total=total,
            running=running,
            failed=failed,
            queued=queued,
        )
    if normalized in {"completed", "complete"}:
        return OperatorRunStatus(
            state="completed",
            state_label="Completed",
            primary_action="Review results",
            attention_level="ready",
            message="Scrape finished. Review failures and prepare corpus sources.",
            done=done,
            total=total,
            running=0,
            failed=failed,
            queued=queued,
        )
    return OperatorRunStatus(
        state=normalized,
        state_label=_label(normalized),
        primary_action="Start run" if total else "Add sources",
        attention_level="neutral",
        message="Run is ready to start." if total else "Add sources before starting a run.",
        done=done,
        total=total,
        running=running,
        failed=failed,
        queued=queued,
    )


def build_operator_source_status(
    *,
    selected_url_count: int,
    pdf_count: int,
    raw_source_count: int,
    raw_ready_count: int,
    raw_failed_count: int,
    raw_review_count: int,
    pdf_page_count: int,
    pdf_chunk_count: int,
) -> OperatorSourceStatus:
    pdf_noun = "PDF" if pdf_count == 1 else "PDFs"
    pdf_detail = f"{pdf_count:,} {pdf_noun}, {pdf_page_count:,} pages, {pdf_chunk_count:,} chunks"
    readiness = "ready" if raw_ready_count > 0 and raw_failed_count == 0 and raw_review_count == 0 else "not ready"
    message = "Normalize scraped pages, PDFs, or tabular files to prepare the corpus."
    if raw_source_count == 0 and pdf_page_count > 0:
        readiness = "partially prepared"
        message = "PDF extraction is ready; raw source normalization is still pending."
    elif raw_failed_count or raw_review_count:
        readiness = "needs review"
        message = "Some sources need review before wiki and retrieval work."
    elif readiness == "ready":
        message = "Prepared sources are ready for wiki and retrieval work."

    return OperatorSourceStatus(
        readiness=readiness,
        primary_count=selected_url_count,
        pdf_detail=pdf_detail,
        message=message,
        selected_url_count=selected_url_count,
        pdf_count=pdf_count,
        raw_source_count=raw_source_count,
        raw_ready_count=raw_ready_count,
        raw_failed_count=raw_failed_count,
        raw_review_count=raw_review_count,
        pdf_page_count=pdf_page_count,
        pdf_chunk_count=pdf_chunk_count,
    )
