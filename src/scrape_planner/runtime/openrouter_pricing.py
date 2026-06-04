"""OpenRouter list pricing for metrics estimates.

Rates are USD per 1M tokens. LLM rates are refreshed from
https://openrouter.ai/api/v1/models when available; embedding rates follow
https://openrouter.ai/openai/text-embedding-3-small and -large (June 2026).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal

_LOGGER = logging.getLogger(__name__)

CostSource = Literal["reported", "estimated", "unknown", "partial", "mixed"]


@dataclass(frozen=True)
class MetricCost:
    amount_usd: float | None = None
    source: CostSource = "unknown"

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# Embedding models are not returned by /models; use OpenRouter catalog list prices.
EMBEDDING_PRICE_PER_MILLION_INPUT_TOKENS: dict[str, float] = {
    "openai/text-embedding-3-small": 0.02,
    "text-embedding-3-small": 0.02,
    "openai/text-embedding-3-large": 0.13,
    "text-embedding-3-large": 0.13,
}

# Snapshot fallback from OpenRouter /models (per-token * 1e6), June 2026.
_LLM_PRICE_FALLBACK_PER_MILLION: dict[str, tuple[float, float]] = {
    "deepseek/deepseek-v4-flash": (0.0983, 0.1966),
    "openai/gpt-4.1-mini": (0.40, 1.60),
    "openai/gpt-4.1": (2.00, 8.00),
    "anthropic/claude-sonnet-4.5": (3.00, 15.00),
    "google/gemini-2.5-flash": (0.30, 2.50),
}

_LLM_PRICE_CACHE: dict[str, tuple[float, float]] | None = None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _per_million_from_per_token(value: Any) -> float | None:
    amount = _to_float(value)
    if amount is None:
        return None
    return round(amount * 1_000_000, 8)


def fetch_openrouter_llm_pricing() -> dict[str, tuple[float, float]]:
    """Load LLM input/output $/1M from OpenRouter models API."""
    request = urllib.request.Request(
        OPENROUTER_MODELS_URL,
        headers={"Accept": "application/json", "User-Agent": "ultra-fast-rag-metrics/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        _LOGGER.debug("OpenRouter pricing fetch failed: %s", exc)
        return dict(_LLM_PRICE_FALLBACK_PER_MILLION)

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return dict(_LLM_PRICE_FALLBACK_PER_MILLION)

    pricing: dict[str, tuple[float, float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("id") or "").strip()
        price = row.get("pricing")
        if not model_id or not isinstance(price, dict):
            continue
        input_price = _per_million_from_per_token(price.get("prompt"))
        output_price = _per_million_from_per_token(price.get("completion"))
        if input_price is None and output_price is None:
            continue
        pricing[model_id] = (input_price or 0.0, output_price or 0.0)

    if not pricing:
        return dict(_LLM_PRICE_FALLBACK_PER_MILLION)
    for model_id, rates in _LLM_PRICE_FALLBACK_PER_MILLION.items():
        pricing.setdefault(model_id, rates)
    return pricing


def llm_price_per_million_tokens(model: str | None = None) -> tuple[float, float] | None:
    global _LLM_PRICE_CACHE
    if _LLM_PRICE_CACHE is None:
        _LLM_PRICE_CACHE = fetch_openrouter_llm_pricing()
    model_id = str(model or "").strip()
    if not model_id:
        return None
    return _LLM_PRICE_CACHE.get(model_id)


def embedding_price_per_million_input_tokens(model: str | None = None) -> float:
    model_id = str(model or "").strip()
    env_override = os.getenv("OPENROUTER_EMBED_PRICE_PER_MILLION_INPUT_TOKENS")
    if env_override not in (None, ""):
        try:
            return float(env_override)
        except (TypeError, ValueError):
            pass
    return float(EMBEDDING_PRICE_PER_MILLION_INPUT_TOKENS.get(model_id) or 0.0)


def estimate_embedding_cost_usd(input_tokens: int | None, model: str | None = None) -> float | None:
    try:
        tokens = int(input_tokens) if input_tokens not in (None, "") else None
    except (TypeError, ValueError):
        tokens = None
    if tokens is None or tokens <= 0:
        return None
    price = embedding_price_per_million_input_tokens(model)
    if price <= 0:
        return None
    return round((tokens / 1_000_000) * price, 8)


def estimate_llm_cost_usd(
    prompt_tokens: int | None,
    completion_tokens: int | None,
    model: str | None = None,
) -> float | None:
    try:
        prompt = int(prompt_tokens) if prompt_tokens not in (None, "") else 0
    except (TypeError, ValueError):
        prompt = 0
    try:
        completion = int(completion_tokens) if completion_tokens not in (None, "") else 0
    except (TypeError, ValueError):
        completion = 0
    if prompt <= 0 and completion <= 0:
        return None
    pricing = llm_price_per_million_tokens(model)
    if pricing is None:
        return None
    input_price, output_price = pricing
    return round((prompt / 1_000_000) * input_price + (completion / 1_000_000) * output_price, 8)


def estimated_embedding_cost_from_payloads(*payloads: Any) -> tuple[float | None, int | None]:
    """Read estimated embedding cost/tokens from report, progress, or embedding sub-objects."""
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        amount = _to_float(payload.get("estimated_embedding_cost_usd"))
        if amount is not None:
            tokens = _to_float(payload.get("estimated_input_tokens"))
            return amount, int(tokens) if tokens is not None else None
        progress = payload.get("progress")
        if isinstance(progress, dict):
            amount = _to_float(progress.get("estimated_embedding_cost_usd"))
            if amount is not None:
                tokens = _to_float(progress.get("estimated_input_tokens"))
                return amount, int(tokens) if tokens is not None else None
        embedding = payload.get("embedding")
        if isinstance(embedding, dict):
            tokens = _to_float(embedding.get("estimated_input_tokens"))
            if tokens is not None:
                return None, int(tokens)
    return None, None


def resolve_embedding_metric_cost(
    *,
    input_tokens: int | None,
    model: str | None,
    estimated_cost_usd: Any = None,
    **payloads: Any,
) -> MetricCost:
    amount = _to_float(estimated_cost_usd)
    if amount is None:
        amount, _ = estimated_embedding_cost_from_payloads(*payloads.values())
    if amount is not None:
        return MetricCost(amount, "estimated")
    amount = estimate_embedding_cost_usd(input_tokens, model)
    if amount is not None:
        return MetricCost(amount, "estimated")
    return MetricCost(None, "unknown")
