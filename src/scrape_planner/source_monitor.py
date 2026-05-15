from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


LIFECYCLE_STATUSES = {
    "new",
    "unchanged",
    "changed",
    "redirected",
    "failed",
    "deleted_candidate",
}


@dataclass
class SourceObservation:
    """Current source observation used by the classifier.

    - url is required
    - content is required when success=True
    - error is required when success=False
    """

    observed_at: str
    url: str
    success: bool
    content: str | None = None
    canonical_url: str | None = None
    http_status: int | None = None
    error: str | None = None


@dataclass
class SourceLedgerRow:
    """Durable source ledger row consumed by downstream slices.

    source_id and content_hash are stable contracts used by S02/S03.
    """

    source_id: str
    url: str
    canonical_url: str
    status: str
    first_seen_at: str
    last_seen_at: str
    last_observed_at: str
    content_hash: str | None = None
    last_success_at: str | None = None
    last_changed_at: str | None = None
    consecutive_failures: int = 0
    consecutive_missing: int = 0
    failure_reason: str | None = None
    http_status: int | None = None


@dataclass
class SourceDiffRow:
    """Per-run lifecycle diff row for source_diff.jsonl."""

    observed_at: str
    source_id: str
    url: str
    canonical_url: str
    status: str
    previous_hash: str | None
    current_hash: str | None
    previous_canonical_url: str | None
    current_canonical_url: str | None
    http_status: int | None
    error: str | None


@dataclass
class SourceMonitorConfig:
    """Conservative deletion-candidate thresholds.

    Rows are never removed in this phase; they are only classified.
    """

    delete_candidate_after_failures: int = 3
    delete_candidate_after_missing: int = 2


def normalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("url is required")

    split = urlsplit(raw)
    if not split.scheme or not split.netloc:
        raise ValueError(f"invalid url: {raw}")

    scheme = split.scheme.lower()
    host = split.netloc.lower()
    path = split.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query_pairs = parse_qsl(split.query, keep_blank_values=True)
    query = urlencode(sorted(query_pairs)) if query_pairs else ""
    fragment = ""
    return urlunsplit((scheme, host, path, query, fragment))


def source_id_for_url(url: str) -> str:
    canonical = normalize_url(url)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"src_{digest}"


