from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from .storage import write_json


def claude_available() -> bool:
    return shutil.which("claude") is not None


def fetch_openrouter_models(api_key: str | None = None) -> list[dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    key = (api_key or os.getenv("OPENROUTER_API_KEY", "")).strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    resp = requests.get("https://openrouter.ai/api/v1/models", headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    models: list[dict[str, Any]] = []
    for item in data:
        pricing = item.get("pricing") or {}
        models.append(
            {
                "id": item.get("id", ""),
                "name": item.get("name") or item.get("id", ""),
                "context_length": item.get("context_length"),
                "prompt_price": pricing.get("prompt", "0"),
                "completion_price": pricing.get("completion", "0"),
                "request_price": pricing.get("request", "0"),
            }
        )
    models.sort(key=lambda m: m["id"])
    return models


def fetch_ollama_models(base_url: str = "http://localhost:11434") -> list[dict[str, Any]]:
    endpoint = f"{base_url.rstrip('/')}/api/tags"
    resp = requests.get(endpoint, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("models", [])
    models: list[dict[str, Any]] = []
    for item in data:
        details = item.get("details") or {}
        models.append(
            {
                "id": item.get("model") or item.get("name") or "",
                "name": item.get("name") or item.get("model") or "",
                "size": item.get("size"),
                "modified_at": item.get("modified_at"),
                "family": details.get("family"),
                "parameter_size": details.get("parameter_size"),
                "quantization_level": details.get("quantization_level"),
            }
        )
    models.sort(key=lambda m: m.get("id", ""))
    return models


def pull_ollama_model(base_url: str, model: str, *, stream: bool = False) -> dict[str, Any]:
    endpoint = f"{base_url.rstrip('/')}/api/pull"
    resp = requests.post(endpoint, json={"model": model, "stream": bool(stream)}, timeout=120)
    resp.raise_for_status()
    payload = resp.json()
    if isinstance(payload, dict):
        return payload
    return {"status": "ok"}


def choose_top_urls_with_claude(
    *,
    site_url: str,
    discovered_rows: list[dict[str, Any]],
    out_path: Path,
    max_urls: int = 150,
) -> dict[str, Any]:
    prompt = _build_url_selection_prompt(site_url=site_url, discovered_rows=discovered_rows, max_urls=max_urls)
    if claude_available():
        try:
            result = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "json"],
                capture_output=True,
                text=True,
                check=True,
            )
            payload = _extract_json_payload(result.stdout)
            if payload and isinstance(payload.get("selected_urls"), list):
                write_json(out_path, payload)
                return payload
        except Exception:
            pass
    fallback = _heuristic_select(discovered_rows, max_urls=max_urls)
    payload = {"selection_method": "heuristic_fallback", "selected_urls": fallback}
    write_json(out_path, payload)
    return payload


def choose_top_urls_with_openrouter(
    *,
    site_url: str,
    discovered_rows: list[dict[str, Any]],
    out_path: Path,
    max_urls: int = 150,
    model: str = "deepseek/deepseek-v4-flash",
    api_key: str | None = None,
    batch_size: int = 250,
    sleep_between_batches_sec: float = 0.0,
    control_dir: str | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    batch_callback: Callable[[list[dict[str, Any]], int, int], None] | None = None,
) -> dict[str, Any]:
    api_key = (api_key or os.getenv("OPENROUTER_API_KEY", "")).strip()
    openrouter_error = ""
    if api_key:
        try:
            parsed = _choose_top_urls_batched(
                site_url=site_url,
                discovered_rows=discovered_rows,
                max_urls=max_urls,
                model=model,
                api_key=api_key,
                batch_size=batch_size,
                sleep_between_batches_sec=sleep_between_batches_sec,
                control_dir=control_dir,
                progress_callback=progress_callback,
                batch_callback=batch_callback,
            )
            write_json(out_path, parsed)
            return parsed
        except Exception as exc:
            openrouter_error = str(exc)
    else:
        openrouter_error = "OPENROUTER_API_KEY is empty."

    payload = {
        "selection_method": "openrouter_failed",
        "model": model,
        "selected_urls": [],
        "scored_urls": [],
        "openrouter_error": openrouter_error,
        "used_openrouter": False,
    }
    write_json(out_path, payload)
    return payload


def _choose_top_urls_batched(
    *,
    site_url: str,
    discovered_rows: list[dict[str, Any]],
    max_urls: int,
    model: str,
    api_key: str,
    batch_size: int = 250,
    sleep_between_batches_sec: float = 0.0,
    control_dir: str | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    batch_callback: Callable[[list[dict[str, Any]], int, int], None] | None = None,
) -> dict[str, Any]:
    batches = [discovered_rows[i : i + batch_size] for i in range(0, len(discovered_rows), batch_size)]
    scored_urls: list[dict[str, Any]] = []
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    batch_errors = []
    batch_trace = []
    control_path = Path(control_dir) if control_dir else None

    def _is_cancelled() -> bool:
        return bool(control_path and (control_path / "cancel.flag").exists())

    def _wait_if_paused() -> None:
        if not control_path:
            return
        pause_flag = control_path / "pause.flag"
        while pause_flag.exists():
            if progress_callback is not None:
                progress_callback(0, 0, "Paused by user. Waiting to resume...")
            time.sleep(1.0)

    for idx, batch in enumerate(batches, start=1):
        if _is_cancelled():
            break
        _wait_if_paused()
        if progress_callback is not None:
            progress_callback(idx - 1, len(batches), f"Scoring batch {idx}/{len(batches)}")
        prompt = _build_url_scoring_prompt(
            site_url=site_url,
            discovered_rows=batch,
            batch_note=f"Batch {idx} of {len(batches)}. Score every URL in this batch.",
        )
        try:
            t0 = time.perf_counter()
            parsed, usage = _call_openrouter_json(api_key=api_key, model=model, prompt=prompt)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            scored_batch = _normalize_score_payload(parsed)
            scored_urls.extend(scored_batch)
            _add_usage(usage_totals, usage)
            batch_trace.append(
                {
                    "batch": idx,
                    "status": "success",
                    "latency_ms": latency_ms,
                    "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                    "completion_tokens": int(usage.get("completion_tokens") or 0),
                    "total_tokens": int(usage.get("total_tokens") or 0),
                    "scored_count": len(scored_batch),
                }
            )
        except Exception as exc:
            batch_errors.append({"batch": idx, "error": str(exc)})
            scored_batch = []
            batch_trace.append(
                {
                    "batch": idx,
                    "status": "failed",
                    "latency_ms": None,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "scored_count": len(scored_batch),
                    "error": str(exc),
                }
            )
        if batch_callback is not None:
            batch_callback(scored_batch, idx, len(batches))
        if progress_callback is not None:
            progress_callback(idx, len(batches), f"Finished batch {idx}/{len(batches)}")
        if sleep_between_batches_sec > 0:
            if progress_callback is not None:
                progress_callback(idx, len(batches), f"Sleeping {sleep_between_batches_sec:.1f}s before next batch")
            time.sleep(sleep_between_batches_sec)

    if batch_errors:
        raise RuntimeError(f"{len(batch_errors)} batch calls failed. First error: {batch_errors[0].get('error')}")

    scored_urls = _merge_scores_with_rows(discovered_rows, scored_urls)
    if progress_callback is not None:
        progress_callback(len(batches), len(batches), "Merging scored results")
    selected_urls = [
        {"url": row["url"], "reason": row.get("reason", ""), "priority": row.get("score", 0)}
        for row in scored_urls
        if int(row.get("score") or 0) >= 70
    ]
    return {
        "selection_method": "openrouter_deepseek_scored",
        "model": model,
        "used_openrouter": True,
        "scored_urls": scored_urls,
        "selected_urls": selected_urls[:max_urls],
        "_usage": usage_totals,
        "batch_count": len(batches),
        "batch_size": batch_size,
        "batch_errors": batch_errors,
        "batch_trace": batch_trace,
        "default_threshold": 70,
    }


def _call_openrouter_json(*, api_key: str, model: str, prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You select high-value URLs for student-facing university wiki coverage. Return JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
    }
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:1000]}")
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return _loads_json_from_text(content), data.get("usage", {})


