## Design

`build_llm_wiki_index(site_root)` remains the canonical build entrypoint. It still writes `indexes/llm_wiki_documents.jsonl` for chunk metadata and `indexes/llm_wiki_postings.json` for lexical retrieval, but dense vectors are stored in a site-scoped zvec collection rather than relying on JSONL row vectors as the query store.

The zvec boundary lives in `src/scrape_planner/index/zvec_store.py` so production wiki code does not import MCP modules or scatter zvec SDK details through ranking logic. The adapter owns collection paths, schema creation, full replacement/upsert behavior, and query result normalization.

## Zvec Collection

Default collection path:

```text
data/sites/<site_id>/indexes/zvec_llm_wiki
```

The collection stores one row per indexed chunk. The vector field is named `embedding`. Metadata fields include:

- `id`
- `corpus`
- `source_kind`
- `source_id`
- `source_ids`
- `path`
- `title`
- `checksum`
- `text`

The manifest records:

- `zvec.ready`
- `zvec.path`
- `zvec.document_count`
- `embedding.provider`
- `embedding.model`
- `embedding.vector_dimensions`
- `embedding.space`
- `embedding_degraded`
- `embedding_space`
- `query_modes_available`

## Build Flow

1. Load raw and wiki documents as today.
2. Build canonical document rows and lexical postings.
3. Embed changed or required rows with the configured OpenRouter embedding model.
4. Replace or upsert the zvec collection with dense-vector rows.
5. Write manifest/report/status only after zvec persistence succeeds.

If OpenRouter embeddings are unavailable, zvec persistence fails, or the resulting vectors are not in the dense OpenRouter embedding space, the build must not claim vector readiness. The existing fail-fast posture is preserved.

## Query Flow

`query_mcp_wiki_index()` keeps the `mcp_auto` strategy:

1. Build BM25/wiki lexical candidates from postings and wiki text.
2. Generate an OpenRouter query embedding.
3. Query the site zvec collection for dense candidates.
4. Fuse dense candidates with lexical candidates.
5. Apply the existing reranking, source/citation/routing boosts, evidence formatting, and confidence metadata.

If query embedding or zvec collection access fails, vector retrieval returns an explicit `embedding_unavailable` response. It must not silently return an empty successful vector leg.

## Compatibility

`mcp_servers/smu_zvec_mcp.py` remains a legacy SMU-only MCP helper. It uses Ollama query embeddings and must not become the production `query_wiki` backend for this change.
