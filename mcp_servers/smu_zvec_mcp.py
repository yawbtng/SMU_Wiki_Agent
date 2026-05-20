from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

import requests

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


def _open_collection(db_path: Path = ZVEC_DB_PATH, *, zvec_module: Any | None = None) -> Any:
    zvec = zvec_module
    if zvec is None:
        import zvec as loaded_zvec

        zvec = loaded_zvec
    if hasattr(zvec, "open"):
        return zvec.open(path=str(db_path))
    # Fallback for SDKs that only expose create_and_open. The existing schema is
    # loaded by the native collection when the path already exists.
    return zvec.create_and_open(path=str(db_path), schema=None)


def query_zvec_index(
    query: str,
    top_k: int = 8,
    *,
    db_path: Path = ZVEC_DB_PATH,
    embed_fn: Callable[[str], list[float]] = _embed,
    collection: Any | None = None,
    zvec_module: Any | None = None,
) -> list[dict[str, Any]]:
    """Semantic search over a local Zvec wiki index."""
    zvec = zvec_module
    if zvec is None:
        import zvec as loaded_zvec

        zvec = loaded_zvec
    collection = collection or _open_collection(db_path, zvec_module=zvec)
    vector = embed_fn(query)
    result = collection.query(vectors=zvec.VectorQuery(field_name="embedding", vector=vector), topk=int(top_k))
    return _format_query_results(result)


def _format_query_results(result: Any) -> list[dict[str, Any]]:
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
                "source_kind": fields.get("source_kind"),
                "source_id": fields.get("source_id"),
                "text": fields.get("text"),
            }
        )
    return rows


def zvec_index_info() -> dict[str, Any]:
    """Return configured Zvec path and embedding model for this MCP server."""
    return {"db_path": str(ZVEC_DB_PATH), "ollama_base_url": OLLAMA_BASE_URL, "embedding_model": OLLAMA_EMBED_MODEL}


def create_mcp() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover - optional runtime dependency
        raise RuntimeError("mcp is not installed. Install optional dependencies with: pip install -r requirements-mcp.txt") from exc

    mcp = FastMCP("smu-zvec-query")

    @mcp.tool()
    def query_smu_wiki(query: str, top_k: int = 8) -> list[dict[str, Any]]:
        """Semantic search over the local SMU Zvec wiki index."""
        return query_zvec_index(query, top_k)

    @mcp.tool()
    def zvec_index_info() -> dict[str, Any]:
        """Return configured Zvec path and embedding model for this MCP server."""
        return {"db_path": str(ZVEC_DB_PATH), "ollama_base_url": OLLAMA_BASE_URL, "embedding_model": OLLAMA_EMBED_MODEL}

    return mcp


if __name__ == "__main__":
    create_mcp().run()
