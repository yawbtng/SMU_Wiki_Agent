from __future__ import annotations

import hashlib
import re


def slug_from_url(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


APPROVED_URL_RE = re.compile(r"https?://[^\s)\]}>\"']+")


def parse_approved_urls_markdown(markdown: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in APPROVED_URL_RE.finditer(markdown or ""):
        url = match.group(0).rstrip(".,;")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls
