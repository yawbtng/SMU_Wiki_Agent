from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def _parse_ts(value: Any) -> pd.Timestamp | pd.NaT:
    if value is None:
        return pd.NaT
    try:
        return pd.to_datetime(value, utc=True, errors="coerce")
    except Exception:
        return pd.NaT


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _duration_sec(page: dict[str, Any]) -> float:
    if isinstance(page.get("duration_sec"), (int, float)):
        return max(0.0, float(page.get("duration_sec") or 0.0))
    started = _parse_ts(page.get("started_at"))
    finished = _parse_ts(page.get("finished_at"))
    if pd.isna(started) or pd.isna(finished):
        return 0.0
    return max(0.0, float((finished - started).total_seconds()))


def _read_size(path_value: Any) -> int:
    if not path_value:
        return 0
    try:
        return Path(str(path_value)).stat().st_size
    except Exception:
        return 0


def summarize_pages(
    pages: list[dict[str, Any]],
    *,
    run_status: dict[str, Any] | None = None,
    total_hint: int | None = None,
) -> dict[str, Any]:
    run_status = run_status or {}
    total_from_status = _safe_int(run_status.get("total"), 0)
    total = max(total_hint or 0, total_from_status, len(pages))
    success = 0
    failed = 0
    cancelled = 0
    done = 0
    started_values: list[pd.Timestamp] = []
    finished_values: list[pd.Timestamp] = []
    for page in pages:
        status = str(page.get("status") or "").lower()
        if status == "success":
            success += 1
            done += 1
        elif status in {"failed", "error"}:
            failed += 1
            done += 1
        elif status in {"cancelled", "skipped"}:
            cancelled += 1
            done += 1
        started = _parse_ts(page.get("started_at"))
        finished = _parse_ts(page.get("finished_at"))
        if pd.notna(started):
            started_values.append(started)
        if pd.notna(finished):
            finished_values.append(finished)

    if not started_values:
        started = _parse_ts(run_status.get("started_at"))
        if pd.notna(started):
            started_values.append(started)
    if not finished_values:
        finished = _parse_ts(run_status.get("finished_at"))
        if pd.notna(finished):
            finished_values.append(finished)

    started_at = min(started_values) if started_values else pd.NaT
    finished_at = max(finished_values) if finished_values else pd.NaT
    now_utc = pd.Timestamp.now(tz="UTC")
    terminal = str(run_status.get("state") or "").lower() in {"completed", "cancelled", "failed"}
    effective_end = finished_at
    if pd.isna(effective_end) and pd.notna(started_at):
        effective_end = now_utc if not terminal else started_at
    elapsed_sec = float((effective_end - started_at).total_seconds()) if pd.notna(started_at) and pd.notna(effective_end) else 0.0
    elapsed_sec = max(0.0, elapsed_sec)

    queued = max(0, total - done)
    pages_per_min = (done / elapsed_sec * 60.0) if elapsed_sec > 0 else 0.0
    eta_min = (queued / pages_per_min) if pages_per_min > 0 else None
    success_rate = (success / done * 100.0) if done > 0 else 0.0

    return {
        "state": str(run_status.get("state") or ""),
        "total": total,
        "done": done,
        "queued": queued,
        "success": success,
        "failed": failed,
        "cancelled": cancelled,
        "success_rate": success_rate,
        "elapsed_sec": elapsed_sec,
        "pages_per_min": pages_per_min,
        "eta_min": eta_min,
        "started_at": started_at,
        "finished_at": finished_at,
    }


