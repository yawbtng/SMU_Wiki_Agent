import unittest

import pandas as pd

from src.scrape_planner.run_analytics import (
    build_llm_calls_timeseries,
    build_llm_cost_breakdown,
    build_llm_latency_table,
    build_llm_model_counts,
    build_llm_token_timeseries,
)


def _trace_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "provider": "openrouter",
                "operation": "select_urls",
                "model": "model-a",
                "status": "success",
                "ts": "2026-05-21T12:00:10Z",
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "latency_ms": 500,
                "cost_usd": 0.01,
                "is_summary": False,
            },
            {
                "provider": "openrouter",
                "operation": "cleanup_markdown",
                "model": "model-b",
                "status": "success",
                "ts": "2026-05-21T12:00:35Z",
                "prompt_tokens": 40,
                "completion_tokens": 10,
                "total_tokens": 50,
                "latency_ms": 800,
                "cost_usd": 0.02,
                "is_summary": False,
            },
            {
                "provider": "openrouter",
                "operation": "select_urls_summary",
                "model": "model-a",
                "status": "success",
                "ts": "2026-05-21T12:01:05Z",
                "prompt_tokens": 999,
                "completion_tokens": 999,
                "total_tokens": 1998,
                "latency_ms": 100,
                "cost_usd": 0.0,
                "is_summary": True,
            },
            {
                "provider": "ollama",
                "operation": "cleanup_markdown",
                "model": "local-model",
                "status": "success",
                "ts": "2026-05-21T12:01:20Z",
                "prompt_tokens": 70,
                "completion_tokens": 30,
                "total_tokens": 100,
                "latency_ms": 300,
                "cost_usd": 0.0,
                "is_summary": False,
            },
        ]
    )


class TestRunAnalyticsLLMMetrics(unittest.TestCase):
    def test_build_llm_calls_timeseries_buckets_openrouter_non_summary_calls(self):
        result = build_llm_calls_timeseries(_trace_df())
        self.assertEqual(
            result.to_dict("records"),
            [
                {"bucket": pd.Timestamp("2026-05-21T12:00:00Z"), "operation": "cleanup_markdown", "calls": 1},
                {"bucket": pd.Timestamp("2026-05-21T12:00:00Z"), "operation": "select_urls", "calls": 1},
            ],
        )

    def test_build_llm_token_timeseries_sums_prompt_completion_and_total(self):
        result = build_llm_token_timeseries(_trace_df())
        self.assertEqual(
            result.to_dict("records"),
            [
                {
                    "bucket": pd.Timestamp("2026-05-21T12:00:00Z"),
                    "prompt_tokens": 140.0,
                    "completion_tokens": 30.0,
                    "total_tokens": 170.0,
                }
            ],
        )

    def test_build_llm_model_counts_ranks_models_for_openrouter_calls(self):
        result = build_llm_model_counts(_trace_df())
        self.assertEqual(
            result.to_dict("records"),
            [{"model": "model-a", "calls": 1}, {"model": "model-b", "calls": 1}],
        )

    def test_build_llm_latency_table_keeps_operation_model_and_latency(self):
        result = build_llm_latency_table(_trace_df())
        self.assertEqual(
            result.to_dict("records"),
            [
                {"operation": "cleanup_markdown", "model": "model-b", "latency_ms": 800.0},
                {"operation": "select_urls", "model": "model-a", "latency_ms": 500.0},
            ],
        )

    def test_build_llm_cost_breakdown_groups_by_operation(self):
        result = build_llm_cost_breakdown(_trace_df(), group_by="operation")
        self.assertEqual(
            result.to_dict("records"),
            [{"operation": "cleanup_markdown", "cost_usd": 0.02}, {"operation": "select_urls", "cost_usd": 0.01}],
        )


if __name__ == "__main__":
    unittest.main()
