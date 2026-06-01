from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

CostSource = Literal["reported", "estimated", "unknown", "partial", "mixed"]
TerminalStatus = Literal["completed", "failed", "canceled", "cancelled"]

STANDARD_WINDOWS: tuple[str, ...] = ("30d", "60d", "90d", "365d")
_LOCK = Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sum_known(values: list[int | None]) -> int | None:
    known = [value for value in values if value is not None]
    if not known and values:
        return None
    return int(sum(known))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        tmp_path.replace(path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


@dataclass(frozen=True)
class MetricCost:
    amount_usd: float | None = None
    source: CostSource = "unknown"


@dataclass(frozen=True)
class LlmUsageSummary:
    request_count: int = 0
    prompt_tokens: int | None = 0
    completion_tokens: int | None = 0
    total_tokens: int | None = 0
    retry_count: int = 0
    latency_ms: int = 0
    cost: MetricCost = field(default_factory=MetricCost)


@dataclass(frozen=True)
class EmbeddingUsageSummary:
    request_count: int = 0
    input_tokens: int | None = 0
    document_count: int = 0
    chunk_count: int = 0
    vector_count: int = 0
    reused_vector_count: int = 0
    skipped_chunk_count: int = 0
    failed_chunk_count: int = 0
    duration_ms: int = 0
    cost: MetricCost = field(default_factory=MetricCost)


@dataclass(frozen=True)
class AgentRunSummary:
    run_id: str
    site_id: str
    status: str
    started_at: str | None
    completed_at: str | None
    duration_ms: int
    event_count: int
    total_model_tokens: int | None
    llm_usage: LlmUsageSummary
    embedding_usage: EmbeddingUsageSummary
    cost: MetricCost
    breakdowns: dict[str, Any]
    metrics_health: dict[str, Any]


def build_llm_metric_event(
    *,
    run_id: str,
    site_id: str,
    timestamp: str | None = None,
    stage: str,
    operation: str,
    provider: str,
    model: str,
    status: str = "success",
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    latency_ms: int | None = None,
    retry_count: int = 0,
    cost_usd: float | None = None,
    cost_source: CostSource = "unknown",
    raw_provider_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens
    return {
        "event_id": f"evt_{uuid4().hex}",
        "run_id": run_id,
        "site_id": site_id,
        "timestamp": timestamp or _utc_now_iso(),
        "stage": stage,
        "operation": operation,
        "provider": provider,
        "model": model,
        "status": status,
        "event_type": "llm",
        "metrics": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "latency_ms": latency_ms,
            "retry_count": retry_count,
            "cost_usd": cost_usd,
            "cost_source": cost_source,
        },
        "raw_provider_usage": raw_provider_usage or {},
    }


def build_embedding_metric_event(
    *,
    run_id: str,
    site_id: str,
    timestamp: str | None = None,
    stage: str,
    operation: str,
    provider: str,
    model: str,
    status: str = "success",
    input_tokens: int | None = None,
    document_count: int = 0,
    chunk_count: int = 0,
    vector_count: int = 0,
    reused_vector_count: int = 0,
    skipped_chunk_count: int = 0,
    failed_chunk_count: int = 0,
    duration_ms: int | None = None,
    cost_usd: float | None = None,
    cost_source: CostSource = "unknown",
    raw_provider_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_id": f"evt_{uuid4().hex}",
        "run_id": run_id,
        "site_id": site_id,
        "timestamp": timestamp or _utc_now_iso(),
        "stage": stage,
        "operation": operation,
        "provider": provider,
        "model": model,
        "status": status,
        "event_type": "embedding",
        "metrics": {
            "input_tokens": input_tokens,
            "document_count": document_count,
            "chunk_count": chunk_count,
            "vector_count": vector_count,
            "reused_vector_count": reused_vector_count,
            "skipped_chunk_count": skipped_chunk_count,
            "failed_chunk_count": failed_chunk_count,
            "duration_ms": duration_ms,
            "cost_usd": cost_usd,
            "cost_source": cost_source,
        },
        "raw_provider_usage": raw_provider_usage or {},
    }


class AgentRunMetricsRepository:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root)

    def site_metrics_root(self, site_id: str) -> Path:
        return self.data_root / "sites" / str(site_id) / "metrics"

    def raw_events_path(self, site_id: str) -> Path:
        return self.site_metrics_root(site_id) / "events.jsonl"

    def run_summary_path(self, site_id: str, run_id: str) -> Path:
        return self.site_metrics_root(site_id) / "runs" / f"{run_id}.json"

    def append_event(self, event: dict[str, Any]) -> None:
        site_id = str(event.get("site_id") or "").strip()
        run_id = str(event.get("run_id") or "").strip()
        if not site_id:
            raise ValueError("metrics event requires site_id")
        if not run_id:
            raise ValueError("metrics event requires run_id")
        payload = dict(event)
        payload.setdefault("event_id", f"evt_{uuid4().hex}")
        payload.setdefault("timestamp", _utc_now_iso())
        payload.setdefault("metrics", {})
        _append_jsonl(self.raw_events_path(site_id), payload)

    def read_events(self, site_id: str, run_id: str | None = None) -> list[dict[str, Any]]:
        rows = _read_jsonl(self.raw_events_path(site_id))
        if run_id is None:
            return rows
        return [row for row in rows if str(row.get("run_id") or "") == run_id]

    def read_run_summary(self, site_id: str, run_id: str) -> dict[str, Any]:
        payload = _read_json(self.run_summary_path(site_id, run_id), {})
        return payload if isinstance(payload, dict) else {}

    def list_run_summaries(self, site_id: str) -> list[dict[str, Any]]:
        summaries_dir = self.site_metrics_root(site_id) / "runs"
        if not summaries_dir.exists():
            return []
        rows: list[dict[str, Any]] = []
        for path in sorted(summaries_dir.glob("*.json")):
            payload = _read_json(path, {})
            if isinstance(payload, dict) and payload.get("run_id"):
                rows.append(payload)
        return sorted(rows, key=lambda row: str(row.get("started_at") or ""), reverse=True)

    def rebuild_run_summary(
        self,
        site_id: str,
        run_id: str,
        *,
        status: str = "unknown",
        trigger: str | None = None,
        agent_mode: str | None = None,
    ) -> dict[str, Any]:
        events = self.read_events(site_id, run_id)
        summary = _build_run_summary(
            site_id=site_id,
            run_id=run_id,
            events=events,
            status=status,
            trigger=trigger,
            agent_mode=agent_mode,
        )
        payload = _summary_to_dict(summary)
        _write_json_atomic(self.run_summary_path(site_id, run_id), payload)
        return payload

    def build_rollups(
        self,
        site_id: str,
        *,
        windows: tuple[str, ...] = STANDARD_WINDOWS,
        as_of: str | datetime | None = None,
        include_all_time: bool = False,
    ) -> dict[str, dict[str, Any]]:
        summaries = self.list_run_summaries(site_id)
        now = _parse_ts(as_of) or datetime.now(timezone.utc)
        results: dict[str, dict[str, Any]] = {}
        for window in windows:
            days = _window_days(window)
            cutoff = None if days is None else now.timestamp() - (days * 86400)
            selected = [summary for summary in summaries if _summary_in_window(summary, cutoff)]
            results[window] = _aggregate_summaries(window, selected)
        if include_all_time:
            results["all_time"] = _aggregate_summaries("all_time", summaries)
        return results


