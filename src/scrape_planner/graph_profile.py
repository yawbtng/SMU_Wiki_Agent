from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from typing import Any
from urllib.parse import urlparse

import requests

ACADEMIC_ROOT_HINTS = {
    "school",
    "college",
    "academics",
    "academic",
    "department",
    "departments",
    "program",
    "programs",
    "degree",
    "degrees",
    "faculty",
    "research",
    "centers",
    "institutes",
    "undergraduate",
    "graduate",
    "admissions",
    "admission",
}

ADMIN_ROOT_HINTS = {
    "admission",
    "admissions",
    "registrar",
    "bursar",
    "financial-aid",
    "financialaid",
    "studentaffairs",
    "student-affairs",
    "businessfinance",
    "hr",
    "oit",
    "libraries",
    "library",
    "alumni",
}

KNOWN_PAGE_AREAS = {
    "academics": "Academics",
    "academic": "Academics",
    "departments": "Departments",
    "department": "Departments",
    "areasofstudy": "Areas of Study",
    "areas-of-study": "Areas of Study",
    "programs": "Programs",
    "program": "Programs",
    "undergraduate": "Undergraduate",
    "graduate": "Graduate",
    "faculty": "Faculty",
    "research": "Research",
    "centers": "Centers",
    "centers-and-institutes": "Centers and Institutes",
    "centers-institutes": "Centers and Institutes",
    "admission": "Admission",
    "admissions": "Admission",
    "students": "Students",
    "alumni": "Alumni",
    "news": "News",
    "news-events": "News and Events",
    "newsandevents": "News and Events",
    "resources": "Resources",
    "about": "About",
}

ABBREVIATIONS = {
    "cs": "Computer Science",
    "ece": "Electrical and Computer Engineering",
    "cee": "Civil and Environmental Engineering",
    "me": "Mechanical Engineering",
    "orem": "Operations Research and Engineering Management",
    "hr": "Human Resources",
    "oit": "Office of Information Technology",
}


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-") or "unknown"


def humanize_segment(segment: str) -> str:
    raw = str(segment or "").strip("/").lower()
    if raw in ABBREVIATIONS:
        return ABBREVIATIONS[raw]
    if raw in KNOWN_PAGE_AREAS:
        return KNOWN_PAGE_AREAS[raw]
    return " ".join(part.capitalize() for part in re.split(r"[-_]+", raw) if part)


def graph_unit_id(key: str) -> str:
    return "unit:" + slugify(key)


def _path_segments(url: str) -> list[str]:
    return [s.lower() for s in urlparse(str(url or "")).path.split("/") if s]


def _root_type(root: str, child_counts: Counter[str]) -> str:
    root_l = root.lower()
    children = set(child_counts)
    if root_l in ADMIN_ROOT_HINTS:
        return "office"
    if children & {"academics", "departments", "areasofstudy", "areas-of-study", "faculty", "research", "undergraduate", "graduate", "centers-and-institutes", "centers-institutes"}:
        return "school"
    if root_l in {"news", "stories", "policy", "catalogs", "search"}:
        return "content-collection"
    if children & ACADEMIC_ROOT_HINTS:
        return "academic-unit"
    return "unit"


def _extract_root_label(root: str, root_titles: list[str]) -> str:
    candidates = [t.strip() for t in root_titles if t and len(t.strip()) <= 90]
    if candidates:
        counts = Counter(candidates)
        title = counts.most_common(1)[0][0]
        # Avoid generic page titles.
        if title.lower() not in {"home", "index", "welcome"}:
            return title
    return humanize_segment(root)


