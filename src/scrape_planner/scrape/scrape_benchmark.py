from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

from .content_extract import extract_content
from .failure_classifier import classify_failure

try:
    from scrapling.fetchers import PlayWrightFetcher
except Exception:  # pragma: no cover - optional import
    PlayWrightFetcher = None


def quality_score(*, failure_reason: str | None, text_length: int, markdown_chars: int, link_density: float) -> float:
    if failure_reason:
        return 0.0
    text_component = min(max(text_length, 0), 4000) / 4000.0
    markdown_component = min(max(markdown_chars, 0), 6000) / 6000.0
    density_penalty = 0.0
    if link_density > 0.25:
        density_penalty = min((link_density - 0.25) * 40.0, 20.0)
    score = 45.0 + (text_component * 35.0) + (markdown_component * 20.0) - density_penalty
    return round(max(0.0, min(score, 100.0)), 2)


def load_sample_urls(selected_urls_path: Path, limit: int, *, offset: int = 0) -> list[str]:
    rows = json.loads(Path(selected_urls_path).read_text(encoding="utf-8"))
    urls: list[str] = []
    for row in rows[offset:]:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if url:
            urls.append(url)
        if len(urls) >= max(1, int(limit)):
            break
    return urls


def mode_availability(mode: str, lightpanda_cdp_url: str = "") -> tuple[bool, str]:
    normalized = str(mode or "").strip().lower()
    if normalized == "fetcher":
        return True, ""
    if normalized == "agent_browser":
        return (shutil.which("agent-browser") is not None, "agent-browser CLI is not installed" if shutil.which("agent-browser") is None else "")
    if normalized == "agent_browser_lightpanda":
        return (shutil.which("agent-browser") is not None, "agent-browser CLI is not installed" if shutil.which("agent-browser") is None else "")
    if normalized != "lightpanda":
        return False, f"unsupported mode: {mode}"
    if PlayWrightFetcher is None:
        return False, "scrapling PlayWrightFetcher is unavailable in this environment"
    if not str(lightpanda_cdp_url or "").strip():
        return False, "LIGHTPANDA_CDP_URL is not configured"
    return True, ""


def _clean_agent_browser_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("AGENT_BROWSER_ARGS", None)
    env.pop("AGENT_BROWSER_EXECUTABLE_PATH", None)
    env["AGENT_BROWSER_CONFIG"] = "/tmp/agent-browser-benchmark.json"
    Path(env["AGENT_BROWSER_CONFIG"]).write_text("{}\n", encoding="utf-8")
    return env


def _fetch_html_with_agent_browser(url: str, *, engine: str | None = None) -> tuple[int | None, str | None, str]:
    env = _clean_agent_browser_env()
    session = f"scrape-bench-{uuid4().hex[:10]}"
    base_cmd = ["agent-browser", "--session", session]
    if engine:
        base_cmd.extend(["--engine", engine])
    open_cmd = base_cmd + ["open", url]
    html_cmd = base_cmd + ["get", "html", "html"]
    close_cmd = ["agent-browser", "--session", session, "close"]
    open_result = subprocess.run(open_cmd, env=env, capture_output=True, text=True, timeout=45, check=False)
    if open_result.returncode != 0:
        raise RuntimeError((open_result.stderr or open_result.stdout or "agent-browser open failed").strip())
    html_result = subprocess.run(html_cmd, env=env, capture_output=True, text=True, timeout=45, check=False)
    subprocess.run(close_cmd, env=env, capture_output=True, text=True, timeout=15, check=False)
    if html_result.returncode != 0:
        raise RuntimeError((html_result.stderr or html_result.stdout or "agent-browser get html failed").strip())
    return 200, "text/html", html_result.stdout


def _fetch_html(url: str, *, mode: str, lightpanda_cdp_url: str = "") -> tuple[int | None, str | None, str]:
    normalized = str(mode or "").strip().lower()
    if normalized == "fetcher":
        response = requests.get(url, timeout=(5, 15))
        content_type = response.headers.get("content-type") if isinstance(response.headers, dict) else None
        return response.status_code, content_type, response.text
    if normalized == "lightpanda":
        response = PlayWrightFetcher.fetch(  # type: ignore[union-attr]
            url,
            headless=True,
            timeout=30000,
            network_idle=True,
            cdp_url=str(lightpanda_cdp_url or "").strip(),
        )
        status = getattr(response, "status", None) or getattr(response, "status_code", None)
        headers = getattr(response, "headers", None) or {}
        content_type = headers.get("content-type") if isinstance(headers, dict) else None
        html = getattr(response, "text", None)
        if html in {None, "None"}:
            html = getattr(response, "body", None)
        return status, content_type, str(html or "")
    if normalized == "agent_browser":
        return _fetch_html_with_agent_browser(url)
    if normalized == "agent_browser_lightpanda":
        return _fetch_html_with_agent_browser(url, engine="lightpanda")
    raise ValueError(f"Unsupported scrape mode: {mode}")


