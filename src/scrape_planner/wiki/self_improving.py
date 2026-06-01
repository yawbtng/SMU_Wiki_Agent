from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..core.site_layout import ensure_layout_for_site_root
from ..infra.background_runner import start_detached
from ..infra.tmux_runner import TmuxRunner
from ..runtime.run_persistence import _append_jsonl, _write_json_atomic
from ..sources.source_quality import assess_source_quality
from ..sources.source_registry import read_registry_rows
from .confidence import assess_confidence
from .ingest_safety import assess_trusted_domain, assess_url_safety, canonicalize_url
from .llm_wiki_index import index_info, query_mcp_wiki_index
from .web_search import WebSearchProvider, web_search

LOOP_GUARD_TTL_SECONDS = 60 * 60
MAX_INGEST_RETRIES = 3
DEFAULT_MIN_INDEX_DOCS = 1
DEFAULT_WEB_SEARCH_BUDGET = 10
DEFAULT_WEB_SEARCH_WINDOW_SECONDS = 3600
DEFAULT_MANUAL_RUN_RETENTION = 20


@dataclass(frozen=True)
class QualityGateDecision:
    accepted: bool
    reasons: list[str]
    quality: dict[str, Any]
    url: str
    title: str
    snippet: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def answer_question(
    site_root: Path,
    question: str,
    *,
    max_evidence: int = 5,
    max_web_results: int = 5,
    provider: WebSearchProvider | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    layout = ensure_layout_for_site_root(Path(site_root))
    current = now if now is not None else time.time()
    local = query_mcp_wiki_index(layout.site_root, question, max_evidence=max_evidence)
    confidence = assess_confidence(local)
    metadata = dict(local.get("metadata") or {}) if isinstance(local.get("metadata"), dict) else {}
    metadata["confidence"] = confidence
    if confidence.get("confident"):
        return {
            "status": "ok",
            "provenance": "wiki",
            "answer": _answer_from_evidence(local.get("evidence", [])),
            "citations": _citations_from_evidence(local.get("evidence", [])),
            "evidence": local.get("evidence", []),
            "metadata": metadata,
        }

    guard = LoopGuard(layout.site_root)
    job_status = _resolve_pending_job(guard, question, now=current)
    if job_status.get("action") == "retry_local":
        local = query_mcp_wiki_index(layout.site_root, question, max_evidence=max_evidence)
        confidence = assess_confidence(local)
        metadata = dict(local.get("metadata") or {}) if isinstance(local.get("metadata"), dict) else {}
        metadata["confidence"] = confidence
        metadata["ingest_completed"] = True
        return {
            "status": "ok",
            "provenance": "wiki",
            "answer": _answer_from_evidence(local.get("evidence", [])),
            "citations": _citations_from_evidence(local.get("evidence", [])),
            "evidence": local.get("evidence", []),
            "metadata": metadata,
            "ingestion_job": job_status.get("job"),
        }
    if job_status.get("action") == "surface_failure":
        return {
            "status": "ingest_failed",
            "provenance": "none",
            "answer": "",
            "evidence": local.get("evidence", []),
            "ingestion_job": job_status.get("job"),
            "metadata": {**metadata, "ingest_failure": job_status.get("reason", "")},
        }
    cached = guard.get(question, now=current)
    if cached:
        return {**cached, "metadata": {**metadata, "loop_guard": "pending"}}

    ready, readiness = _index_ready(layout.site_root)
    if not ready:
        return {
            "status": "index_not_ready",
            "provenance": "none",
            "answer": "",
            "evidence": local.get("evidence", []),
            "metadata": {**metadata, "index_readiness": readiness},
        }

    budget = WebSearchBudget(layout.site_root)
    if not budget.allow(now=current):
        return {
            "status": "web_search_budget_exhausted",
            "provenance": "none",
            "answer": "",
            "evidence": local.get("evidence", []),
            "metadata": {**metadata, "web_search_budget": budget.snapshot(now=current)},
        }

    if guard.retry_exhausted(question):
        return {
            "status": "ingest_retry_exhausted",
            "provenance": "none",
            "answer": "",
            "evidence": local.get("evidence", []),
            "metadata": metadata,
        }

    search = web_search(question, max_results=max_web_results, provider=provider)
    if search.get("status") != "ok":
        return {
            "status": str(search.get("status") or "web_search_unavailable"),
            "provenance": "none",
            "answer": "",
            "evidence": local.get("evidence", []),
            "metadata": {**metadata, "web_search": search},
        }

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in search.get("results", []) if isinstance(search.get("results"), list) else []:
        if not isinstance(row, dict):
            continue
        decision = assess_candidate_source(row, site_root=layout.site_root).to_dict()
        if decision["accepted"]:
            accepted.append({**row, "quality_gate": decision})
        else:
            rejected.append({**row, "quality_gate": decision})
            record_rejection(layout.site_root, row, decision)

    if not accepted:
        return {
            "status": "no_confident_answer",
            "provenance": "none",
            "answer": "",
            "evidence": local.get("evidence", []),
            "web_results": search.get("results", []),
            "rejected_sources": rejected,
            "metadata": {**metadata, "web_search": search},
        }

    top = accepted[0]
    job = launch_ingest_job(layout.site_root, str(top.get("url") or ""), question=question)
    if job.get("status") == "unavailable":
        return {
            "status": "ingest_launch_failed",
            "provenance": "none",
            "answer": "",
            "evidence": local.get("evidence", []),
            "ingestion_job": job,
            "metadata": {**metadata, "web_search": {**search, "results": accepted}},
        }
    budget.record(now=current)
    record_accepted_ingest(
        layout.site_root,
        question=question,
        job=job,
        url=str(top.get("url") or ""),
        source_ids=[],
    )
    provisional = {
        "status": "ok",
        "provenance": "web_provisional",
        "answer": _provisional_answer(top),
        "citations": [{"title": top.get("title", ""), "url": top.get("url", "")}],
        "evidence": local.get("evidence", []),
        "web_results": accepted,
        "rejected_sources": rejected,
        "ingestion_job": job,
        "metadata": {**metadata, "web_search": {**search, "results": accepted}},
    }
    guard.put(question, provisional, job_id=str(job.get("id") or ""), now=current)
    return provisional


def ingest_url(site_root: Path, url: str, *, question: str = "") -> dict[str, Any]:
    layout = ensure_layout_for_site_root(Path(site_root))
    candidate = {"url": url, "title": url, "snippet": question or url}
    decision = assess_candidate_source(candidate, site_root=layout.site_root, markdown=question).to_dict()
    if not decision["accepted"]:
        record_rejection(layout.site_root, candidate, decision)
        return {"status": "rejected", "url": url, "quality_gate": decision}
    job = launch_ingest_job(layout.site_root, url, question=question)
    if job.get("status") == "unavailable":
        return {"status": "ingest_launch_failed", "url": url, "quality_gate": decision, "ingestion_job": job}
    record_accepted_ingest(layout.site_root, question=question, job=job, url=url, source_ids=[])
    return {"status": "queued", "url": url, "quality_gate": decision, "ingestion_job": job}


def assess_candidate_source(
    candidate: dict[str, Any],
    *,
    site_root: Path | None = None,
    markdown: str = "",
) -> QualityGateDecision:
    title = str(candidate.get("title") or "")
    url = str(candidate.get("url") or "")
    snippet = str(candidate.get("snippet") or candidate.get("description") or "")
    text = markdown or f"{title}\n\n{snippet}\n\n{url}"
    if site_root is not None:
        domain_decision = assess_trusted_domain(url, site_root=site_root)
        if not domain_decision.allowed:
            return QualityGateDecision(
                accepted=False,
                reasons=[domain_decision.reason],
                quality={},
                url=url,
                title=title,
                snippet=snippet,
            )
        safety = assess_url_safety(url)
        if not safety.allowed:
            return QualityGateDecision(
                accepted=False,
                reasons=[safety.reason],
                quality={},
                url=url,
                title=title,
                snippet=snippet,
            )
    quality = assess_source_quality(text, source_id=_short_hash(url or text), original_url=url, parser_kind="web-search").to_dict()
    reasons = list(quality.get("reasons") or [])
    if quality.get("action") == "quarantined":
        reasons.append("source_quality_quarantined")
    policy_reason = _student_policy_rejection(title, url, snippet if not markdown else markdown)
    if policy_reason:
        reasons.append(policy_reason)
    accepted = not reasons or set(reasons).issubset({"high_boilerplate_or_link_ratio"})
    return QualityGateDecision(accepted=accepted, reasons=reasons, quality=quality, url=url, title=title, snippet=snippet)


def launch_ingest_job(site_root: Path, url: str, *, question: str = "") -> dict[str, Any]:
    layout = ensure_layout_for_site_root(Path(site_root))
    session = f"rag-ingest-{_short_hash(url)}"
    status_path = _job_status_path(layout.site_root, session)
    site_url = _trusted_site_url(layout.site_root)
    command = " ".join(
        [
            shlex.quote(sys.executable),
            "-m",
            "src.scrape_planner.scrape.manual_url_pipeline",
            "--site-root",
            shlex.quote(str(layout.site_root)),
            "--site-url",
            shlex.quote(site_url),
            "--url",
            shlex.quote(url),
            "--job-id",
            shlex.quote(session),
            "--job-status-file",
            shlex.quote(str(status_path)),
            "--question",
            shlex.quote(question),
        ]
    )
    _write_json_atomic(
        status_path,
        {"id": session, "status": "pending", "url": url, "question": question, "updated_at": int(time.time())},
    )
    workdir = str(layout.site_root.resolve())
    runner = TmuxRunner()
    if runner.available():
        result = runner.start(session, command, workdir)
        runner_name = "tmux"
    else:
        log_path = layout.indexes_dir / "ingest_jobs" / f"{session}.log"
        result = start_detached(command, workdir, log_path=log_path)
        runner_name = "background"
    return {
        "id": session,
        "status": "queued" if result.get("ok") else "unavailable",
        "runner": runner_name,
        "url": url,
        "question": question,
        "command": command,
        "status_file": str(status_path),
        "error": str(result.get("error") or ""),
    }


def record_rejection(site_root: Path, candidate: dict[str, Any], decision: dict[str, Any]) -> None:
    layout = ensure_layout_for_site_root(Path(site_root))
    _append_jsonl(
        layout.indexes_dir / "self_improving_rejections.jsonl",
        {"ts": int(time.time()), "candidate": candidate, "quality_gate": decision},
    )


def record_accepted_ingest(
    site_root: Path,
    *,
    question: str,
    job: dict[str, Any],
    url: str,
    source_ids: list[str],
) -> None:
    layout = ensure_layout_for_site_root(Path(site_root))
    _append_jsonl(
        layout.indexes_dir / "self_improving_accepted.jsonl",
        {
            "ts": int(time.time()),
            "question": question,
            "job_id": str(job.get("id") or ""),
            "url": url,
            "source_ids": list(source_ids),
            "status_file": str(job.get("status_file") or ""),
        },
    )


def rollback_auto_ingest(site_root: Path, job_id: str, *, now: str | None = None) -> dict[str, Any]:
    from ..sources.source_registry import write_registry_rows
    from .llm_wiki_builder import build_wiki
    from .llm_wiki_index import build_llm_wiki_index

    layout = ensure_layout_for_site_root(Path(site_root))
    status = read_ingest_job_status(layout.site_root, job_id)
    source_ids = [str(value) for value in status.get("source_ids", []) if str(value)]
    registry_path = layout.registry_path
    rows = read_registry_rows(registry_path) if registry_path.exists() else []
    quarantined: list[str] = []
    kept: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("source_id") or "") in source_ids:
            row = dict(row)
            row["status"] = "quarantined"
            row["error_reason"] = f"rollback:{job_id}"
            quarantined.append(str(row.get("source_id") or ""))
        kept.append(row)
    if quarantined:
        write_registry_rows(registry_path, kept)
    timestamp = now or str(int(time.time()))
    build_wiki(layout.site_root, no_input=True, resume=True, now=timestamp)
    index_report = build_llm_wiki_index(layout.site_root, now=timestamp)
    return {"status": "rolled_back", "job_id": job_id, "quarantined_source_ids": quarantined, "index_report": index_report}


