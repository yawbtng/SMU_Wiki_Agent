from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Protocol

import requests


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str
    rank: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class WebSearchProvider(Protocol):
    def search(self, query: str, *, max_results: int = 5) -> list[WebSearchResult]: ...


class MockWebSearchProvider:
    def __init__(self, results: list[WebSearchResult] | None = None) -> None:
        self.results = results or []
        self.calls: list[str] = []

    def search(self, query: str, *, max_results: int = 5) -> list[WebSearchResult]:
        self.calls.append(query)
        return self.results[:max_results]


class BraveWebSearchProvider:
    def __init__(self, *, api_key: str, endpoint: str = "https://api.search.brave.com/res/v1/web/search") -> None:
        self.api_key = api_key
        self.endpoint = endpoint

    def search(self, query: str, *, max_results: int = 5) -> list[WebSearchResult]:
        response = requests.get(
            self.endpoint,
            params={"q": query, "count": max_results},
            headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        rows = ((payload.get("web") or {}).get("results") or []) if isinstance(payload, dict) else []
        return [
            WebSearchResult(
                title=str(row.get("title") or ""),
                url=str(row.get("url") or ""),
                snippet=str(row.get("description") or row.get("snippet") or ""),
                rank=index,
            )
            for index, row in enumerate(rows[:max_results], start=1)
            if isinstance(row, dict) and row.get("url")
        ]


class TavilyWebSearchProvider:
    def __init__(self, *, api_key: str, endpoint: str = "https://api.tavily.com/search") -> None:
        self.api_key = api_key
        self.endpoint = endpoint

    def search(self, query: str, *, max_results: int = 5) -> list[WebSearchResult]:
        response = requests.post(
            self.endpoint,
            json={"api_key": self.api_key, "query": query, "max_results": max_results},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("results") if isinstance(payload, dict) else []
        return [
            WebSearchResult(
                title=str(row.get("title") or ""),
                url=str(row.get("url") or ""),
                snippet=str(row.get("content") or row.get("snippet") or ""),
                rank=index,
            )
            for index, row in enumerate((rows or [])[:max_results], start=1)
            if isinstance(row, dict) and row.get("url")
        ]


def provider_from_env() -> WebSearchProvider | None:
    provider = os.getenv("RAG_WEB_SEARCH_PROVIDER", "").strip().lower()
    if provider in {"", "none", "disabled"}:
        if os.getenv("BRAVE_SEARCH_API_KEY", "").strip():
            provider = "brave"
        elif os.getenv("TAVILY_API_KEY", "").strip():
            provider = "tavily"
        else:
            return None
    if provider == "brave":
        key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
        return BraveWebSearchProvider(api_key=key) if key else None
    if provider == "tavily":
        key = os.getenv("TAVILY_API_KEY", "").strip()
        return TavilyWebSearchProvider(api_key=key) if key else None
    return None


def web_search(query: str, *, max_results: int = 5, provider: WebSearchProvider | None = None) -> dict[str, object]:
    selected = provider or provider_from_env()
    if selected is None:
        return {"status": "web_search_unavailable", "query": query, "results": []}
    results = selected.search(query, max_results=max_results)
    return {"status": "ok", "query": query, "results": [row.to_dict() for row in results]}
