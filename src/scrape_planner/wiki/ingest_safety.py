from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

DEFAULT_MAX_REDIRECTS = 5
DEFAULT_MAX_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class FetchDecision:
    allowed: bool
    reason: str
    url: str

    def to_dict(self) -> dict[str, str]:
        return {"allowed": self.allowed, "reason": self.reason, "url": self.url}


def canonicalize_url(url: str) -> str:
    raw = str(url or "").strip()
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return f"{scheme}://{netloc}{path}{('?' + parsed.query) if parsed.query else ''}"


def trusted_domains_for_site(site_root: str | os.PathLike[str]) -> set[str]:
    """Explicit trusted-domain allowlist for external ingestion."""
    from ..core.site_layout import ensure_layout_for_site_root

    domains: set[str] = set()
    env_raw = os.getenv("RAG_TRUSTED_INGEST_DOMAINS", "").strip()
    if env_raw:
        domains.update(part.strip().lower() for part in env_raw.split(",") if part.strip())
    layout = ensure_layout_for_site_root(Path(site_root))
    config_path = layout.site_root / "config" / "trusted_domains.txt"
    if config_path.exists():
        for line in config_path.read_text(encoding="utf-8").splitlines():
            value = line.strip().lower()
            if value and not value.startswith("#"):
                domains.add(value.lstrip("."))
    site_name = layout.site_root.name.lower()
    if site_name and "." in site_name:
        domains.add(site_name)
    return domains


def assess_trusted_domain(url: str, *, site_root: str | os.PathLike[str]) -> FetchDecision:
    canonical = canonicalize_url(url)
    parsed = urlparse(canonical)
    if parsed.scheme != "https":
        return FetchDecision(False, "https_required", canonical)
    host = parsed.hostname or ""
    if not host:
        return FetchDecision(False, "missing_host", canonical)
    allowed = trusted_domains_for_site(site_root)
    host_lower = host.lower()
    if not allowed:
        return FetchDecision(False, "trusted_domain_policy_empty", canonical)
    if any(host_lower == domain or host_lower.endswith(f".{domain}") for domain in allowed):
        return FetchDecision(True, "trusted_domain", canonical)
    return FetchDecision(False, "untrusted_domain", canonical)


def _blocked_ip(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return True
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
        return True
    if addr.is_multicast:
        return True
    metadata_ranges = (
        ipaddress.ip_network("169.254.169.254/32"),
        ipaddress.ip_network("fd00:ec2::254/128"),
    )
    return any(addr in net for net in metadata_ranges)


def _resolve_host_ips(hostname: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return []
    ips: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr:
            ips.append(str(sockaddr[0]))
    return ips


def assess_url_safety(url: str) -> FetchDecision:
    canonical = canonicalize_url(url)
    parsed = urlparse(canonical)
    if parsed.scheme != "https":
        return FetchDecision(False, "https_required", canonical)
    host = parsed.hostname or ""
    if not host:
        return FetchDecision(False, "missing_host", canonical)
    if host.lower() in {"localhost"} or host.endswith(".local"):
        return FetchDecision(False, "blocked_host", canonical)
    for ip in _resolve_host_ips(host):
        if _blocked_ip(ip):
            return FetchDecision(False, "blocked_ip", canonical)
    return FetchDecision(True, "ok", canonical)


def safe_fetch(
    url: str,
    *,
    site_root: str | os.PathLike[str] | None = None,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: tuple[float, float] = (5.0, 15.0),
) -> Any:
    decision = assess_url_safety(url)
    if not decision.allowed:
        raise ValueError(decision.reason)
    if site_root is not None:
        domain_decision = assess_trusted_domain(url, site_root=site_root)
        if not domain_decision.allowed:
            raise ValueError(domain_decision.reason)

    session = requests.Session()
    current = decision.url
    for _attempt in range(max_redirects + 1):
        safety = assess_url_safety(current)
        if not safety.allowed:
            raise ValueError(safety.reason)
        response = session.get(current, timeout=timeout, stream=True, allow_redirects=False)
        if response.is_redirect or response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location") or response.headers.get("location") or ""
            if not location:
                raise ValueError("redirect_missing_location")
            current = urljoin(current, location)
            continue
        response.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("response_byte_cap_exceeded")
            chunks.append(chunk)
        body = b"".join(chunks)
        response._content = body
        response.encoding = response.encoding or "utf-8"
        response._text = body.decode(response.encoding, errors="replace")
        return response
    raise ValueError("redirect_cap_exceeded")
