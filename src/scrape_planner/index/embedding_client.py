from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests

from ..core.env import float_env


DEFAULT_OPENROUTER_EMBED_MODEL = "openai/text-embedding-3-small"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass(frozen=True)
class EmbeddingClientConfig:
    provider: str = "openrouter"
    model: str = DEFAULT_OPENROUTER_EMBED_MODEL
    base_url: str = DEFAULT_OPENROUTER_BASE_URL
    timeout_seconds: float = 30.0
    api_key: str = ""


def embedding_config_from_env() -> EmbeddingClientConfig:
    return EmbeddingClientConfig(
        provider="openrouter",
        model=os.getenv("OPENROUTER_EMBED_MODEL", DEFAULT_OPENROUTER_EMBED_MODEL).strip() or DEFAULT_OPENROUTER_EMBED_MODEL,
        base_url=os.getenv("OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL).strip() or DEFAULT_OPENROUTER_BASE_URL,
        timeout_seconds=float_env("OPENROUTER_EMBED_TIMEOUT", 30.0),
        api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
    )


def openrouter_embed(text: str, *, model: str, base_url: str, api_key: str, timeout_seconds: float = 30.0) -> list[float]:
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is required for embeddings")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "input": text}
    resp = requests.post(f"{base_url.rstrip('/')}/embeddings", json=payload, headers=headers, timeout=timeout_seconds)
    resp.raise_for_status()
    data: Any = resp.json()
    rows = data.get("data") if isinstance(data, dict) else None
    if isinstance(rows, list) and rows:
        embedding = rows[0].get("embedding") if isinstance(rows[0], dict) else None
        return _float_vector(embedding)
    if isinstance(data, dict) and "embedding" in data:
        return _float_vector(data["embedding"])
    raise ValueError("OpenRouter embedding response did not include an embedding")


def openrouter_embed_batch(
    texts: list[str],
    *,
    model: str,
    base_url: str,
    api_key: str,
    timeout_seconds: float = 30.0,
) -> list[list[float]]:
    if not texts:
        return []
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is required for embeddings")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "input": texts}
    resp = requests.post(f"{base_url.rstrip('/')}/embeddings", json=payload, headers=headers, timeout=timeout_seconds)
    resp.raise_for_status()
    data: Any = resp.json()
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("OpenRouter embedding response did not include data rows")
    ordered = sorted(
        [row for row in rows if isinstance(row, dict)],
        key=lambda row: int(row.get("index") or 0),
    )
    vectors = [_float_vector(row.get("embedding")) for row in ordered]
    if len(vectors) != len(texts):
        raise ValueError("OpenRouter embedding response row count did not match input count")
    return vectors


def embed_text(text: str, config: EmbeddingClientConfig | None = None) -> list[float]:
    cfg = config or embedding_config_from_env()
    if cfg.provider != "openrouter":
        raise ValueError(f"unsupported embedding provider: {cfg.provider}")
    return openrouter_embed(
        text,
        model=cfg.model,
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        timeout_seconds=cfg.timeout_seconds,
    )


def embed_texts(texts: list[str], config: EmbeddingClientConfig | None = None) -> list[list[float]]:
    cfg = config or embedding_config_from_env()
    if cfg.provider != "openrouter":
        raise ValueError(f"unsupported embedding provider: {cfg.provider}")
    return openrouter_embed_batch(
        texts,
        model=cfg.model,
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        timeout_seconds=cfg.timeout_seconds,
    )


def _float_vector(values: Any) -> list[float]:
    if not isinstance(values, list):
        raise ValueError("embedding vector is not a list")
    return [float(value) for value in values]