def _build_run_summary(
    *,
    site_id: str,
    run_id: str,
    events: list[dict[str, Any]],
    status: str,
    trigger: str | None,
    agent_mode: str | None,
) -> AgentRunSummary:
    timestamps = [_parse_ts(event.get("timestamp") or event.get("ts")) for event in events if isinstance(event, dict)]
    valid_ts = [ts for ts in timestamps if ts is not None]
    started = min(valid_ts) if valid_ts else None
    completed = max(valid_ts) if valid_ts else None
    duration_ms = int((completed.timestamp() - started.timestamp()) * 1000) if started and completed else 0

    llm_events = [event for event in events if _event_type(event) == "llm"]
    embedding_events = [event for event in events if _event_type(event) == "embedding"]
    warnings: set[str] = set()
    llm_usage = _summarize_llm_usage(llm_events, warnings)
    embedding_usage = _summarize_embedding_usage(embedding_events, warnings)
    total_model_tokens = _combine_optional_ints(llm_usage.total_tokens, embedding_usage.input_tokens)
    cost = _combine_costs([llm_usage.cost, embedding_usage.cost], warnings)
    breakdowns = _build_breakdowns(events)

    return AgentRunSummary(
        run_id=run_id,
        site_id=site_id,
        status=status,
        started_at=started.isoformat().replace("+00:00", "Z") if started else None,
        completed_at=completed.isoformat().replace("+00:00", "Z") if completed else None,
        duration_ms=duration_ms,
        event_count=len(events),
        total_model_tokens=total_model_tokens,
        llm_usage=llm_usage,
        embedding_usage=embedding_usage,
        cost=cost,
        breakdowns={
            **breakdowns,
            "trigger": trigger,
            "agent_mode": agent_mode,
        },
        metrics_health={
            "status": "partial" if warnings else "complete",
            "warnings": sorted(warnings),
        },
    )