def read_ingest_job_status(site_root: Path, job_id: str) -> dict[str, Any]:
    path = _job_status_path(site_root, job_id)
    if not path.exists():
        return {"id": job_id, "status": "unknown"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"id": job_id, "status": "malformed"}
    return payload if isinstance(payload, dict) else {"id": job_id, "status": "malformed"}


class WebSearchBudget:
    def __init__(self, site_root: Path) -> None:
        layout = ensure_layout_for_site_root(Path(site_root))
        self.path = layout.indexes_dir / "web_search_budget.json"
        self.limit = int(os.getenv("RAG_WEB_SEARCH_BUDGET", str(DEFAULT_WEB_SEARCH_BUDGET)))
        self.window_seconds = int(os.getenv("RAG_WEB_SEARCH_WINDOW_SECONDS", str(DEFAULT_WEB_SEARCH_WINDOW_SECONDS)))

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"count": 0, "window_start": 0.0}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"count": 0, "window_start": 0.0}
        return payload if isinstance(payload, dict) else {"count": 0, "window_start": 0.0}

    def allow(self, *, now: float) -> bool:
        data = self._read()
        window_start = float(data.get("window_start") or 0.0)
        count = int(data.get("count") or 0)
        if now - window_start > self.window_seconds:
            return True
        return count < self.limit

    def record(self, *, now: float) -> None:
        data = self._read()
        window_start = float(data.get("window_start") or 0.0)
        count = int(data.get("count") or 0)
        if now - window_start > self.window_seconds:
            window_start = now
            count = 0
        count += 1
        _write_json_atomic(self.path, {"count": count, "window_start": window_start, "limit": self.limit})

    def snapshot(self, *, now: float) -> dict[str, Any]:
        data = self._read()
        return {"count": int(data.get("count") or 0), "limit": self.limit, "window_seconds": self.window_seconds, "now": now}


