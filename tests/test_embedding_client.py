from __future__ import annotations

from pathlib import Path

from src.scrape_planner.app.tmux_settings import apply_app_state_env_bridge, refresh_app_state_cache
from src.scrape_planner.core.storage import write_json
from src.scrape_planner.index.embedding_client import embedding_config_from_env, openrouter_embed_batch


def test_openrouter_embedding_timeout_defaults_to_cold_start_safe_value(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_EMBED_TIMEOUT", raising=False)

    config = embedding_config_from_env()

    assert config.provider == "openrouter"
    assert config.timeout_seconds == 30.0


def test_embedding_config_uses_app_state_openrouter_key_when_env_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    write_json(
        data_root / "app_state.json",
        {
            "openrouter_api_key": "fake-openrouter-key",
            "embedding_model": "openai/text-embedding-3-large",
        },
    )
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_EMBED_MODEL", raising=False)
    refresh_app_state_cache()

    apply_app_state_env_bridge()
    config = embedding_config_from_env()

    assert config.api_key == "fake-openrouter-key"
    assert config.model == "openai/text-embedding-3-large"


def test_embedding_config_prefers_env_over_app_state_openrouter_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    write_json(
        data_root / "app_state.json",
        {"openrouter_api_key": "fake-openrouter-key"},
    )
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-openrouter-key")
    refresh_app_state_cache()

    apply_app_state_env_bridge()
    config = embedding_config_from_env()

    assert config.api_key == "env-openrouter-key"


def test_app_state_env_bridge_can_force_saved_openrouter_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    write_json(data_root / "app_state.json", {"openrouter_api_key": "saved-openrouter-key"})
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))
    monkeypatch.setenv("OPENROUTER_API_KEY", "stale-openrouter-key")
    refresh_app_state_cache()

    apply_app_state_env_bridge(force=True)
    config = embedding_config_from_env()

    assert config.api_key == "saved-openrouter-key"


def test_openrouter_embed_batch_preserves_response_order(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            }

    def fake_post(url: str, *, json: dict, headers: dict, timeout: float) -> Response:
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("src.scrape_planner.index.embedding_client.requests.post", fake_post)

    vectors = openrouter_embed_batch(
        ["first", "second"],
        model="openai/text-embedding-3-small",
        base_url="https://openrouter.example/api/v1",
        api_key="test-key",
        timeout_seconds=12.5,
    )

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert captured["url"] == "https://openrouter.example/api/v1/embeddings"
    assert captured["json"]["input"] == ["first", "second"]  # type: ignore[index]
    assert captured["headers"]["Authorization"] == "Bearer test-key"  # type: ignore[index]
    assert captured["timeout"] == 12.5