def benchmark_url(url: str, *, mode: str, lightpanda_cdp_url: str = "") -> dict[str, Any]:
    started = time.perf_counter()
    try:
        http_status, content_type, html = _fetch_html(url, mode=mode, lightpanda_cdp_url=lightpanda_cdp_url)
        _text, markdown, text_length, link_density = extract_content(html)
        failure_reason = classify_failure(
            http_status=http_status,
            content_type=content_type,
            text_length=text_length,
            link_density=link_density,
        )
        markdown_chars = len(markdown)
        return {
            "url": url,
            "mode": mode,
            "elapsed_sec": round(time.perf_counter() - started, 4),
            "http_status": http_status,
            "content_type": content_type,
            "failure_reason": failure_reason,
            "text_length": text_length,
            "markdown_chars": markdown_chars,
            "link_density": round(link_density, 6),
            "quality_score": quality_score(
                failure_reason=failure_reason,
                text_length=text_length,
                markdown_chars=markdown_chars,
                link_density=link_density,
            ),
        }
    except Exception as exc:
        return {
            "url": url,
            "mode": mode,
            "elapsed_sec": round(time.perf_counter() - started, 4),
            "http_status": None,
            "content_type": None,
            "failure_reason": classify_failure(
                http_status=None,
                content_type=None,
                text_length=0,
                link_density=0.0,
                error=exc,
            )
            or "error",
            "text_length": 0,
            "markdown_chars": 0,
            "link_density": 0.0,
            "quality_score": 0.0,
            "error": f"{type(exc).__name__}: {exc}",
        }


def summarize_mode_results(*, mode: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    sample_count = len(rows)
    success_rows = [row for row in rows if not row.get("failure_reason")]
    failure_rows = [row for row in rows if row.get("failure_reason")]
    elapsed_values = [float(row.get("elapsed_sec") or 0.0) for row in rows]
    success_quality = [float(row.get("quality_score") or 0.0) for row in success_rows]
    success_text_lengths = [int(row.get("text_length") or 0) for row in success_rows]
    success_markdown_chars = [int(row.get("markdown_chars") or 0) for row in success_rows]
    failure_breakdown: dict[str, int] = {}
    for row in failure_rows:
        reason = str(row.get("failure_reason") or "unknown")
        failure_breakdown[reason] = failure_breakdown.get(reason, 0) + 1
    total_elapsed = sum(elapsed_values)
    pages_per_min = (sample_count / total_elapsed * 60.0) if total_elapsed > 0 else 0.0
    return {
        "mode": mode,
        "available": True,
        "sample_count": sample_count,
        "success_count": len(success_rows),
        "failure_count": len(failure_rows),
        "success_rate": round((len(success_rows) / sample_count) if sample_count else 0.0, 4),
        "avg_elapsed_sec": round((statistics.mean(elapsed_values) if elapsed_values else 0.0), 4),
        "pages_per_min": round(pages_per_min, 2),
        "avg_quality_success": round((statistics.mean(success_quality) if success_quality else 0.0), 2),
        "median_text_length_success": int(statistics.median(success_text_lengths)) if success_text_lengths else 0,
        "median_markdown_chars_success": int(statistics.median(success_markdown_chars)) if success_markdown_chars else 0,
        "failure_breakdown": dict(sorted(failure_breakdown.items(), key=lambda item: (-item[1], item[0]))),
    }


def benchmark_mode(
    urls: list[str],
    *,
    mode: str,
    concurrency: int,
    lightpanda_cdp_url: str = "",
) -> dict[str, Any]:
    available, reason = mode_availability(mode, lightpanda_cdp_url)
    if not available:
        return {"mode": mode, "available": False, "reason": reason, "rows": []}
    rows: list[dict[str, Any]] = []
    if str(mode or "").strip().lower().startswith("agent_browser"):
        worker_count = 1
    else:
        worker_count = max(1, min(int(concurrency or 1), len(urls) or 1))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(benchmark_url, url, mode=mode, lightpanda_cdp_url=lightpanda_cdp_url): url
            for url in urls
        }
        for future in as_completed(futures):
            rows.append(future.result())
    rows.sort(key=lambda row: urls.index(row["url"]))
    summary = summarize_mode_results(mode=mode, rows=rows)
    summary["rows"] = rows
    return summary


def build_report(*, benchmark_name: str, sample_urls: list[str], summaries: list[dict[str, Any]]) -> dict[str, Any]:
    available = [summary for summary in summaries if summary.get("available")]
    winner = None
    if available:
        winner = sorted(
            available,
            key=lambda summary: (
                float(summary.get("success_rate") or 0.0),
                float(summary.get("avg_quality_success") or 0.0),
                float(summary.get("pages_per_min") or 0.0),
            ),
            reverse=True,
        )[0]
    return {
        "benchmark_name": benchmark_name,
        "sample_count": len(sample_urls),
        "sample_urls": sample_urls,
        "summaries": summaries,
        "winner": None if winner is None else {k: v for k, v in winner.items() if k != "rows"},
    }