class LoopGuard:
    def __init__(self, site_root: Path, *, ttl_seconds: int = LOOP_GUARD_TTL_SECONDS) -> None:
        self.site_root = Path(site_root)
        self.ttl_seconds = ttl_seconds
        self.path = ensure_layout_for_site_root(self.site_root).indexes_dir / "self_improving_loop_guard.json"

    def get(self, question: str, *, now: float | None = None) -> dict[str, Any] | None:
        data = self._read()
        key = _query_key(question)
        entry = data.get(key)
        current = now if now is not None else time.time()
        if not isinstance(entry, dict):
            return None
        if current - float(entry.get("created_at") or 0) > self.ttl_seconds:
            data.pop(key, None)
            self._write(data)
            return None
        payload = entry.get("payload")
        return dict(payload) if isinstance(payload, dict) else None

    def put(self, question: str, payload: dict[str, Any], *, job_id: str = "", now: float | None = None) -> None:
        data = self._read()
        key = _query_key(question)
        previous = data.get(key) if isinstance(data.get(key), dict) else {}
        retry_count = int(previous.get("retry_count") or 0)
        data[key] = {
            "created_at": now if now is not None else time.time(),
            "payload": payload,
            "job_id": job_id,
            "retry_count": retry_count,
        }
        self._write(data)

    def clear(self, question: str, *, increment_retry: bool = False) -> None:
        data = self._read()
        key = _query_key(question)
        if increment_retry and isinstance(data.get(key), dict):
            entry = dict(data[key])
            entry["retry_count"] = int(entry.get("retry_count") or 0) + 1
            entry.pop("payload", None)
            entry.pop("job_id", None)
            data[key] = entry
        else:
            data.pop(key, None)
        self._write(data)

    def retry_exhausted(self, question: str) -> bool:
        entry = self._read().get(_query_key(question))
        if not isinstance(entry, dict):
            return False
        return int(entry.get("retry_count") or 0) >= MAX_INGEST_RETRIES

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, Any]) -> None:
        _write_json_atomic(self.path, data)


