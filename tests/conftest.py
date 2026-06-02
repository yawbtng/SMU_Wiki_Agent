from __future__ import annotations

import hashlib
import math
import re

import pytest


@pytest.fixture(autouse=True)
def _deterministic_llm_wiki_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use deterministic dense-shaped embeddings so tests do not depend on local Ollama."""

    def _embed_text(text: str, *_args: object, **_kwargs: object) -> list[float]:
        vector = [0.0] * 768
        for token in re.findall(r"[a-z0-9]+", str(text).lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % len(vector)
            sign = 1.0 if digest[4] % 2 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if not norm:
            return vector
        return [round(value / norm, 6) for value in vector]

    monkeypatch.setattr(
        "src.scrape_planner.wiki.llm_wiki_index.embed_text",
        _embed_text,
    )
    try:
        from src.scrape_planner.wiki import llm_wiki_index as index_module

        index_module._reset_embedding_backend_state()
    except Exception:
        pass
