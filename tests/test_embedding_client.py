from __future__ import annotations

from src.scrape_planner.index.embedding_client import embedding_config_from_env


def test_ollama_embedding_timeout_defaults_to_cold_start_safe_value(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_EMBED_TIMEOUT", raising=False)

    config = embedding_config_from_env()

    assert config.timeout_seconds == 10.0