def _resolve_pending_job(guard: LoopGuard, question: str, *, now: float) -> dict[str, Any]:
    data = guard._read().get(_query_key(question))
    if not isinstance(data, dict):
        return {"action": "continue"}
    job_id = str(data.get("job_id") or "")
    if not job_id:
        cached = guard.get(question, now=now)
        if cached:
            return {"action": "continue"}
        return {"action": "continue"}
    status = read_ingest_job_status(guard.site_root, job_id)
    state = str(status.get("status") or "")
    if state == "succeeded":
        guard.clear(question)
        return {"action": "retry_local", "job": status}
    if state == "failed":
        guard.clear(question, increment_retry=True)
        return {"action": "surface_failure", "job": status, "reason": str(status.get("reason") or "ingest_failed")}
    return {"action": "continue"}


def _index_ready(site_root: Path) -> tuple[bool, dict[str, Any]]:
    info = index_info(site_root)
    min_docs = int(os.getenv("RAG_MIN_INDEX_DOCS", str(DEFAULT_MIN_INDEX_DOCS)))
    total = int(info.get("raw_index_count") or 0) + int(info.get("wiki_index_count") or 0)
    if not info.get("ready"):
        return False, {"reason": "index_not_ready", "document_count": total, "min_documents": min_docs}
    if total < min_docs:
        return False, {"reason": "index_below_minimum", "document_count": total, "min_documents": min_docs}
    return True, {"reason": "ready", "document_count": total, "min_documents": min_docs}