def _add_usage(total: dict[str, int], usage: dict[str, Any]) -> None:
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        try:
            total[key] += int(usage.get(key) or 0)
        except Exception:
            pass


def _dedupe_selected_urls(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        url = row.get("url")
        if not url:
            continue
        existing = deduped.get(url)
        if not existing or int(row.get("priority") or 0) > int(existing.get("priority") or 0):
            deduped[url] = row
    return list(deduped.values())


def _normalize_score_payload(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(parsed.get("scores"), dict):
        return [
            {
                "url": url,
                "score": int(score),
                "reason": parsed.get("reasons", {}).get(url, "") if isinstance(parsed.get("reasons"), dict) else "",
                "student_value": int((parsed.get("student_value") or {}).get(url, 0))
                if isinstance(parsed.get("student_value"), dict)
                else None,
                "freshness": int((parsed.get("freshness") or {}).get(url, 0))
                if isinstance(parsed.get("freshness"), dict)
                else None,
                "source_quality": int((parsed.get("source_quality") or {}).get(url, 0))
                if isinstance(parsed.get("source_quality"), dict)
                else None,
                "scrape_value": int((parsed.get("scrape_value") or {}).get(url, 0))
                if isinstance(parsed.get("scrape_value"), dict)
                else None,
            }
            for url, score in parsed["scores"].items()
        ]
    if isinstance(parsed.get("scored_urls"), list):
        out = []
        for row in parsed["scored_urls"]:
            out.append(
                {
                    "url": row.get("url"),
                    "score": int(row.get("score", 0)),
                    "reason": row.get("reason", ""),
                    "student_value": row.get("student_value"),
                    "freshness": row.get("freshness"),
                    "source_quality": row.get("source_quality"),
                    "scrape_value": row.get("scrape_value"),
                }
            )
        return out
    return []


def _build_url_scoring_prompt(site_url: str, discovered_rows: list[dict[str, Any]], batch_note: str = "") -> str:
    target_year = datetime.now(timezone.utc).year
    compact = []
    for idx, row in enumerate(discovered_rows):
        compact.append(
            {
                "id": idx,
                "url": row.get("url"),
                "lastmod": row.get("lastmod"),
                "path_category": row.get("path_category"),
                "source_sitemap": row.get("source_sitemap"),
                "excluded_reason": row.get("excluded_reason"),
            }
        )
    return (
        "Score every URL for student-facing university wiki usefulness.\n"
        f"Site: {site_url}\n"
        f"{batch_note}\n"
        f"Current year: {target_year}\n"
        "Return every input URL exactly once. Do not select a subset.\n"
        "Score 0-100 using student value, freshness, source quality, and scrape value.\n"
        "High score: admissions, programs, departments, tuition, aid, scholarships, registrar, housing, schedules.\n"
        "Set score under 30 for login/search/filter/tag/archive/feed/duplicate/noisy URLs.\n"
        "Return strict JSON only with schema:\n"
        '{"scored_urls":[{"url":"...","score":87,"reason":"...","student_value":85,"freshness":92,"source_quality":83,"scrape_value":88}]}\n'
        "Rules: include every input URL exactly once; all numeric fields must be integers 0-100.\n"
        f"Candidates JSON:\n{json.dumps(compact, ensure_ascii=True)}"
    )


def _merge_scores_with_rows(rows: list[dict[str, Any]], scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url = {item.get("url"): item for item in scored if item.get("url")}
    merged = []
    for row in rows:
        url = row.get("url")
        score_row = by_url.get(url)
        if not score_row:
            score_row = {
                "score": 0,
                "reason": "missing_from_model_output",
                "student_value": 0,
                "freshness": 0,
                "source_quality": 0,
                "scrape_value": 0,
            }
        merged_row = dict(row)
        for key in ("score", "reason", "student_value", "freshness", "source_quality", "scrape_value"):
            merged_row[key] = score_row.get(key)
        merged.append(merged_row)
    merged.sort(key=lambda item: int(item.get("score") or 0), reverse=True)
    return merged


def explain_url_selection_with_openrouter(
    *,
    site_url: str,
    selected_payload: dict[str, Any],
    discovered_rows: list[dict[str, Any]],
    question: str,
    model: str = "deepseek/deepseek-v4-flash",
    api_key: str | None = None,
) -> str:
    key = (api_key or os.getenv("OPENROUTER_API_KEY", "")).strip()
    if not key:
        return "OpenRouter key missing. Save OPENROUTER_API_KEY first."

    selected = selected_payload.get("selected_urls", [])
    compact_selected = selected[:200]
    compact_discovered = [
        {
            "url": r.get("url"),
            "lastmod": r.get("lastmod"),
            "path_category": r.get("path_category"),
            "selected": any(s.get("url") == r.get("url") for s in compact_selected),
        }
        for r in discovered_rows[:1000]
    ]
    prompt = (
        "You are explaining URL selection choices for a scrape planner.\n"
        f"Site: {site_url}\n"
        "Use plain language. Be specific about freshness, student-value, and dedupe/noise filtering.\n"
        f"User question: {question}\n\n"
        f"Selected URLs + reasons JSON:\n{json.dumps(compact_selected, ensure_ascii=True)}\n\n"
        f"Candidate snapshot JSON:\n{json.dumps(compact_discovered, ensure_ascii=True)}\n"
    )
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You explain ranking decisions clearly and concisely."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.0,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        return f"Could not fetch explanation from OpenRouter: {exc}"


def build_wiki_with_claude(run_root: Path, manifest_path: Path, wiki_root: Path) -> dict[str, Any]:
    wiki_root.mkdir(parents=True, exist_ok=True)
    prompt_path = run_root / "claude_wiki_prompt.md"
    prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else "Build wiki from manifest."
    task_prompt = (
        f"{prompt}\n\n"
        f"Manifest path: {manifest_path}\n"
        f"Write outputs under: {wiki_root}\n"
        "Return strict JSON: {\"status\":\"ok|error\",\"index_path\":\"...\",\"pages_written\":number,\"notes\":[...]}"
    )
    if not claude_available():
        return {"status": "error", "notes": ["claude CLI not installed"], "index_path": None, "pages_written": 0}
    try:
        result = subprocess.run(
            ["claude", "-p", task_prompt, "--output-format", "json"],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = _extract_json_payload(result.stdout) or {}
        write_json(run_root / "claude_wiki_run_result.json", payload)
        return payload
    except Exception as exc:
        payload = {"status": "error", "notes": [str(exc)], "index_path": None, "pages_written": 0}
        write_json(run_root / "claude_wiki_run_result.json", payload)
        return payload


def _build_url_selection_prompt(site_url: str, discovered_rows: list[dict[str, Any]], max_urls: int) -> str:
    compact = []
    for row in discovered_rows:
        compact.append(
            {
                "url": row.get("url"),
                "path_category": row.get("path_category"),
                "source_sitemap": row.get("source_sitemap"),
                "excluded_reason": row.get("excluded_reason"),
            }
        )
    return (
        "You are selecting the best pages for high-signal wiki building.\n"
        f"Site: {site_url}\n"
        f"Hard cap selected URLs: {max_urls}\n"
        "Rules:\n"
        "1) Prefer canonical content pages, docs, products, about, policies.\n"
        "2) Avoid tag/search/login/cart/author/feed/filter/sort/duplicate pages.\n"
        "3) Keep domain relevance broad for a wiki index.\n"
        "4) Return STRICT JSON only.\n"
        'Format: {"selection_method":"claude","selected_urls":[{"url":"...","reason":"...","priority":1}]}\n'
        f"Candidates JSON:\n{json.dumps(compact, ensure_ascii=True)}"
    )


def _build_student_useful_url_prompt(
    site_url: str,
    discovered_rows: list[dict[str, Any]],
    max_urls: int,
    batch_note: str = "",
) -> str:
    target_year = datetime.now(timezone.utc).year
    compact = []
    for row in discovered_rows:
        compact.append(
            {
                "url": row.get("url"),
                "lastmod": row.get("lastmod"),
                "path_category": row.get("path_category"),
                "source_sitemap": row.get("source_sitemap"),
                "excluded_reason": row.get("excluded_reason"),
            }
        )
    return (
        "Goal: pick URLs most useful for current/prospective students.\n"
        f"Site: {site_url}\n"
        f"Max URLs: {max_urls}\n"
        f"{batch_note}\n"
        f"Freshness target year: {target_year}\n"
        f"Strong preference for {target_year} and {target_year - 1} pages by lastmod or URL year.\n"
        f"Skip older-year pages when possible, except evergreen core student pages.\n"
        "Prioritize: admissions, academics, programs, tuition and aid, deadlines, housing, campus life, advising, registrar, student services.\n"
        "Deprioritize: login, search, tags, filter/sort, archive, tracking, and duplicate URLs.\n"
        "Return strict JSON only with schema:\n"
        '{"selected_urls":[{"url":"...","reason":"student value","priority":1}]}\n'
        f"Candidates JSON:\n{json.dumps(compact, ensure_ascii=True)}"
    )


def _heuristic_select(rows: list[dict[str, Any]], max_urls: int) -> list[dict[str, Any]]:
    bad_tokens = ("tag", "search", "login", "signup", "cart", "checkout", "feed", "filter", "sort", "wp-json")
    target_year = datetime.now(timezone.utc).year
    evergreen_tokens = (
        "admission",
        "apply",
        "program",
        "degree",
        "tuition",
        "aid",
        "scholarship",
        "housing",
        "campus-life",
        "student-services",
        "registrar",
        "advising",
        "deadline",
        "calendar",
    )
    picked = []
    for row in rows:
        url = (row.get("url") or "").lower()
        if row.get("excluded_reason"):
            continue
        if any(token in url for token in bad_tokens):
            continue
        score = 10
        year = _extract_year(row.get("url"), row.get("lastmod"))
        is_evergreen = any(token in url for token in evergreen_tokens)
        if year == target_year:
            score += 18
        elif year == target_year - 1:
            score += 10
        elif year is not None and year < target_year - 1:
            score -= 10 if is_evergreen else 28

        category = row.get("path_category")
        if category == "docs":
            score += 5
        if category == "content":
            score += 3
        if is_evergreen:
            score += 6
        if year is not None and year >= target_year:
            reason = f"fresh_{year}_student_relevance"
        elif year is not None:
            reason = f"older_{year}_kept_for_core_coverage" if is_evergreen else f"older_{year}_deprioritized"
        else:
            reason = "no_year_metadata_student_relevance"
        picked.append({"url": row.get("url"), "reason": "heuristic quality filter", "priority": score})
        picked[-1]["reason"] = reason
    picked.sort(key=lambda item: item["priority"], reverse=True)
    preferred = [p for p in picked if p["priority"] > 0]
    return preferred[:max_urls] if preferred else picked[:max_urls]


def _extract_year(url: Any, lastmod: Any) -> int | None:
    texts = [str(url or ""), str(lastmod or "")]
    for text in texts:
        for match in re.findall(r"(20\d{2})", text):
            year = int(match)
            if 2000 <= year <= 2100:
                return year
    return None


def _extract_json_payload(stdout: str) -> dict[str, Any] | None:
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            if "result" in data and isinstance(data["result"], str):
                try:
                    return json.loads(data["result"])
                except Exception:
                    pass
            return data
    except Exception:
        pass
    return None


def _loads_json_from_text(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("No JSON object found in model response.")
