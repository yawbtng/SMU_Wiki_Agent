from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .storage import read_json, write_json


GRAPH_SCHEMA_VERSION = "scraped-url-graph-v1"

TOPIC_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    ("Admissions", "student_service", ("admission", "apply", "application", "deadline", "requirements")),
    ("Programs", "academic", ("program", "degree", "major", "minor", "graduate", "undergraduate")),
    ("Departments", "academic", ("department", "school of", "college of", "faculty", "academic units")),
    ("Tuition & Aid", "student_service", ("tuition", "fees", "financial aid", "billing", "payment", "scholarship")),
    ("Registrar", "student_service", ("registrar", "calendar", "transcript", "enrollment", "course catalog")),
    ("Student Life", "student_service", ("housing", "dining", "campus life", "student services", "health", "orientation")),
    ("Research", "academic", ("research", "lab", "institute", "center", "publication")),
    ("Policies", "office", ("policy", "policies", "compliance", "privacy", "accessibility")),
]


def build_scraped_url_graph(
    *,
    run_root: Path,
    site_url: str,
    model: str = "deepseek/deepseek-v4-flash",
    api_key: str | None = None,
    batch_size: int = 80,
) -> dict[str, Any]:
    sources = _read_scraped_sources(run_root)
    key = (api_key or os.getenv("OPENROUTER_API_KEY", "")).strip()
    pages = _classify_with_openrouter(sources, site_url=site_url, model=model, api_key=key, batch_size=batch_size) if key else []
    if not pages or len(pages) != len(sources):
        pages = [_heuristic_classify(source) for source in sources]

    graph = _build_graph_payload(site_url=site_url, run_root=run_root, pages=pages)
    out_dir = run_root / "wiki"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "graph.json", graph)
    write_json(run_root / "scraped_url_reasoning.json", {"pages": pages, "generated_at": graph["generated_at"]})
    _write_graph_index(out_dir / "index.md", graph)
    return graph


def _read_scraped_sources(run_root: Path) -> list[dict[str, Any]]:
    rows = read_json(run_root / "scrape_manifest.json", [])
    sources: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("status") != "success":
            continue
        path = Path(str(row.get("markdown_path") or ""))
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        title = _extract_title(text, row.get("url"))
        sources.append(
            {
                "url": row.get("url"),
                "markdown_path": str(path),
                "metadata_path": row.get("metadata_path"),
                "text_length": int(row.get("text_length") or len(text)),
                "title": title,
                "snippet": _compact_text(text, limit=1400),
            }
        )
    sources.sort(key=lambda item: str(item.get("url") or ""))
    return sources


def _classify_with_openrouter(
    sources: list[dict[str, Any]],
    *,
    site_url: str,
    model: str,
    api_key: str,
    batch_size: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    batches = [sources[i : i + batch_size] for i in range(0, len(sources), max(1, batch_size))]
    for batch_index, batch in enumerate(batches, start=1):
        prompt = _build_graph_prompt(site_url=site_url, batch=batch, batch_index=batch_index, batch_count=len(batches))
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Classify scraped university pages into a deterministic student-facing graph. Return JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
        }
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=180,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = _loads_json_from_text(content)
        rows = parsed.get("pages", []) if isinstance(parsed, dict) else []
        by_url = {row.get("url"): row for row in rows if isinstance(row, dict) and row.get("url")}
        for source in batch:
            row = by_url.get(source.get("url")) or {}
            out.append(_normalize_page(row, source))
    return out


def _build_graph_prompt(*, site_url: str, batch: list[dict[str, Any]], batch_index: int, batch_count: int) -> str:
    compact = [
        {
            "url": item.get("url"),
            "title": item.get("title"),
            "text_length": item.get("text_length"),
            "snippet": item.get("snippet"),
        }
        for item in batch
    ]
    return (
        "Reason over every scraped URL and classify it for a deterministic university graph.\n"
        f"Site: {site_url}\n"
        f"Batch: {batch_index}/{batch_count}\n"
        "Return every input URL exactly once. Do not drop pages.\n"
        "Use stable categories: Admissions, Programs, Departments, Tuition & Aid, Registrar, Student Life, Research, Policies, Other.\n"
        "Set include=false for pages that are thin, navigation-only, duplicate, stale news/events, or not student useful.\n"
        "For included pages, choose one category and optionally one group label such as a school, department, office, or service.\n"
        "Return strict JSON only with schema:\n"
        '{"pages":[{"url":"...","include":true,"category":"Registrar","node_type":"student_service","group":"Registrar","title":"...","confidence":0.87,"reason":"..."}]}\n'
        f"Scraped pages JSON:\n{json.dumps(compact, ensure_ascii=True)}"
    )