def _trusted_site_url(site_root: Path) -> str:
    domains = []
    config_path = site_root / "config" / "trusted_domains.txt"
    if config_path.exists():
        domains = [line.strip() for line in config_path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    env_raw = os.getenv("RAG_TRUSTED_INGEST_DOMAINS", "").strip()
    if env_raw:
        domains.extend(part.strip() for part in env_raw.split(",") if part.strip())
    if not domains and "." in site_root.name:
        domains.append(site_root.name)
    domain = domains[0] if domains else site_root.name
    if domain.startswith("http"):
        return domain
    return f"https://{domain.lstrip('.')}"


def _job_status_path(site_root: Path, job_id: str) -> Path:
    layout = ensure_layout_for_site_root(Path(site_root))
    return layout.indexes_dir / "ingest_jobs" / f"{job_id}.json"


def _answer_from_evidence(evidence: Any) -> str:
    if not isinstance(evidence, list) or not evidence:
        return ""
    top = evidence[0] if isinstance(evidence[0], dict) else {}
    title = str(top.get("title") or "")
    snippet = str(top.get("snippet") or "")
    return f"{title}: {snippet}" if title else snippet


def _citations_from_evidence(evidence: Any) -> list[dict[str, Any]]:
    if not isinstance(evidence, list):
        return []
    return [
        {"title": row.get("title", ""), "path": row.get("path", ""), "source_id": row.get("source_id", "")}
        for row in evidence
        if isinstance(row, dict)
    ]


def _provisional_answer(result: dict[str, Any]) -> str:
    title = str(result.get("title") or "")
    snippet = str(result.get("snippet") or "")
    return f"{title}: {snippet}" if title and snippet else title or snippet


def _student_policy_rejection(title: str, url: str, snippet: str) -> str:
    haystack = f"{title} {url} {snippet}".lower()
    blocked = {
        "giving": ("/giving", "donor", "advancement", "annual report"),
        "alumni": ("alumni",),
        "old_news": ("/news/", "magazine", "press release"),
        "staff_bio": ("bio", "biography", "profile"),
        "design_demo": ("design system", "component library", "template", "demo"),
        "admin": ("trustee", "president", "cabinet", "administration"),
    }
    for reason, needles in blocked.items():
        if any(needle in haystack for needle in needles):
            return f"student_policy_{reason}"
    allowed_terms = (
        "registrar", "enrollment", "calendar", "course", "catalog", "degree", "program", "grades", "gpa",
        "tuition", "financial aid", "scholarship", "billing", "housing", "dining", "health", "counseling",
        "parking", "orientation", "accessibility", "admission", "student",
    )
    if not any(term in haystack for term in allowed_terms):
        return "student_policy_not_student_actionable"
    return ""


def _query_key(question: str) -> str:
    normalized = re.sub(r"\s+", " ", str(question or "").strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _short_hash(value: str) -> str:
    return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:12]


def find_registry_row_for_url(site_root: Path, url: str) -> dict[str, Any] | None:
    layout = ensure_layout_for_site_root(Path(site_root))
    canonical = canonicalize_url(url)
    for row in read_registry_rows(layout.registry_path):
        if canonicalize_url(str(row.get("original_url") or "")) == canonical and str(row.get("status") or "").lower() == "ready":
            return row
    return None


def enforce_manual_run_retention(site_root: Path, *, keep: int | None = None) -> list[str]:
    layout = ensure_layout_for_site_root(Path(site_root))
    limit = keep if keep is not None else int(os.getenv("RAG_MANUAL_RUN_RETENTION", str(DEFAULT_MANUAL_RUN_RETENTION)))
    runs = sorted(
        [path for path in layout.site_root.iterdir() if path.is_dir() and path.name.startswith("manual-")],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    removed: list[str] = []
    for path in runs[limit:]:
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink(missing_ok=True)
            elif child.is_dir():
                try:
                    child.rmdir()
                except OSError:
                    pass
        try:
            path.rmdir()
            removed.append(path.name)
        except OSError:
            continue
    return removed
