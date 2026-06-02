from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AppStateUpdate(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class DiscoverSiteRequest(BaseModel):
    site_url: str
    timeout: int = Field(default=15, ge=3, le=60)


class ApprovedUrlsUpdate(BaseModel):
    markdown: str = ""


class ApprovedUrlsCommitRequest(BaseModel):
    markdown: str = ""
    remove_terms: list[str] = Field(default_factory=list)


class ApprovedUrlsChatRequest(BaseModel):
    message: str = ""
    base_prompt: str = ""
    markdown: str | None = None
    limit: int = Field(default=5000, ge=1, le=30000)
    autosave: bool = True


class StartScrapeRequest(BaseModel):
    concurrency: int = Field(default=4, ge=1, le=16)
    prefer_approved: bool = True
    browser_mode: str = "none"


class SiteJobRequest(BaseModel):
    skill: str
    prompt: str = ""
    allow_concurrent: bool = False
    rebuild_wiki: bool = False
