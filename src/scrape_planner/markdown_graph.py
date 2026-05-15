from __future__ import annotations

import hashlib
import html
import json
import math
import re
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

from .storage import read_json, write_json


UNIT_RULES: list[dict[str, Any]] = [
    {
        "id": "smu_root",
        "label": "SMU root",
        "patterns": [r"^/$", r"\bsmu\b", r"southern methodist university"],
        "weak": True,
    },
    {
        "id": "admission",
        "label": "Admission",
        "patterns": [r"\badmission[s]?\b", r"\bapply\b", r"undergraduate admission", r"graduate admission"],
    },
    {
        "id": "isss_international",
        "label": "ISSS / international students",
        "patterns": [
            r"\bisss\b",
            r"international student",
            r"\bi-20\b",
            r"\bf-1\b",
            r"\bj-1\b",
            r"student visa",
            r"foreign national",
        ],
    },
    {
        "id": "registrar",
        "label": "Registrar",
        "patterns": [r"\bregistrar\b", r"academic calendar", r"transcript", r"enrollment verification", r"\bgrades?\b"],
    },
    {
        "id": "financial_aid_bursar",
        "label": "Financial Aid / Bursar",
        "patterns": [
            r"financial aid",
            r"\bbursar\b",
            r"\btuition\b",
            r"\bfees?\b",
            r"scholarship",
            r"payment deadline",
            r"cost of attendance",
        ],
    },
    {
        "id": "cox_business",
        "label": "Cox School of Business",
        "patterns": [r"\bcox\b", r"cox school", r"business school", r"/cox(?:/|$)"],
    },
    {
        "id": "meadows_school",
        "label": "Meadows School",
        "patterns": [r"\bmeadows\b", r"meadows school", r"/meadows(?:/|$)"],
    },
    {
        "id": "dedman_college",
        "label": "Dedman College",
        "patterns": [r"\bdedman\b", r"dedman college", r"/dedman(?:/|$)"],
    },
    {
        "id": "perkins_school",
        "label": "Perkins School",
        "patterns": [r"\bperkins\b", r"perkins school", r"school of theology", r"/perkins(?:/|$)"],
    },
    {
        "id": "lyle_engineering",
        "label": "Lyle School of Engineering",
        "patterns": [r"\blyle\b", r"school of engineering", r"engineering", r"/lyle(?:/|$)"],
    },
    {
        "id": "simmons_school",
        "label": "Simmons School",
        "patterns": [r"\bsimmons\b", r"simmons school", r"education and human development", r"/simmons(?:/|$)"],
    },
    {
        "id": "student_affairs",
        "label": "Student Affairs",
        "patterns": [r"student affairs", r"student life", r"dean of students", r"student support"],
    },
    {
        "id": "chaplain_religious_life",
        "label": "Chaplain / religious life",
        "patterns": [r"\bchaplain\b", r"religious life", r"spiritual life", r"faith"],
    },
    {
        "id": "libraries",
        "label": "Libraries",
        "patterns": [r"\blibrar(?:y|ies)\b", r"fondren", r"bridwell library", r"library services"],
    },
    {
        "id": "campus_recreation",
        "label": "Campus Recreation",
        "patterns": [r"campus recreation", r"\brecreation\b", r"dedman center", r"intramural"],
    },
    {
        "id": "parking_id_card",
        "label": "Parking / ID card services",
        "patterns": [r"\bparking\b", r"id card", r"parking and id", r"pony card", r"parking permit"],
    },
]

UNIT_ALIASES = {
    "root": "smu_root",
    "smu": "smu_root",
    "admissions": "admission",
    "apply": "admission",
    "international": "isss_international",
    "international students": "isss_international",
    "international_students": "isss_international",
    "io": "isss_international",
    "isss": "isss_international",
    "i-20": "isss_international",
    "i20": "isss_international",
    "f-1": "isss_international",
    "f1": "isss_international",
    "financial aid": "financial_aid_bursar",
    "financial_aid": "financial_aid_bursar",
    "bursar": "financial_aid_bursar",
    "tuition": "financial_aid_bursar",
    "cox": "cox_business",
    "business": "cox_business",
    "meadows": "meadows_school",
    "dedman": "dedman_college",
    "perkins": "perkins_school",
    "lyle": "lyle_engineering",
    "engineering": "lyle_engineering",
    "simmons": "simmons_school",
    "chaplain": "chaplain_religious_life",
    "religious life": "chaplain_religious_life",
    "library": "libraries",
    "recreation": "campus_recreation",
    "parking": "parking_id_card",
    "id card": "parking_id_card",
}

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "what",
    "with",
    "you",
    "your",
    "https",
    "http",
    "www",
    "smu",
    "edu",
    "main",
    "content",
    "page",
    "pages",
    "student",
    "students",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def knowledge_graph_dir(run_root: Path) -> Path:
    return run_root / "knowledge_graph"