def _event_type(event: dict[str, Any]) -> str:
    explicit = str(event.get("event_type") or "").strip().lower()
    if explicit:
        return explicit
    operation = str(event.get("operation") or "").lower()
    if "embed" in operation:
        return "embedding"
    return "llm"


def _metrics(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("metrics")
    if isinstance(value, dict):
        return value
    return event


def _summarize_llm_usage(events: list[dict[str, Any]], warnings: set[str]) -> LlmUsageSummary:
    prompt_tokens = [_to_int(_metrics(event).get("prompt_tokens")) for event in events]
    completion_tokens = [_to_int(_metrics(event).get("completion_tokens")) for event in events]
    total_tokens = [_to_int(_metrics(event).get("total_tokens")) for event in events]
    for idx, total in enumerate(total_tokens):
        if total is None and prompt_tokens[idx] is not None and completion_tokens[idx] is not None:
            total_tokens[idx] = prompt_tokens[idx] + completion_tokens[idx]
    if events and any(value is None for value in total_tokens):
        warnings.add("missing_llm_tokens")
    cost = _cost_from_events(events, warnings)
    return LlmUsageSummary(
        request_count=len(events),
        prompt_tokens=_sum_known(prompt_tokens),
        completion_tokens=_sum_known(completion_tokens),
        total_tokens=_sum_known(total_tokens),
        retry_count=sum(_to_int(_metrics(event).get("retry_count")) or 0 for event in events),
        latency_ms=sum(_to_int(_metrics(event).get("latency_ms")) or 0 for event in events),
        cost=cost,
    )


def _summarize_embedding_usage(events: list[dict[str, Any]], warnings: set[str]) -> EmbeddingUsageSummary:
    input_tokens = [_to_int(_metrics(event).get("input_tokens")) for event in events]
    if events and any(value is None for value in input_tokens):
        warnings.add("missing_embedding_tokens")
    cost = _cost_from_events(events, warnings)
    return EmbeddingUsageSummary(
        request_count=len(events),
        input_tokens=_sum_known(input_tokens),
        document_count=sum(_to_int(_metrics(event).get("document_count")) or 0 for event in events),
        chunk_count=sum(_to_int(_metrics(event).get("chunk_count")) or 0 for event in events),
        vector_count=sum(_to_int(_metrics(event).get("vector_count")) or 0 for event in events),
        reused_vector_count=sum(_to_int(_metrics(event).get("reused_vector_count")) or 0 for event in events),
        skipped_chunk_count=sum(_to_int(_metrics(event).get("skipped_chunk_count")) or 0 for event in events),
        failed_chunk_count=sum(_to_int(_metrics(event).get("failed_chunk_count")) or 0 for event in events),
        duration_ms=sum(_to_int(_metrics(event).get("duration_ms")) or 0 for event in events),
        cost=cost,
    )


def _cost_from_events(events: list[dict[str, Any]], warnings: set[str]) -> MetricCost:
    costs: list[float] = []
    sources: set[str] = set()
    unknown = False
    for event in events:
        metrics = _metrics(event)
        amount = _to_float(metrics.get("cost_usd"))
        source = str(metrics.get("cost_source") or "unknown")
        if amount is None or source == "unknown":
            unknown = True
            continue
        costs.append(amount)
        sources.add(source)
    if unknown and events:
        warnings.add("unknown_cost")
    if not costs:
        return MetricCost(None, "unknown")
    if unknown:
        return MetricCost(round(sum(costs), 8), "partial")
    if len(sources) == 1 and next(iter(sources)) in {"reported", "estimated"}:
        return MetricCost(round(sum(costs), 8), next(iter(sources)))  # type: ignore[arg-type]
    return MetricCost(round(sum(costs), 8), "mixed")


def _combine_costs(costs: list[MetricCost], warnings: set[str]) -> MetricCost:
    known = [cost for cost in costs if cost.amount_usd is not None]
    if len(known) != len(costs):
        warnings.add("unknown_cost")
    if not known:
        return MetricCost(None, "unknown")
    amount = round(sum(float(cost.amount_usd or 0.0) for cost in known), 8)
    sources = {cost.source for cost in known}
    if len(known) != len(costs):
        return MetricCost(amount, "partial")
    if len(sources) == 1 and next(iter(sources)) in {"reported", "estimated"}:
        return MetricCost(amount, next(iter(sources)))  # type: ignore[arg-type]
    return MetricCost(amount, "mixed")


def _combine_optional_ints(*values: int | None) -> int | None:
    known = [value for value in values if value is not None]
    if not known and any(value is None for value in values):
        return None
    return sum(known)


def _build_breakdowns(events: list[dict[str, Any]]) -> dict[str, Any]:
    breakdown: dict[str, dict[str, int]] = {
        "by_stage": {},
        "by_provider": {},
        "by_model": {},
        "by_operation": {},
    }
    for event in events:
        metrics = _metrics(event)
        token_value = _to_int(metrics.get("total_tokens"))
        if token_value is None:
            token_value = _to_int(metrics.get("input_tokens")) or 0
        for key, field_name in [
            ("by_stage", "stage"),
            ("by_provider", "provider"),
            ("by_model", "model"),
            ("by_operation", "operation"),
        ]:
            label = str(event.get(field_name) or "unknown")
            breakdown[key][label] = breakdown[key].get(label, 0) + token_value
    return breakdown


def _summary_to_dict(summary: AgentRunSummary) -> dict[str, Any]:
    return asdict(summary)


def _window_days(label: str) -> int | None:
    if not label.endswith("d"):
        return None
    try:
        return int(label[:-1])
    except ValueError:
        return None


def _summary_in_window(summary: dict[str, Any], cutoff_timestamp: float | None) -> bool:
    if cutoff_timestamp is None:
        return True
    started = _parse_ts(summary.get("started_at") or summary.get("completed_at"))
    if started is None:
        return False
    return started.timestamp() >= cutoff_timestamp


def _aggregate_summaries(label: str, summaries: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = [str(summary.get("status") or "").lower() for summary in summaries]
    total_duration = sum(_to_int(summary.get("duration_ms")) or 0 for summary in summaries)
    total_tokens = _sum_known([_to_int(summary.get("total_model_tokens")) for summary in summaries])
    llm_tokens = _sum_known([_to_int((summary.get("llm_usage") or {}).get("total_tokens")) for summary in summaries])
    embedding_tokens = _sum_known([_to_int((summary.get("embedding_usage") or {}).get("input_tokens")) for summary in summaries])
    cost = _combine_costs([_dict_cost(summary.get("cost")) for summary in summaries], set())
    embedding_cost = _combine_costs([_dict_cost((summary.get("embedding_usage") or {}).get("cost")) for summary in summaries], set())
    return {
        "window": label,
        "run_count": len(summaries),
        "successful_run_count": sum(1 for status in statuses if status in {"complete", "completed"}),
        "failed_run_count": sum(1 for status in statuses if status == "failed"),
        "canceled_run_count": sum(1 for status in statuses if status in {"canceled", "cancelled"}),
        "total_tokens": total_tokens,
        "llm_tokens": llm_tokens,
        "embedding_tokens": embedding_tokens,
        "total_cost": asdict(cost),
        "embedding_cost": asdict(embedding_cost),
        "total_duration_ms": total_duration,
        "average_duration_ms": int(total_duration / len(summaries)) if summaries else 0,
        "document_count": sum(_to_int((summary.get("embedding_usage") or {}).get("document_count")) or 0 for summary in summaries),
        "chunk_count": sum(_to_int((summary.get("embedding_usage") or {}).get("chunk_count")) or 0 for summary in summaries),
        "vector_count": sum(_to_int((summary.get("embedding_usage") or {}).get("vector_count")) or 0 for summary in summaries),
    }


def _dict_cost(value: Any) -> MetricCost:
    if not isinstance(value, dict):
        return MetricCost(None, "unknown")
    source = str(value.get("source") or "unknown")
    if source not in {"reported", "estimated", "unknown", "partial", "mixed"}:
        source = "unknown"
    return MetricCost(_to_float(value.get("amount_usd")), source)  # type: ignore[arg-type]
