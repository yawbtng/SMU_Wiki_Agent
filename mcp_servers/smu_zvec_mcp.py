from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("smu-zvec-query")

ZVEC_DB_PATH = Path(os.getenv("ZVEC_DB_PATH", "data/sites/www.smu.edu/latest/zvec_index")).resolve()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest")


def _embed(text: str) -> list[float]:
    resp = requests.post(f"{OLLAMA_BASE_URL}/api/embeddings", json={"model": OLLAMA_EMBED_MODEL, "prompt": text}, timeout=120)
    if resp.status_code == 404:
        resp = requests.post(f"{OLLAMA_BASE_URL}/api/embed", json={"model": OLLAMA_EMBED_MODEL, "input": text}, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    if "embedding" in data:
        return [float(v) for v in data["embedding"]]
    embeddings = data.get("embeddings") or []
    if embeddings:
        return [float(v) for v in embeddings[0]]
    raise RuntimeError("Ollama returned no embedding")


def _open_collection() -> Any:
    import zvec

    if hasattr(zvec, "open"):
        return zvec.open(path=str(ZVEC_DB_PATH))
    # Fallback for SDKs that only expose create_and_open. The existing schema is
    # loaded by the native collection when the path already exists.
    return zvec.create_and_open(path=str(ZVEC_DB_PATH), schema=None)


@mcp.tool()
def query_smu_wiki(query: str, top_k: int = 8) -> list[dict[str, Any]]:
    """Semantic search over the local SMU Zvec wiki index."""
    import zvec

    collection = _open_collection()
    vector = _embed(query)
    result = collection.query(vectors=zvec.VectorQuery(field_name="embedding", vector=vector), topk=int(top_k))
    rows = []
    for item in result or []:
        doc = getattr(item, "doc", item)
        score = getattr(item, "score", None)
        fields = getattr(doc, "fields", {}) or {}
        rows.append(
            {
                "score": score,
                "title": fields.get("title"),
                "url": fields.get("url"),
                "path": fields.get("path"),
                "text": fields.get("text"),
            }
        )
    return rows


@mcp.tool()
def zvec_index_info() -> dict[str, Any]:
    """Return configured Zvec path and embedding model for this MCP server."""
    return {"db_path": str(ZVEC_DB_PATH), "ollama_base_url": OLLAMA_BASE_URL, "embedding_model": OLLAMA_EMBED_MODEL}


if __name__ == "__main__":
    mcp.run()