def _normalize_page(row: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    category = str(row.get("category") or "").strip() or _heuristic_category(source)[0]
    valid_categories = {name for name, _, _ in TOPIC_RULES} | {"Other"}
    if category not in valid_categories:
        category = "Other"
    node_type = str(row.get("node_type") or "").strip() or _node_type_for_category(category)
    group = str(row.get("group") or "").strip() or category
    title = str(row.get("title") or source.get("title") or source.get("url") or "Untitled").strip()
    try:
        confidence = float(row.get("confidence"))
    except Exception:
        confidence = 0.5
    return {
        "url": source.get("url"),
        "title": title[:180],
        "markdown_path": source.get("markdown_path"),
        "metadata_path": source.get("metadata_path"),
        "text_length": source.get("text_length"),
        "include": bool(row.get("include", True)),
        "category": category,
        "node_type": node_type,
        "group": group[:140],
        "confidence": max(0.0, min(confidence, 1.0)),
        "reason": str(row.get("reason") or "Classified from scraped page content.").strip()[:500],
    }


def _heuristic_classify(source: dict[str, Any]) -> dict[str, Any]:
    category, node_type, score = _heuristic_category(source)
    text = f"{source.get('url', '')} {source.get('title', '')} {source.get('snippet', '')}".lower()
    include = score > 0 and int(source.get("text_length") or 0) >= 80
    stale = re.search(r"/20(0\d|1\d|2[0-3])/", text) or re.search(r"\b20(0\d|1\d|2[0-3])\b", text)
    if stale and category not in {"Programs", "Departments", "Registrar"}:
        include = False
    return _normalize_page(
        {
            "include": include,
            "category": category,
            "node_type": node_type,
            "group": category,
            "confidence": 0.58 if include else 0.35,
            "reason": "Deterministic keyword fallback from scraped content.",
        },
        source,
    )


def _heuristic_category(source: dict[str, Any]) -> tuple[str, str, int]:
    text = f"{source.get('url', '')} {source.get('title', '')} {source.get('snippet', '')}".lower()
    best = ("Other", "page", 0)
    for category, node_type, terms in TOPIC_RULES:
        score = sum(text.count(term) for term in terms)
        score += sum(4 for term in terms if term.replace(" ", "-") in text)
        if score > best[2]:
            best = (category, node_type, score)
    return best


def _build_graph_payload(*, site_url: str, run_root: Path, pages: list[dict[str, Any]]) -> dict[str, Any]:
    included = [page for page in pages if page.get("include")]
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    root_id = "site:" + _stable_slug(site_url or run_root.name)
    nodes[root_id] = {"id": root_id, "type": "site", "label": site_url or run_root.name}
    for page in included:
        category = str(page.get("category") or "Other")
        group = str(page.get("group") or category)
        category_id = "category:" + _stable_slug(category)
        group_id = "group:" + _stable_slug(f"{category}:{group}")
        page_id = "page:" + hashlib.sha1(str(page.get("url") or "").encode("utf-8")).hexdigest()[:12]
        nodes.setdefault(category_id, {"id": category_id, "type": "category", "label": category})
        nodes.setdefault(group_id, {"id": group_id, "type": str(page.get("node_type") or "group"), "label": group})
        nodes[page_id] = {
            "id": page_id,
            "type": "page",
            "label": page.get("title") or page.get("url"),
            "url": page.get("url"),
            "markdown_path": page.get("markdown_path"),
            "confidence": page.get("confidence"),
            "reason": page.get("reason"),
        }
        edges.extend(
            [
                {"source": root_id, "target": category_id, "relationship": "contains"},
                {"source": category_id, "target": group_id, "relationship": "contains"},
                {"source": group_id, "target": page_id, "relationship": "has_source"},
            ]
        )

    edges = _dedupe_edges(edges)
    return {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "site_url": site_url,
        "run_root": str(run_root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "scraped_content_llm_reasoning",
        "counts": {
            "scraped_pages": len(pages),
            "included_pages": len(included),
            "excluded_pages": len(pages) - len(included),
            "nodes": len(nodes),
            "edges": len(edges),
        },
        "nodes": sorted(nodes.values(), key=lambda item: (item.get("type", ""), item.get("label", ""))),
        "edges": edges,
        "pages": sorted(pages, key=lambda item: (not item.get("include"), item.get("category", ""), item.get("url", ""))),
    }


def _write_graph_index(path: Path, graph: dict[str, Any]) -> None:
    lines = [
        "# University Source Graph",
        "",
        f"Site: {graph.get('site_url')}",
        f"Generated: {graph.get('generated_at')}",
        "",
        "## Categories",
        "",
    ]
    pages = [page for page in graph.get("pages", []) if page.get("include")]
    by_category: dict[str, list[dict[str, Any]]] = {}
    for page in pages:
        by_category.setdefault(str(page.get("category") or "Other"), []).append(page)
    for category in sorted(by_category):
        lines.append(f"### {category}")
        for page in sorted(by_category[category], key=lambda item: str(item.get("title") or item.get("url") or "")):
            lines.append(f"- [{page.get('title') or page.get('url')}]({page.get('url')}) - {page.get('reason')}")
        lines.append("")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _node_type_for_category(category: str) -> str:
    for item_category, node_type, _terms in TOPIC_RULES:
        if item_category == category:
            return node_type
    return "page"


def _dedupe_edges(edges: list[dict[str, str]]) -> list[dict[str, str]]:
    seen = set()
    out = []
    for edge in edges:
        key = (edge["source"], edge["target"], edge["relationship"])
        if key in seen:
            continue
        seen.add(key)
        out.append(edge)
    return sorted(out, key=lambda item: (item["source"], item["target"], item["relationship"]))


def _extract_title(text: str, fallback: Any) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()[:180]
    return str(fallback or "Untitled").rstrip("/").split("/")[-1].replace("-", " ").title() or str(fallback or "Untitled")


def _compact_text(text: str, *, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned[:limit]


def _stable_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80] or hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _loads_json_from_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    try:
        data = json.loads(stripped)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(stripped[start : end + 1])
            return data if isinstance(data, dict) else {}
    return {}
