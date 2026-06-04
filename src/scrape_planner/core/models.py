from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .time import utc_now_iso


@dataclass
class DiscoveredURL:
    url: str
    source_sitemap: str
    lastmod: Optional[str] = None
    path_category: str = "other"
    content_type_guess: str = "html"
    excluded_reason: Optional[str] = None
    selected: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PageResult:
    url: str
    status: str
    fetch_mode: str
    worker_id: Optional[str] = None
    attempt: int = 0
    http_status: Optional[int] = None
    failure_reason: Optional[str] = None
    metadata_path: Optional[str] = None
    markdown_path: Optional[str] = None
    raw_html_path: Optional[str] = None
    text_length: int = 0
    link_density: float = 0.0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