def build_completion_timeseries(pages: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for page in pages:
        finished = _parse_ts(page.get("finished_at"))
        if pd.isna(finished):
            continue
        status = str(page.get("status") or "unknown").lower()
        rows.append({"ts": finished, "status": status})
    if not rows:
        return pd.DataFrame(columns=["bucket", "completed", "success", "failed", "cancelled", "ppm"])

    df = pd.DataFrame(rows).sort_values("ts")
    df["bucket"] = df["ts"].dt.floor("min")
    buckets = (
        df.groupby(["bucket", "status"], as_index=False)
        .size()
        .pivot(index="bucket", columns="status", values="size")
        .fillna(0)
        .reset_index()
    )
    for col in ("success", "failed", "cancelled", "skipped", "error"):
        if col not in buckets.columns:
            buckets[col] = 0
    buckets["failed"] = buckets["failed"] + buckets["error"]
    buckets["cancelled"] = buckets["cancelled"] + buckets["skipped"]
    buckets["completed"] = buckets["success"] + buckets["failed"] + buckets["cancelled"]
    buckets = buckets.sort_values("bucket").reset_index(drop=True)
    buckets["completed"] = buckets["completed"].cumsum()
    buckets["success"] = buckets["success"].cumsum()
    buckets["failed"] = buckets["failed"].cumsum()
    buckets["cancelled"] = buckets["cancelled"].cumsum()
    buckets["ppm"] = buckets["completed"].diff().fillna(buckets["completed"]).astype(float)
    return buckets[["bucket", "completed", "success", "failed", "cancelled", "ppm"]]


def summarize_durations(pages: list[dict[str, Any]]) -> dict[str, Any]:
    values = [_duration_sec(page) for page in pages if _duration_sec(page) > 0]
    if not values:
        return {"avg_sec": 0.0, "p50_sec": 0.0, "p95_sec": 0.0}
    series = pd.Series(values, dtype="float64")
    return {
        "avg_sec": float(series.mean()),
        "p50_sec": float(series.quantile(0.5)),
        "p95_sec": float(series.quantile(0.95)),
    }


def build_slowest_pages_table(pages: list[dict[str, Any]], limit: int = 25) -> pd.DataFrame:
    rows = []
    for page in pages:
        duration = _duration_sec(page)
        if duration <= 0:
            continue
        rows.append(
            {
                "url": str(page.get("url") or ""),
                "status": str(page.get("status") or ""),
                "duration_sec": round(duration, 2),
                "fetch_mode": str(page.get("fetch_mode") or ""),
                "http_status": page.get("http_status"),
                "failure_reason": str(page.get("failure_reason") or ""),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["url", "status", "duration_sec", "fetch_mode", "http_status", "failure_reason"])
    df = pd.DataFrame(rows).sort_values("duration_sec", ascending=False).head(max(1, int(limit)))
    return df.reset_index(drop=True)


def summarize_failures(
    pages: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> dict[str, pd.DataFrame]:
    page_failures = []
    for page in pages:
        status = str(page.get("status") or "").lower()
        if status not in {"failed", "error"}:
            continue
        page_failures.append(
            {
                "url": str(page.get("url") or ""),
                "failure_reason": str(page.get("failure_reason") or "unknown"),
                "fetch_mode": str(page.get("fetch_mode") or "unknown"),
                "http_status": str(page.get("http_status") or "unknown"),
                "error": str((page.get("error") or "")).strip(),
            }
        )
    for rec in failures:
        meta = rec.get("metadata") if isinstance(rec, dict) else {}
        if not isinstance(meta, dict):
            meta = {}
        page_failures.append(
            {
                "url": str(rec.get("url") or ""),
                "failure_reason": str(rec.get("failure_reason") or "unknown"),
                "fetch_mode": str(meta.get("fetch_mode") or "unknown"),
                "http_status": str(meta.get("http_status") or "unknown"),
                "error": str(meta.get("error") or "").strip(),
            }
        )

    if not page_failures:
        empty = pd.DataFrame(columns=["label", "count"])
        return {"by_reason": empty, "by_fetch_mode": empty.copy(), "by_http_status": empty.copy(), "top_errors": empty.copy()}

    df = pd.DataFrame(page_failures)
    by_reason = df.groupby("failure_reason", as_index=False).size().rename(columns={"failure_reason": "label", "size": "count"}).sort_values("count", ascending=False)
    by_fetch_mode = df.groupby("fetch_mode", as_index=False).size().rename(columns={"fetch_mode": "label", "size": "count"}).sort_values("count", ascending=False)
    by_http_status = df.groupby("http_status", as_index=False).size().rename(columns={"http_status": "label", "size": "count"}).sort_values("count", ascending=False)
    error_series = df["error"].fillna("").astype(str).str.strip()
    error_series = error_series[error_series != ""]
    if error_series.empty:
        top_errors = pd.DataFrame(columns=["label", "count"])
    else:
        top_errors = error_series.value_counts().head(10).rename_axis("label").reset_index(name="count")
    return {
        "by_reason": by_reason.reset_index(drop=True),
        "by_fetch_mode": by_fetch_mode.reset_index(drop=True),
        "by_http_status": by_http_status.reset_index(drop=True),
        "top_errors": top_errors.reset_index(drop=True),
    }


def summarize_output_volume(pages: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for page in pages:
        md_size = _read_size(page.get("markdown_path"))
        html_size = _read_size(page.get("raw_html_path"))
        text_length = _safe_int(page.get("text_length"), 0)
        rows.append(
            {
                "url": str(page.get("url") or ""),
                "status": str(page.get("status") or ""),
                "markdown_bytes": md_size,
                "raw_html_bytes": html_size,
                "text_length": text_length,
                "fetch_mode": str(page.get("fetch_mode") or ""),
            }
        )
    if not rows:
        return {
            "markdown_total_bytes": 0,
            "raw_html_total_bytes": 0,
            "text_avg": 0.0,
            "text_p50": 0.0,
            "text_p95": 0.0,
            "largest_pages": pd.DataFrame(columns=["url", "status", "markdown_bytes", "raw_html_bytes", "text_length", "fetch_mode", "total_bytes"]),
            "text_distribution": pd.DataFrame(columns=["bucket", "count"]),
        }

    df = pd.DataFrame(rows)
    df["total_bytes"] = df["markdown_bytes"] + df["raw_html_bytes"]
    text_series = df["text_length"].astype(float)
    text_distribution = (
        pd.cut(text_series, bins=[-1, 0, 500, 2000, 5000, 20000, 50000, float("inf")], labels=["0", "1-500", "501-2k", "2k-5k", "5k-20k", "20k-50k", "50k+"])
        .value_counts(sort=False)
        .rename_axis("bucket")
        .reset_index(name="count")
    )
    largest_pages = df.sort_values("total_bytes", ascending=False).head(25).reset_index(drop=True)
    return {
        "markdown_total_bytes": int(df["markdown_bytes"].sum()),
        "raw_html_total_bytes": int(df["raw_html_bytes"].sum()),
        "text_avg": float(text_series.mean()) if not text_series.empty else 0.0,
        "text_p50": float(text_series.quantile(0.5)) if not text_series.empty else 0.0,
        "text_p95": float(text_series.quantile(0.95)) if not text_series.empty else 0.0,
        "largest_pages": largest_pages[["url", "status", "markdown_bytes", "raw_html_bytes", "text_length", "fetch_mode", "total_bytes"]],
        "text_distribution": text_distribution,
    }


def _llm_trace_subset(trace_df: pd.DataFrame, provider: str = "openrouter") -> pd.DataFrame:
    if trace_df is None or trace_df.empty:
        return pd.DataFrame()
    df = trace_df.copy()
    if "provider" in df.columns:
        df = df[df["provider"].fillna("").astype(str) == provider]
    if "is_summary" in df.columns:
        df = df[~df["is_summary"].fillna(False).astype(bool)]
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        df = df.dropna(subset=["ts"])
    return df.reset_index(drop=True)


def build_llm_calls_timeseries(trace_df: pd.DataFrame, provider: str = "openrouter") -> pd.DataFrame:
    df = _llm_trace_subset(trace_df, provider=provider)
    if df.empty:
        return pd.DataFrame(columns=["bucket", "operation", "calls"])
    df["bucket"] = df["ts"].dt.floor("min")
    df["operation"] = df.get("operation", "unknown").fillna("unknown").astype(str)
    result = (
        df.groupby(["bucket", "operation"], as_index=False)
        .size()
        .rename(columns={"size": "calls"})
        .sort_values(["bucket", "operation"], ascending=[True, True])
        .reset_index(drop=True)
    )
    return result


def build_llm_token_timeseries(trace_df: pd.DataFrame, provider: str = "openrouter") -> pd.DataFrame:
    df = _llm_trace_subset(trace_df, provider=provider)
    if df.empty:
        return pd.DataFrame(columns=["bucket", "prompt_tokens", "completion_tokens", "total_tokens"])
    df["bucket"] = df["ts"].dt.floor("min")
    for col in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    result = (
        df.groupby("bucket", as_index=False)[["prompt_tokens", "completion_tokens", "total_tokens"]]
        .sum()
        .sort_values("bucket")
        .reset_index(drop=True)
    )
    return result


def build_llm_model_counts(trace_df: pd.DataFrame, provider: str = "openrouter", limit: int = 12) -> pd.DataFrame:
    df = _llm_trace_subset(trace_df, provider=provider)
    if df.empty:
        return pd.DataFrame(columns=["model", "calls"])
    model_series = df.get("model", pd.Series(dtype=str)).fillna("unknown").astype(str)
    counts = model_series.value_counts().head(max(1, int(limit))).rename_axis("model").reset_index(name="calls")
    return counts.sort_values(["calls", "model"], ascending=[False, True]).reset_index(drop=True)


def build_llm_latency_table(trace_df: pd.DataFrame, provider: str = "openrouter") -> pd.DataFrame:
    df = _llm_trace_subset(trace_df, provider=provider)
    if df.empty:
        return pd.DataFrame(columns=["operation", "model", "latency_ms"])
    df["operation"] = df.get("operation", "unknown").fillna("unknown").astype(str)
    df["model"] = df.get("model", "unknown").fillna("unknown").astype(str)
    df["latency_ms"] = pd.to_numeric(df.get("latency_ms"), errors="coerce")
    df = df.dropna(subset=["latency_ms"])
    if df.empty:
        return pd.DataFrame(columns=["operation", "model", "latency_ms"])
    return df[["operation", "model", "latency_ms"]].sort_values("latency_ms", ascending=False).reset_index(drop=True)


def build_llm_cost_breakdown(trace_df: pd.DataFrame, *, group_by: str, provider: str = "openrouter") -> pd.DataFrame:
    df = _llm_trace_subset(trace_df, provider=provider)
    if df.empty:
        return pd.DataFrame(columns=[group_by, "cost_usd"])
    if group_by not in {"operation", "model"}:
        raise ValueError(f"unsupported group_by: {group_by}")
    df[group_by] = df.get(group_by, "unknown").fillna("unknown").astype(str)
    df["cost_usd"] = pd.to_numeric(df.get("cost_usd"), errors="coerce").fillna(0.0)
    result = (
        df.groupby(group_by, as_index=False)["cost_usd"]
        .sum()
        .sort_values(["cost_usd", group_by], ascending=[False, True])
        .reset_index(drop=True)
    )
    return result[result["cost_usd"] > 0].reset_index(drop=True)
