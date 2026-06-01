from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


DEFAULT_OLLAMA_EMBED_MODEL = "nomic-embed-text:latest"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


@dataclass(frozen=True)
class EmbeddingClientConfig:
    provider: str = "ollama"
    model: str = DEFAULT_OLLAMA_EMBED_MODEL
    base_url: str = DEFAULT_OLLAMA_BASE_URL
    timeout_seconds: float = 10.0


def embedding_config_from_env() -> EmbeddingClientConfig:
    return EmbeddingClientConfig(
        provider="ollama",
        model=os.getenv("OLLAMA_EMBED_MODEL", DEFAULT_OLLAMA_EMBED_MODEL).strip() or DEFAULT_OLLAMA_EMBED_MODEL,
        base_url=os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).strip() or DEFAULT_OLLAMA_BASE_URL,
        timeout_seconds=_float_env("OLLAMA_EMBED_TIMEOUT", 0.5),
    )


def ollama_embed(text: str, *, model: str, base_url: str, timeout_seconds: float = 10.0) -> list[float]:
    payload = {"model": model, "prompt": text}
    resp = requests.post(f"{base_url.rstrip('/')}/api/embeddings", json=payload, timeout=timeout_seconds)
    if resp.status_code == 404:
        resp = requests.post(
            f"{base_url.rstrip('/')}/api/embed",
            json={"model": model, "input": text},
            timeout=timeout_seconds,
        )
    resp.raise_for_status()
    data: Any = resp.json()
    if isinstance(data, dict) and "embedding" in data:
        return _float_vector(data["embedding"])
    embeddings = data.get("embeddings") if isinstance(data, dict) else None
    if isinstance(embeddings, list) and embeddings:
        return _float_vector(embeddings[0])
    raise ValueError("ollama embedding response did not include an embedding")


def embed_text(text: str, config: EmbeddingClientConfig | None = None) -> list[float]:
    cfg = config or embedding_config_from_env()
    if cfg.provider != "ollama":
        raise ValueError(f"unsupported embedding provider: {cfg.provider}")
    return ollama_embed(text, model=cfg.model, base_url=cfg.base_url, timeout_seconds=cfg.timeout_seconds)


def _float_vector(values: Any) -> list[float]:
    if not isinstance(values, list):
        raise ValueError("embedding vector is not a list")
    return [float(value) for value in values]


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default