def infer_graph_profile(page_nodes: list[dict[str, Any]], *, site_id: str, run_id: str) -> dict[str, Any]:
    """Infer a per-university graph profile from URL paths and page titles.

    The output is intentionally deterministic and site-specific. It gives the
    graph builder a URL skeleton for any university without hardcoding SMU units.
    """

    root_counts: Counter[str] = Counter()
    child_counts: dict[str, Counter[str]] = defaultdict(Counter)
    third_counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    root_titles: dict[str, list[str]] = defaultdict(list)

    for page in page_nodes:
        url = str(page.get("source_url") or "")
        parts = _path_segments(url)
        if not parts:
            root = "root"
            root_counts[root] += 1
            root_titles[root].append(str(page.get("title") or ""))
            continue
        root = parts[0]
        root_counts[root] += 1
        if len(parts) == 1:
            root_titles[root].append(str(page.get("title") or ""))
        if len(parts) > 1:
            child_counts[root][parts[1]] += 1
        if len(parts) > 2:
            third_counts[(root, parts[1])][parts[2]] += 1

    units: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def add_unit(key: str, label: str, unit_type: str, *, root: str, path_prefix: list[str], confidence: float = 0.75) -> str:
        node_id = graph_unit_id(key)
        if not any(u["id"] == node_id for u in units):
            units.append(
                {
                    "id": node_id,
                    "type": "unit",
                    "unit_key": slugify(key),
                    "label": label,
                    "unit_type": unit_type,
                    "root": root,
                    "path_prefix": path_prefix,
                    "patterns": ["/" + "/".join(path_prefix) + r"(?:/|$)" if path_prefix else r"^/$"],
                    "confidence": confidence,
                    "source": "dynamic_url_profile",
                }
            )
        return node_id

    root_node = add_unit("root", site_id, "site-root", root="root", path_prefix=[], confidence=1.0)

    for root, count in root_counts.most_common():
        if root == "root":
            continue
        unit_type = _root_type(root, child_counts[root])
        label = _extract_root_label(root, root_titles[root])
        root_key = f"root/{root}"
        root_unit = add_unit(root_key, label, unit_type, root=root, path_prefix=[root], confidence=0.86)
        edges.append({"source": root_node, "target": root_unit, "type": "unit_has_child", "reason": "first URL path segment"})

        # Add common area children dynamically. Limit prevents huge news/year trees.
        for child, child_count in child_counts[root].most_common(24):
            if child_count < 2 and count > 20:
                continue
            child_label = humanize_segment(child)
            child_type = "area"
            if child in {"departments", "department"}:
                child_type = "department-collection"
            elif child in {"areasofstudy", "areas-of-study", "programs", "academics", "undergraduate", "graduate"}:
                child_type = "academic-area"
            elif child in {"faculty"}:
                child_type = "faculty-collection"
            child_key = f"root/{root}/{child}"
            child_unit = add_unit(child_key, child_label, child_type, root=root, path_prefix=[root, child], confidence=0.80)
            edges.append({"source": root_unit, "target": child_unit, "type": "unit_has_child", "reason": "second URL path segment"})

            if child in {"departments", "department", "areasofstudy", "areas-of-study", "programs", "academics"}:
                for third, third_count in third_counts[(root, child)].most_common(32):
                    if third_count < 2 and count > 20:
                        continue
                    third_key = f"root/{root}/{child}/{third}"
                    third_unit = add_unit(
                        third_key,
                        humanize_segment(third),
                        "department-or-program",
                        root=root,
                        path_prefix=[root, child, third],
                        confidence=0.78,
                    )
                    edges.append({"source": child_unit, "target": third_unit, "type": "unit_has_child", "reason": "third URL path segment"})

    return {
        "schema_version": 1,
        "site_id": site_id,
        "run_id": run_id,
        "source": "dynamic_url_profile",
        "counts": {"roots": len(root_counts), "units": len(units), "hierarchy_edges": len(edges)},
        "units": units,
        "edges": edges,
    }


def maybe_label_profile_with_openrouter(profile: dict[str, Any], *, api_key: str | None = None, model: str | None = None) -> dict[str, Any]:
    """Optionally ask OpenRouter to improve unit labels/types only.

    This never lets the LLM invent URLs or hierarchy; it may only return labels
    for existing unit ids. Set UFR_GRAPH_PROFILE_LLM=1 to enable.
    """

    if str(os.getenv("UFR_GRAPH_PROFILE_LLM", "")).lower() not in {"1", "true", "yes"}:
        return profile
    api_key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return profile
    model = model or os.getenv("GRAPH_PROFILE_OPENROUTER_MODEL", "openai/gpt-4.1-mini")
    units = profile.get("units") or []
    compact = [
        {"id": u.get("id"), "label": u.get("label"), "unit_type": u.get("unit_type"), "path_prefix": u.get("path_prefix")}
        for u in units[:200]
    ]
    prompt = (
        "You label university website graph units. Return strict JSON only with key 'units'. "
        "Do not invent ids or hierarchy. For each provided id, optionally improve label and unit_type.\n"
        f"Units: {json.dumps(compact, ensure_ascii=False)}"
    )
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "max_tokens": 4000},
            timeout=90,
        )
        resp.raise_for_status()
        content = str(resp.json()["choices"][0]["message"]["content"] or "")
        match = re.search(r"\{.*\}", content, re.S)
        payload = json.loads(match.group(0) if match else content)
        by_id = {str(row.get("id")): row for row in payload.get("units", []) if isinstance(row, dict)}
        allowed = {u["id"] for u in units}
        for unit in units:
            row = by_id.get(unit["id"])
            if not row or unit["id"] not in allowed:
                continue
            label = str(row.get("label") or "").strip()
            unit_type = str(row.get("unit_type") or "").strip()
            if label and len(label) <= 100:
                unit["label"] = label
                unit["label_source"] = "openrouter"
            if unit_type and len(unit_type) <= 50:
                unit["unit_type"] = slugify(unit_type)
        profile["llm_labeling"] = {"provider": "openrouter", "model": model, "status": "success"}
    except Exception as exc:  # pragma: no cover - network optional
        profile["llm_labeling"] = {"provider": "openrouter", "model": model, "status": "failed", "error": str(exc)[:300]}
    return profile