def content_hash_for_text(content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _validate_timestamp(ts: str) -> None:
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception as exc:  # pragma: no cover - explicit error path
        raise ValueError(f"invalid timestamp: {ts}") from exc


def _validate_observation(observation: SourceObservation) -> None:
    _validate_timestamp(observation.observed_at)
    if not observation.url:
        raise ValueError("observation.url is required")
    if observation.success:
        if observation.content is None:
            raise ValueError("successful observation requires content")
    else:
        if not observation.error:
            raise ValueError("failed observation requires error")


def load_ledger_jsonl(path: Path) -> dict[str, SourceLedgerRow]:
    if not path.exists():
        return {}

    rows: dict[str, SourceLedgerRow] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid ledger jsonl at line {line_no}") from exc

            row = SourceLedgerRow(**payload)
            rows[row.source_id] = row

    return rows


def ledger_rows_to_jsonl(rows: list[SourceLedgerRow]) -> list[str]:
    ordered = sorted(rows, key=lambda row: row.source_id)
    return [json.dumps(asdict(row), ensure_ascii=True, sort_keys=True) for row in ordered]


def _is_missing_status(http_status: int | None) -> bool:
    return http_status in {404, 410}


def classify_observations(
    previous_ledger: dict[str, SourceLedgerRow],
    observations: list[SourceObservation],
    config: SourceMonitorConfig | None = None,
) -> tuple[list[SourceLedgerRow], list[SourceDiffRow], dict[str, int]]:
    cfg = config or SourceMonitorConfig()
    next_ledger = {k: SourceLedgerRow(**asdict(v)) for k, v in previous_ledger.items()}
    diffs: list[SourceDiffRow] = []
    counts = {status: 0 for status in LIFECYCLE_STATUSES}
    observed_ids: set[str] = set()

    for obs in observations:
        _validate_observation(obs)
        canonical_url = normalize_url(obs.canonical_url or obs.url)
        source_id = source_id_for_url(obs.url)
        observed_ids.add(source_id)

        prior = next_ledger.get(source_id)
        previous_hash = prior.content_hash if prior else None
        previous_canonical = prior.canonical_url if prior else None

        if obs.success:
            current_hash = content_hash_for_text(obs.content or "")
            status = "new"
            if prior:
                status = "unchanged" if prior.content_hash == current_hash else "changed"
                if prior.canonical_url != canonical_url and status == "unchanged":
                    status = "redirected"
            elif obs.canonical_url and normalize_url(obs.url) != canonical_url:
                status = "redirected"

            first_seen_at = prior.first_seen_at if prior else obs.observed_at
            last_changed_at = obs.observed_at if (not prior or prior.content_hash != current_hash) else prior.last_changed_at

            next_ledger[source_id] = SourceLedgerRow(
                source_id=source_id,
                url=obs.url,
                canonical_url=canonical_url,
                status="active",
                first_seen_at=first_seen_at,
                last_seen_at=obs.observed_at,
                last_observed_at=obs.observed_at,
                content_hash=current_hash,
                last_success_at=obs.observed_at,
                last_changed_at=last_changed_at,
                consecutive_failures=0,
                consecutive_missing=0,
                failure_reason=None,
                http_status=obs.http_status,
            )
        else:
            failure_count = (prior.consecutive_failures if prior else 0) + 1
            missing_count = (prior.consecutive_missing if prior else 0) + (1 if _is_missing_status(obs.http_status) else 0)
            status = "failed"
            if (
                failure_count >= cfg.delete_candidate_after_failures
                or missing_count >= cfg.delete_candidate_after_missing
            ):
                status = "deleted_candidate"

            first_seen_at = prior.first_seen_at if prior else obs.observed_at
            preserved_hash = prior.content_hash if prior else None
            preserved_success = prior.last_success_at if prior else None
            last_changed_at = prior.last_changed_at if prior else None

            next_ledger[source_id] = SourceLedgerRow(
                source_id=source_id,
                url=obs.url,
                canonical_url=canonical_url,
                status=status,
                first_seen_at=first_seen_at,
                last_seen_at=prior.last_seen_at if prior else obs.observed_at,
                last_observed_at=obs.observed_at,
                content_hash=preserved_hash,
                last_success_at=preserved_success,
                last_changed_at=last_changed_at,
                consecutive_failures=failure_count,
                consecutive_missing=missing_count,
                failure_reason=obs.error,
                http_status=obs.http_status,
            )
            current_hash = preserved_hash

        counts[status] += 1
        diffs.append(
            SourceDiffRow(
                observed_at=obs.observed_at,
                source_id=source_id,
                url=obs.url,
                canonical_url=canonical_url,
                status=status,
                previous_hash=previous_hash,
                current_hash=current_hash,
                previous_canonical_url=previous_canonical,
                current_canonical_url=canonical_url,
                http_status=obs.http_status,
                error=obs.error,
            )
        )

    for source_id, prior in list(next_ledger.items()):
        if source_id in observed_ids:
            continue

        missing_count = prior.consecutive_missing + 1
        failure_count = prior.consecutive_failures + 1
        status = "failed"
        if (
            failure_count >= cfg.delete_candidate_after_failures
            or missing_count >= cfg.delete_candidate_after_missing
        ):
            status = "deleted_candidate"

        next_ledger[source_id] = SourceLedgerRow(
            source_id=prior.source_id,
            url=prior.url,
            canonical_url=prior.canonical_url,
            status=status,
            first_seen_at=prior.first_seen_at,
            last_seen_at=prior.last_seen_at,
            last_observed_at=prior.last_observed_at,
            content_hash=prior.content_hash,
            last_success_at=prior.last_success_at,
            last_changed_at=prior.last_changed_at,
            consecutive_failures=failure_count,
            consecutive_missing=missing_count,
            failure_reason="missing from current observation set",
            http_status=prior.http_status,
        )
        counts[status] += 1
        diffs.append(
            SourceDiffRow(
                observed_at=prior.last_observed_at,
                source_id=prior.source_id,
                url=prior.url,
                canonical_url=prior.canonical_url,
                status=status,
                previous_hash=prior.content_hash,
                current_hash=prior.content_hash,
                previous_canonical_url=prior.canonical_url,
                current_canonical_url=prior.canonical_url,
                http_status=prior.http_status,
                error="missing from current observation set",
            )
        )

    return sorted(next_ledger.values(), key=lambda row: row.source_id), diffs, counts
