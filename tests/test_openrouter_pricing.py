from __future__ import annotations

from src.scrape_planner.runtime.openrouter_pricing import (
    EMBEDDING_PRICE_PER_MILLION_INPUT_TOKENS,
    estimate_embedding_cost_usd,
    estimate_llm_cost_usd,
    fetch_openrouter_llm_pricing,
    llm_price_per_million_tokens,
)


def test_embedding_catalog_matches_openrouter_list_price() -> None:
    assert EMBEDDING_PRICE_PER_MILLION_INPUT_TOKENS["openai/text-embedding-3-small"] == 0.02
    assert estimate_embedding_cost_usd(1_000_000, "openai/text-embedding-3-small") == 0.02


def test_llm_pricing_includes_deepseek_v4_flash_from_openrouter_api() -> None:
    pricing = fetch_openrouter_llm_pricing()
    assert "deepseek/deepseek-v4-flash" in pricing
    input_price, output_price = pricing["deepseek/deepseek-v4-flash"]
    assert round(input_price, 4) == 0.0983
    assert round(output_price, 4) == 0.1966
    assert estimate_llm_cost_usd(1_000_000, 1_000_000, "deepseek/deepseek-v4-flash") == round(0.0983 + 0.1966, 8)


def test_llm_price_lookup_returns_none_for_unknown_model() -> None:
    assert llm_price_per_million_tokens("unknown/model") is None