def normalize_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def page_id_for_path(path: Path) -> str:
    return f"page:{path.stem}"


def unit_id(value: str) -> str:
    return f"unit:{value}"


def resolve_unit_key(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    key = raw.removeprefix("unit:")
    lowered = key.lower()
    normalized_space = re.sub(r"\s+", " ", lowered.replace("_", " ")).strip()
    normalized_underscore = normalized_space.replace(" ", "_")
    return UNIT_ALIASES.get(lowered) or UNIT_ALIASES.get(normalized_space) or UNIT_ALIASES.get(normalized_underscore) or key


def source_url_id(url: str) -> str:
    return "source_url:" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{hashlib.sha1(str(path).encode()).hexdigest()[:8]}.tmp")
    tmp_path.write_text("".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    tmp_path.replace(path)


def _read_text(path: Path, limit_chars: int | None = None) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if limit_chars is not None:
        return text[:limit_chars]
    return text


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _extract_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines()[:80]:
        match = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()[:240]
    for line in markdown.splitlines()[:40]:
        clean = re.sub(r"[*_`#\[\]()>-]+", " ", line).strip()
        clean = re.sub(r"\s+", " ", clean)
        if 8 <= len(clean) <= 180:
            return clean
    return fallback


def _extract_headings(markdown: str, limit: int = 12) -> list[str]:
    headings = []
    for line in markdown.splitlines():
        match = re.match(r"^\s{0,3}#{1,4}\s+(.+?)\s*$", line)
        if match:
            headings.append(re.sub(r"\s+", " ", match.group(1)).strip())
        if len(headings) >= limit:
            break
    return headings


def _load_manifest_by_markdown(run_root: Path) -> dict[str, dict[str, Any]]:
    rows = read_json(run_root / "scrape_manifest.json", [])
    by_path: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return by_path
    for row in rows:
        if not isinstance(row, dict):
            continue
        md_path = str(row.get("markdown_path") or "")
        if md_path:
            by_path[str(Path(md_path).resolve())] = row
            by_path[Path(md_path).name] = row
    return by_path


def _load_metadata_for_markdown(run_root: Path, md_path: Path, manifest_row: dict[str, Any]) -> dict[str, Any]:
    candidates = []
    if manifest_row.get("metadata_path"):
        candidates.append(Path(str(manifest_row.get("metadata_path"))))
    candidates.append(run_root / "metadata" / f"{md_path.stem}.json")
    for candidate in candidates:
        if candidate.exists():
            payload = read_json(candidate, {})
            if isinstance(payload, dict):
                return payload
    return {}


def discover_raw_markdown_files(run_root: Path) -> list[Path]:
    markdown_dir = run_root / "markdown"
    if not markdown_dir.exists():
        return []
    return sorted(markdown_dir.rglob("*.md"))


def build_page_nodes(run_root: Path, site_id: str, run_id: str) -> list[dict[str, Any]]:
    manifest_by_path = _load_manifest_by_markdown(run_root)
    nodes: list[dict[str, Any]] = []
    for md_path in discover_raw_markdown_files(run_root):
        text = _read_text(md_path)
        manifest = manifest_by_path.get(str(md_path.resolve())) or manifest_by_path.get(md_path.name) or {}
        metadata = _load_metadata_for_markdown(run_root, md_path, manifest)
        source_url = normalize_url(str(manifest.get("url") or metadata.get("url") or ""))
        title = _extract_title(text, Path(source_url).name if source_url else md_path.stem)
        headings = _extract_headings(text)
        nodes.append(
            {
                "id": page_id_for_path(md_path),
                "type": "page",
                "site_id": site_id,
                "run_id": run_id,
                "path": str(md_path),
                "relative_path": str(md_path.relative_to(run_root)),
                "source_url": source_url,
                "title": title,
                "content_hash": _content_hash(text),
                "text_length": len(text),
                "headings": headings,
                "metadata_path": str(run_root / "metadata" / f"{md_path.stem}.json") if (run_root / "metadata" / f"{md_path.stem}.json").exists() else str(manifest.get("metadata_path") or ""),
                "raw_html_path": str(manifest.get("raw_html_path") or ""),
                "http_status": manifest.get("http_status") or metadata.get("http_status"),
            }
        )
    return nodes


def build_unit_nodes(site_id: str, run_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": unit_id(rule["id"]),
            "type": "unit",
            "site_id": site_id,
            "run_id": run_id,
            "unit_key": rule["id"],
            "label": rule["label"],
            "patterns": rule["patterns"],
        }
        for rule in UNIT_RULES
    ]


def _reason_if_match(pattern: str, url_path: str, title: str, headings: str, body_sample: str) -> str:
    regex = re.compile(pattern, re.IGNORECASE)
    for label, value in (("url_path", url_path), ("title", title), ("headings", headings), ("body", body_sample)):
        if regex.search(value):
            return f"{label} matched /{pattern}/"
    return ""


def tag_page_units(page: dict[str, Any], markdown: str) -> list[dict[str, Any]]:
    parsed = urlparse(str(page.get("source_url") or ""))
    url_path = parsed.path.lower() or "/"
    title = str(page.get("title") or "")
    headings = "\n".join(str(h) for h in page.get("headings") or [])
    body_sample = markdown[:12000]
    tags: list[dict[str, Any]] = []
    for rule in UNIT_RULES:
        if rule.get("weak") and url_path not in {"", "/"}:
            continue
        reasons = []
        for pattern in rule["patterns"]:
            reason = _reason_if_match(pattern, url_path, title, headings, body_sample)
            if reason:
                reasons.append(reason)
        if reasons:
            tags.append(
                {
                    "page_id": page["id"],
                    "unit_id": unit_id(rule["id"]),
                    "unit_key": rule["id"],
                    "unit_label": rule["label"],
                    "reasons": reasons[:5],
                }
            )
    if not tags and parsed.netloc:
        tags.append(
            {
                "page_id": page["id"],
                "unit_id": unit_id("smu_root"),
                "unit_key": "smu_root",
                "unit_label": "SMU root",
                "reasons": ["fallback: no unit-specific rule matched"],
            }
        )
    return tags


def _extract_markdown_links(markdown: str, base_url: str) -> list[str]:
    links = []
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", markdown):
        parts = match.group(1).split()
        if not parts:
            continue
        href = parts[0].strip("<>\"'")
        if not href or href.startswith("#") or href.lower().startswith(("mailto:", "tel:", "javascript:")):
            continue
        links.append(normalize_url(urljoin(base_url or "", href)))
    for match in re.finditer(r"https?://[^\s)>\"]+", markdown):
        links.append(normalize_url(match.group(0).rstrip(".,;:")))
    return sorted({link for link in links if link})


def build_edges(page_nodes: list[dict[str, Any]], unit_nodes: list[dict[str, Any]], tags: list[dict[str, Any]], markdown_by_page: dict[str, str]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    site_id = str(page_nodes[0].get("site_id") if page_nodes else "")
    site_node = f"site:{site_id}" if site_id else "site:unknown"
    source_url_to_page = {normalize_url(str(page.get("source_url") or "")): page["id"] for page in page_nodes if page.get("source_url")}
    page_by_id = {page["id"]: page for page in page_nodes}
    seen: set[tuple[str, str, str]] = set()

    def add(source: str, target: str, edge_type: str, **attrs: Any) -> None:
        key = (source, target, edge_type)
        if key in seen:
            return
        seen.add(key)
        payload = {"source": source, "target": target, "type": edge_type}
        payload.update(attrs)
        edges.append(payload)

    for unit in unit_nodes:
        add(site_node, unit["id"], "site_has_unit")

    tags_by_unit: dict[str, list[str]] = defaultdict(list)
    for tag in tags:
        add(tag["unit_id"], tag["page_id"], "unit_has_page", reasons=tag.get("reasons", []))
        add(tag["page_id"], tag["unit_id"], "page_mentions_unit", reasons=tag.get("reasons", []))
        tags_by_unit[tag["unit_id"]].append(tag["page_id"])

    for unit, page_ids in tags_by_unit.items():
        sorted_ids = sorted(set(page_ids))
        for idx, source in enumerate(sorted_ids):
            for target in sorted_ids[idx + 1 : idx + 11]:
                add(source, target, "same_unit", unit_id=unit)
                add(target, source, "same_unit", unit_id=unit)

    for page in page_nodes:
        if page.get("source_url"):
            add(page["id"], source_url_id(page["source_url"]), "source_url", url=page["source_url"])
        for linked_url in _extract_markdown_links(markdown_by_page.get(page["id"], ""), str(page.get("source_url") or "")):
            target_page = source_url_to_page.get(linked_url)
            if target_page and target_page != page["id"]:
                add(page["id"], target_page, "page_links_to_page", url=linked_url)
            elif linked_url:
                parsed_target = urlparse(linked_url).netloc.lower()
                parsed_page = urlparse(str(page_by_id.get(page["id"], {}).get("source_url") or "")).netloc.lower()
                if parsed_target and parsed_target == parsed_page:
                    add(page["id"], source_url_id(linked_url), "source_url", url=linked_url, unresolved=True)
    return edges


def _edge_key(edge: dict[str, Any]) -> tuple[str, str, str]:
    return (str(edge.get("source") or ""), str(edge.get("target") or ""), str(edge.get("type") or ""))


def _node_key(node: dict[str, Any]) -> str:
    return str(node.get("id") or "")


def build_graph(run_root: Path, site_id: str, run_id: str) -> dict[str, Any]:
    run_root = Path(run_root)
    out_dir = knowledge_graph_dir(run_root)
    started_at = utc_now_iso()
    page_nodes = build_page_nodes(run_root, site_id, run_id)
    unit_nodes = build_unit_nodes(site_id, run_id)
    markdown_by_page = {page["id"]: _read_text(Path(page["path"])) for page in page_nodes}
    tags = []
    for page in page_nodes:
        tags.extend(tag_page_units(page, markdown_by_page[page["id"]]))
    edges = build_edges(page_nodes, unit_nodes, tags, markdown_by_page)
    graph = {
        "schema_version": 1,
        "site_id": site_id,
        "run_id": run_id,
        "built_at": utc_now_iso(),
        "source": "raw_markdown",
        "counts": {
            "raw_markdown_files": len(discover_raw_markdown_files(run_root)),
            "page_nodes": len(page_nodes),
            "unit_nodes": len(unit_nodes),
            "edges": len(edges),
            "tags": len(tags),
        },
        "nodes": [{"id": f"site:{site_id}", "type": "site", "site_id": site_id, "run_id": run_id}] + unit_nodes + page_nodes,
        "edges": edges,
    }
    report = build_graph_report(graph, page_nodes, unit_nodes, edges, tags)
    write_json(out_dir / "graph.json", graph)
    write_jsonl(out_dir / "page_nodes.jsonl", page_nodes)
    write_json(out_dir / "unit_nodes.json", unit_nodes)
    write_jsonl(out_dir / "edges.jsonl", edges)
    write_jsonl(out_dir / "tags.jsonl", tags)
    (out_dir / "graph_report.md").write_text(report, encoding="utf-8")
    (out_dir / "graph.html").write_text(render_graph_html(graph, page_nodes, unit_nodes, edges, tags), encoding="utf-8")
    write_json(
        out_dir / "build_status.json",
        {
            "status": "success",
            "started_at": started_at,
            "finished_at": utc_now_iso(),
            "graph_dir": str(out_dir),
            "counts": graph["counts"],
            "raw_markdown_source": str(run_root / "markdown"),
            "graphify_required": False,
        },
    )
    return graph


def load_graph(run_root: Path) -> dict[str, Any]:
    return read_json(knowledge_graph_dir(run_root) / "graph.json", {})


def load_page_nodes(run_root: Path) -> list[dict[str, Any]]:
    return read_jsonl(knowledge_graph_dir(run_root) / "page_nodes.jsonl")


def load_unit_nodes(run_root: Path) -> list[dict[str, Any]]:
    payload = read_json(knowledge_graph_dir(run_root) / "unit_nodes.json", [])
    return payload if isinstance(payload, list) else []


def load_edges(run_root: Path) -> list[dict[str, Any]]:
    return read_jsonl(knowledge_graph_dir(run_root) / "edges.jsonl")


def load_tags(run_root: Path) -> list[dict[str, Any]]:
    return read_jsonl(knowledge_graph_dir(run_root) / "tags.jsonl")


def run_graphify_enrichment_for_unit(run_root: Path, unit: str, max_pages: int = 100, max_concepts: int = 25) -> dict[str, Any]:
    """Merge bounded semantic concept edges for one deterministic unit slice."""
    graph = load_graph(run_root)
    if not graph:
        raise FileNotFoundError(f"Build deterministic graph first: {knowledge_graph_dir(run_root) / 'graph.json'}")
    found_unit = get_unit(run_root, unit)
    if not found_unit:
        raise KeyError(unit)
    pages = get_unit_pages(run_root, str(found_unit["unit_key"]), limit=max_pages)
    term_counts: Counter[str] = Counter()
    page_terms: dict[str, Counter[str]] = {}
    for page in pages:
        markdown = Path(str(page["path"])).read_text(encoding="utf-8", errors="replace")
        tokens = [token for token in tokenize(markdown) if len(token) >= 4 and not token.isdigit()]
        counts = Counter(tokens)
        page_terms[str(page["id"])] = counts
        term_counts.update(counts)

    concepts = []
    for term, count in term_counts.most_common(max_concepts):
        concepts.append(
            {
                "id": f"concept:{found_unit['unit_key']}:{term}",
                "type": "concept",
                "label": f"{found_unit['label']}: {term}",
                "term": term,
                "unit_id": found_unit["id"],
                "unit_key": found_unit["unit_key"],
                "count": int(count),
                "source": "bounded_graphify_enrichment",
            }
        )

    semantic_edges = []
    concept_terms = {concept["term"]: concept for concept in concepts}
    for page in pages:
        counts = page_terms.get(str(page["id"]), Counter())
        for term, concept in concept_terms.items():
            weight = int(counts.get(term, 0))
            if weight <= 0:
                continue
            semantic_edges.append(
                {
                    "source": page["id"],
                    "target": concept["id"],
                    "type": "semantic_keyword",
                    "weight": weight,
                    "unit_id": found_unit["id"],
                    "source_layer": "bounded_graphify_enrichment",
                }
            )

    existing_nodes = {str(node.get("id")): node for node in graph.get("nodes", []) if isinstance(node, dict)}
    for concept in concepts:
        existing_nodes[_node_key(concept)] = concept
    existing_edges = {_edge_key(edge): edge for edge in graph.get("edges", []) if isinstance(edge, dict)}
    for edge in semantic_edges:
        existing_edges[_edge_key(edge)] = edge
    graph["nodes"] = list(existing_nodes.values())
    graph["edges"] = list(existing_edges.values())
    graph["counts"] = {
        **dict(graph.get("counts") or {}),
        "concept_nodes": len([node for node in graph["nodes"] if node.get("type") == "concept"]),
        "edges": len(graph["edges"]),
    }
    graph.setdefault("enrichments", [])
    graph["enrichments"].append(
        {
            "type": "bounded_graphify_enrichment",
            "unit_id": found_unit["id"],
            "unit_label": found_unit["label"],
            "concept_count": len(concepts),
            "semantic_edge_count": len(semantic_edges),
            "built_at": utc_now_iso(),
        }
    )
    out_dir = knowledge_graph_dir(run_root)
    write_json(out_dir / "graph.json", graph)
    write_jsonl(out_dir / "edges.jsonl", graph["edges"])
    enrichment = {
        "schema_version": 1,
        "source_layer": "bounded_graphify_enrichment",
        "unit_id": found_unit["id"],
        "unit_key": found_unit["unit_key"],
        "unit_label": found_unit["label"],
        "pages_considered": len(pages),
        "concepts": concepts,
        "semantic_edges": semantic_edges,
        "communities": [
            {
                "id": f"community:{found_unit['unit_key']}:{concept['term']}",
                "label": concept["label"],
                "unit_label": found_unit["label"],
                "concept_id": concept["id"],
            }
            for concept in concepts
        ],
    }
    enrichment_path = out_dir / f"graphify_enrichment_{found_unit['unit_key']}.json"
    write_json(enrichment_path, enrichment)
    status = read_json(out_dir / "build_status.json", {})
    if isinstance(status, dict):
        status.setdefault("semantic_enrichments", [])
        status["semantic_enrichments"].append(
            {
                "unit_key": found_unit["unit_key"],
                "path": str(enrichment_path),
                "concept_count": len(concepts),
                "semantic_edge_count": len(semantic_edges),
                "finished_at": utc_now_iso(),
            }
        )
        status["counts"] = graph["counts"]
        write_json(out_dir / "build_status.json", status)
    return {
        "status": "success",
        "unit_key": found_unit["unit_key"],
        "unit_label": found_unit["label"],
        "path": str(enrichment_path),
        "concept_count": len(concepts),
        "semantic_edge_count": len(semantic_edges),
        "pages_considered": len(pages),
    }


def graph_stats(run_root: Path) -> dict[str, Any]:
    graph = load_graph(run_root)
    if not graph:
        return {"status": "missing", "graph_dir": str(knowledge_graph_dir(run_root))}
    page_nodes = load_page_nodes(run_root)
    unit_nodes = load_unit_nodes(run_root)
    edges = load_edges(run_root)
    tags = load_tags(run_root)
    raw_count = len(discover_raw_markdown_files(run_root))
    tagged_pages = {tag["page_id"] for tag in tags}
    linked_targets = {edge["target"] for edge in edges if edge.get("type") == "page_links_to_page"}
    linked_sources = {edge["source"] for edge in edges if edge.get("type") == "page_links_to_page"}
    page_ids = {page["id"] for page in page_nodes}
    isolated = sorted(page_ids - tagged_pages - linked_targets - linked_sources)
    return {
        "status": "ready",
        "graph_dir": str(knowledge_graph_dir(run_root)),
        "raw_markdown_files": raw_count,
        "page_nodes": len(page_nodes),
        "unit_nodes": len(unit_nodes),
        "edges": len(edges),
        "tags": len(tags),
        "pages_without_unit_tags": len(page_ids - tagged_pages),
        "isolated_pages": len(isolated),
        "counts_match": raw_count == len(page_nodes),
        "built_at": graph.get("built_at"),
    }


def unit_distribution(run_root: Path) -> list[dict[str, Any]]:
    tags = load_tags(run_root)
    units = {unit["id"]: unit for unit in load_unit_nodes(run_root)}
    counter = Counter(tag["unit_id"] for tag in tags)
    return [
        {
            "unit_id": unit_id_value,
            "label": units.get(unit_id_value, {}).get("label", unit_id_value),
            "page_count": count,
        }
        for unit_id_value, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def pages_without_unit_tags(run_root: Path) -> list[dict[str, Any]]:
    tags = load_tags(run_root)
    tagged = {tag["page_id"] for tag in tags}
    return [page for page in load_page_nodes(run_root) if page["id"] not in tagged]


def orphan_pages(run_root: Path) -> list[dict[str, Any]]:
    edges = load_edges(run_root)
    linked = {
        edge[node_key]
        for edge in edges
        for node_key in ("source", "target")
        if str(edge.get(node_key, "")).startswith("page:")
    }
    return [page for page in load_page_nodes(run_root) if page["id"] not in linked]


def get_page(run_root: Path, page_id: str) -> dict[str, Any] | None:
    for page in load_page_nodes(run_root):
        if page.get("id") == page_id:
            return page
    return None


def get_page_markdown(run_root: Path, page_id: str) -> str:
    page = get_page(run_root, page_id)
    if not page:
        raise KeyError(page_id)
    return Path(str(page["path"])).read_text(encoding="utf-8", errors="replace")


def list_units(run_root: Path) -> list[dict[str, Any]]:
    distribution = {row["unit_id"]: row["page_count"] for row in unit_distribution(run_root)}
    rows = []
    for unit in load_unit_nodes(run_root):
        rows.append({**unit, "page_count": int(distribution.get(unit["id"], 0))})
    return rows


def get_unit(run_root: Path, unit: str) -> dict[str, Any] | None:
    key = resolve_unit_key(unit)
    target = unit_id(key) if key else unit
    for row in list_units(run_root):
        label = str(row.get("label") or "").lower()
        if row.get("id") == target or row.get("unit_key") == key or str(unit).lower() == label:
            return row
    return None


def get_unit_pages(run_root: Path, unit: str, limit: int = 50) -> list[dict[str, Any]]:
    found = get_unit(run_root, unit)
    if not found:
        return []
    page_lookup = {page["id"]: page for page in load_page_nodes(run_root)}
    page_ids = [tag["page_id"] for tag in load_tags(run_root) if tag.get("unit_id") == found["id"]]
    return [page_lookup[pid] for pid in page_ids[: max(0, int(limit))] if pid in page_lookup]


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9-]{1,}", str(text).lower()) if t not in STOPWORDS]


def _score_page(query: str, query_tokens: list[str], page: dict[str, Any], markdown: str) -> float:
    query_lower = str(query or "").lower()
    title = str(page.get("title") or "").lower()
    url = str(page.get("source_url") or "").lower()
    headings = " ".join(str(h) for h in page.get("headings") or []).lower()
    body = markdown.lower()
    combined = "\n".join([title, url, headings, body])
    score = 0.0
    for token in query_tokens:
        score += 10.0 * title.count(token)
        score += 6.0 * headings.count(token)
        score += 4.0 * url.count(token)
        score += min(body.count(token), 20) * 1.0
    if query_tokens and all(token in body or token in title or token in url for token in query_tokens):
        score += 15.0
    if "president" in query_tokens and ("who" in query_lower or "president of smu" in query_lower or "smu president" in query_lower):
        if re.search(r"\bpresident,\s*smu\b", combined):
            score += 120.0
        if "serves as the 11th president of smu" in combined:
            score += 150.0
        if "president of smu" in combined or "smu president" in combined:
            score += 80.0
        if "president's scholar" in combined or "presidents-scholars" in url:
            score -= 60.0
        if "presidential awards" in combined:
            score -= 30.0
    return score


ROLE_WORDS = {"chair", "coordinator", "dean", "director", "head", "president"}


def _role_lookup(query: str, tokens: list[str]) -> dict[str, Any] | None:
    role = next((token for token in tokens if token in ROLE_WORDS), "")
    if not role:
        return None
    query_lower = str(query or "").lower()
    target = ""
    match = re.search(rf"\b{re.escape(role)}\s+of\s+(.+)$", query_lower)
    if match:
        target = match.group(1)
    else:
        match = re.search(rf"\b(.+?)\s+{re.escape(role)}\b", query_lower)
        if match:
            target = match.group(1)
    target = re.sub(r"[^a-z0-9\s-]", " ", target)
    target = re.sub(r"\b(the|a|an|who|is|of)\b", " ", target)
    target = re.sub(r"\s+", " ", target).strip()
    return {"role": role, "target": target}


def _role_query_matches(role_query: dict[str, Any], page: dict[str, Any], markdown: str) -> bool:
    role = str(role_query.get("role") or "")
    target = str(role_query.get("target") or "")
    title = str(page.get("title") or "")
    url = str(page.get("source_url") or "")
    headings = " ".join(str(h) for h in page.get("headings") or [])
    combined = "\n".join([title, url, headings, markdown]).lower()
    if not re.search(rf"\b{re.escape(role)}\b", combined):
        return False
    if not target:
        return True
    target_tokens = tokenize(target)
    if not target_tokens:
        return True
    if target not in combined:
        return False
    role_positions = [match.start() for match in re.finditer(rf"\b{re.escape(role)}\b", combined)]
    target_positions = [match.start() for match in re.finditer(re.escape(target), combined)]
    return any(abs(role_pos - target_pos) <= 240 for role_pos in role_positions for target_pos in target_positions)


def _snippet(markdown: str, tokens: list[str], size: int = 900) -> str:
    lower = markdown.lower()
    positions = [lower.find(token) for token in tokens if lower.find(token) >= 0]
    if not positions:
        return markdown[:size]
    center = min(positions)
    start = max(0, center - size // 3)
    end = min(len(markdown), start + size)
    return markdown[start:end].strip()


def search_pages(run_root: Path, query: str, unit: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    tokens = tokenize(query)
    if not tokens:
        return []
    role_query = _role_lookup(query, tokens)
    pages = load_page_nodes(run_root)
    allowed_ids: set[str] | None = None
    if unit:
        allowed_ids = {page["id"] for page in get_unit_pages(run_root, unit, limit=100000)}
    results = []
    for page in pages:
        if allowed_ids is not None and page["id"] not in allowed_ids:
            continue
        markdown = Path(str(page["path"])).read_text(encoding="utf-8", errors="replace")
        if role_query and not _role_query_matches(role_query, page, markdown):
            continue
        score = _score_page(query, tokens, page, markdown)
        if score <= 0:
            continue
        results.append(
            {
                "page_id": page["id"],
                "score": round(score, 3),
                "title": page.get("title"),
                "source_url": page.get("source_url"),
                "path": page.get("path"),
                "snippet": _snippet(markdown, tokens),
            }
        )
    return sorted(results, key=lambda row: (-float(row["score"]), str(row["source_url"])))[: max(0, int(limit))]


def traverse_from_page(run_root: Path, page_id: str, depth: int = 1) -> dict[str, Any]:
    edges = load_edges(run_root)
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        adjacency[str(edge.get("source"))].append(edge)
    seen = {page_id}
    queue = deque([(page_id, 0)])
    found_edges = []
    while queue:
        node, dist = queue.popleft()
        if dist >= int(depth):
            continue
        for edge in adjacency.get(node, []):
            found_edges.append(edge)
            target = str(edge.get("target"))
            if target not in seen:
                seen.add(target)
                queue.append((target, dist + 1))
    page_lookup = {page["id"]: page for page in load_page_nodes(run_root)}
    unit_lookup = {unit["id"]: unit for unit in load_unit_nodes(run_root)}
    return {
        "start": page_id,
        "depth": depth,
        "nodes": [page_lookup.get(node) or unit_lookup.get(node) or {"id": node} for node in sorted(seen)],
        "edges": found_edges,
    }


def shortest_path(run_root: Path, from_id: str, to_id: str) -> dict[str, Any]:
    edges = load_edges(run_root)
    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        adjacency[str(edge.get("source"))].append(edge)
    queue = deque([(from_id, [])])
    seen = {from_id}
    while queue:
        node, path_edges = queue.popleft()
        if node == to_id:
            return {"found": True, "nodes": [from_id] + [edge["target"] for edge in path_edges], "edges": path_edges}
        for edge in adjacency.get(node, []):
            target = str(edge.get("target"))
            if target in seen:
                continue
            seen.add(target)
            queue.append((target, path_edges + [edge]))
    return {"found": False, "nodes": [], "edges": []}


def answer_context(run_root: Path, question: str, unit: str | None = None, budget_chars: int = 12000) -> dict[str, Any]:
    results = search_pages(run_root, question, unit=unit, limit=20)
    remaining = max(500, int(budget_chars))
    evidence = []
    tokens = tokenize(question)
    for result in results:
        if remaining <= 0:
            break
        markdown = Path(str(result["path"])).read_text(encoding="utf-8", errors="replace")
        excerpt = _snippet(markdown, tokens, size=min(1800, remaining))
        if len(excerpt) > remaining:
            excerpt = excerpt[:remaining]
        remaining -= len(excerpt)
        evidence.append(
            {
                "page_id": result["page_id"],
                "title": result["title"],
                "source_url": result["source_url"],
                "path": result["path"],
                "score": result["score"],
                "markdown_excerpt": excerpt,
            }
        )
    return {
        "question": question,
        "unit": unit,
        "budget_chars": budget_chars,
        "used_chars": sum(len(item["markdown_excerpt"]) for item in evidence),
        "evidence": evidence,
        "instruction": "Use only this evidence to answer. Cite source_url or path for every claim.",
    }


def build_graph_report(graph: dict[str, Any], page_nodes: list[dict[str, Any]], unit_nodes: list[dict[str, Any]], edges: list[dict[str, Any]], tags: list[dict[str, Any]]) -> str:
    counts = graph.get("counts", {})
    dist = Counter(tag["unit_label"] for tag in tags)
    untagged = len({page["id"] for page in page_nodes} - {tag["page_id"] for tag in tags})
    edge_counts = Counter(edge["type"] for edge in edges)
    lines = [
        "# Markdown Knowledge Graph Report",
        "",
        f"- Site: `{graph.get('site_id')}`",
        f"- Run: `{graph.get('run_id')}`",
        f"- Built at: `{graph.get('built_at')}`",
        f"- Raw markdown files: `{counts.get('raw_markdown_files', 0)}`",
        f"- Page nodes: `{counts.get('page_nodes', 0)}`",
        f"- Unit nodes: `{counts.get('unit_nodes', 0)}`",
        f"- Edges: `{counts.get('edges', 0)}`",
        f"- Untagged pages: `{untagged}`",
        "",
        "## Unit Distribution",
        "",
        "| Unit | Pages |",
        "| --- | ---: |",
    ]
    for label, count in sorted(dist.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {label} | {count} |")
    lines.extend(["", "## Edge Types", "", "| Edge type | Count |", "| --- | ---: |"])
    for edge_type, count in sorted(edge_counts.items()):
        lines.append(f"| {edge_type} | {count} |")
    lines.extend(["", "## Determinism", "", "Graphify is not required for this graph. Raw markdown files remain the source of truth."])
    return "\n".join(lines) + "\n"


def render_graph_html(graph: dict[str, Any], page_nodes: list[dict[str, Any]], unit_nodes: list[dict[str, Any]], edges: list[dict[str, Any]], tags: list[dict[str, Any]]) -> str:
    dist = Counter(tag["unit_id"] for tag in tags)
    rows = []
    units = {unit["id"]: unit for unit in unit_nodes}
    for unit_id_value, count in sorted(dist.items(), key=lambda item: (-item[1], item[0])):
        label = units.get(unit_id_value, {}).get("label", unit_id_value)
        rows.append(f"<tr><td>{html.escape(str(label))}</td><td>{count}</td></tr>")
    edge_counts = Counter(edge["type"] for edge in edges)
    edge_rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>" for k, v in sorted(edge_counts.items()))
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Markdown Knowledge Graph</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    th, td {{ border-bottom: 1px solid #d8dee8; padding: 8px 10px; text-align: left; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 12px; }}
    .metric {{ border: 1px solid #d8dee8; border-radius: 6px; padding: 10px; }}
    .metric strong {{ display: block; font-size: 22px; }}
  </style>
</head>
<body>
  <h1>Markdown Knowledge Graph</h1>
  <p><strong>{html.escape(str(graph.get("site_id")))}</strong> / <code>{html.escape(str(graph.get("run_id")))}</code></p>
  <div class="metrics">
    <div class="metric"><span>Raw files</span><strong>{len(page_nodes)}</strong></div>
    <div class="metric"><span>Units</span><strong>{len(unit_nodes)}</strong></div>
    <div class="metric"><span>Edges</span><strong>{len(edges)}</strong></div>
    <div class="metric"><span>Tags</span><strong>{len(tags)}</strong></div>
  </div>
  <h2>Unit Distribution</h2>
  <table><thead><tr><th>Unit</th><th>Pages</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
  <h2>Edge Types</h2>
  <table><thead><tr><th>Type</th><th>Count</th></tr></thead><tbody>{edge_rows}</tbody></table>
</body>
</html>
"""


def rebuild_query_index(run_root: Path) -> dict[str, Any]:
    pages = load_page_nodes(run_root)
    docs = []
    df: dict[str, int] = defaultdict(int)
    for page in pages:
        markdown = Path(str(page["path"])).read_text(encoding="utf-8", errors="replace")
        tokens = tokenize(" ".join([str(page.get("title") or ""), str(page.get("source_url") or ""), markdown]))
        counts = Counter(tokens)
        for token in counts:
            df[token] += 1
        docs.append({"page_id": page["id"], "token_counts": dict(counts), "length": sum(counts.values())})
    doc_count = max(1, len(docs))
    idf = {token: math.log((doc_count + 1) / (freq + 1)) + 1.0 for token, freq in df.items()}
    out = {"schema_version": 1, "built_at": utc_now_iso(), "doc_count": len(docs), "idf": idf, "documents": docs}
    write_json(knowledge_graph_dir(run_root) / "query_index.json", out)
    return {"status": "success", "path": str(knowledge_graph_dir(run_root) / "query_index.json"), "doc_count": len(docs)}
