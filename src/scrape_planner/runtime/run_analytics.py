from __future__ import annotations

from typing import Any

import pandas as pd


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
