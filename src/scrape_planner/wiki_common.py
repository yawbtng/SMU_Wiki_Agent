from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

INTEGRATED_STATES = {"integrated", "complete", "done", "excluded", "not-applicable"}


def parse_markdown_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    metadata: dict[str, Any] = {}
    current_key = ""
    for line in text[4:end].splitlines():
        if line.startswith("  - ") and current_key:
            metadata.setdefault(current_key, []).append(line[4:].strip())
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            current_key = key.strip()
            metadata[current_key] = value.strip() if value.strip() else []
    return metadata


def strip_markdown_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    if end < 0:
        return text
    return text[end + 4 :].lstrip()


def site_relative(path: Path, site_root: Path, *, resolve: bool = False) -> str:
    try:
        if resolve:
            return str(Path(path).resolve().relative_to(Path(site_root).resolve()))
        return str(Path(path).relative_to(site_root))
    except ValueError:
        return str(path)


def timestamp_slug(value: str, *, fallback_hash: bool = False) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z]+", "-", str(value)).strip("-")
    if cleaned or not fallback_hash:
        return cleaned
    return hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:12]


def session_timestamp_slug(value: str) -> str:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) >= 14:
        return f"{digits[:8]}-{digits[8:14]}"
    return timestamp_slug(value)
