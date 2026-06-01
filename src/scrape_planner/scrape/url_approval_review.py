from __future__ import annotations

import argparse
import json
import re
import shlex
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import requests

from ..infra.tmux_runner import TmuxRunner

APPROVED_MARKER = "<!-- scrape-planner:approved-urls:v1 -->"
DEFAULT_SESSION_PREFIX = "url-approval-agent"

KEEP_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("catalog", ("catalog",)),
    ("programs-degrees", ("program", "degree", "majors", "minor", "curriculum", "academics")),
    ("courses", ("course", "courses", "class-schedule")),
    ("advising", ("advising", "advisor", "degree-plan")),
    ("admissions", ("admission", "apply", "requirements")),
    ("aid-scholarships", ("financial-aid", "scholarship", "tuition", "cost", "funding")),
    ("calendar-exams", ("calendar", "deadline", "final-exam", "finals")),
    ("student-services", ("student", "housing", "dining", "health", "counseling", "parking", "accessibility", "orientation")),
    ("forms-handbooks", ("form", "forms", "handbook", "policy", "policies")),
    ("department-resource", ("department", "undergraduate", "graduate", "resources")),
)

REMOVE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("news-events", ("news", "news-events", "event", "events", "lecture", "lectures", "symposium", "calendar/event")),
    ("alumni", ("alumni", "class-notes", "recent-graduates")),
    ("donor-giving", ("give", "giving", "donor", "donors", "advancement")),
    ("annual-report", ("annual-report", "annualreports", "report-to-donors")),
    ("people-profiles", ("faculty", "staff", "people", "profiles", "directory", "bio", "emeriti", "person")),
    ("boards-admin", ("board", "trustee", "president", "provost", "administration")),
    ("employment", ("employment", "jobs", "careers")),
    ("templates-demo-search", ("template", "templates", "demo", "search", "component", "styleguide")),
)

DATED_SEGMENT_RE = re.compile(r"(?:^|/)(?:19|20)\d{2}(?:/|$)")
APPROVED_LINE_RE = re.compile(r"^(?P<prefix>\s*- \[[xX ]\]\s+)(?P<url>https?://\S+)\s*$")


@dataclass(frozen=True)
class ApprovedUrlEntry:
    url: str
    line_number: int
    raw_line: str


@dataclass
class UrlClassification:
    url: str
    bucket: str
    reason: str
    labels: list[str] = field(default_factory=list)
    http_status: int | None = None
    http_error: str = ""


@dataclass
class UrlApprovalReviewReport:
    generated_at: str
    approved_path: str
    total_urls: int
    counts: dict[str, int]
    top_level_counts: dict[str, int]
    dedman_counts: dict[str, int]
    classifications: list[UrlClassification]
    samples: dict[str, list[str]]
    remove_patterns: dict[str, list[str]]
    high_priority_keep_urls: list[str]
    dedman_keep_urls: list[str]
    http_failures: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["classifications"] = [asdict(item) for item in self.classifications]
        return payload


def parse_approved_urls(path: Path) -> list[ApprovedUrlEntry]:
    entries: list[ApprovedUrlEntry] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = APPROVED_LINE_RE.match(line)
        if match:
            entries.append(ApprovedUrlEntry(url=match.group("url").strip(), line_number=line_number, raw_line=line))
    return entries


def classify_url(url: str) -> UrlClassification:
    parsed = urlparse(url)
    path = parsed.path.lower().strip("/")
    tokens = tuple(part for part in re.split(r"[/_.-]+", path) if part)
    path_with_slashes = f"/{path}/"

    keep_labels = _matching_labels(path, tokens, KEEP_RULES)
    remove_labels = _matching_labels(path, tokens, REMOVE_RULES)
    if DATED_SEGMENT_RE.search(path_with_slashes):
        remove_labels.append("dated-path")

    # Canonical student-facing matches win over broad people/admin words only when they are specific.
    if keep_labels and not remove_labels:
        return UrlClassification(url=url, bucket="keep", reason=keep_labels[0], labels=keep_labels)
    if keep_labels and remove_labels:
        if any(label in keep_labels for label in {"catalog", "programs-degrees", "courses", "advising", "aid-scholarships", "student-services"}):
            return UrlClassification(url=url, bucket="review", reason=f"student-signal-with-noise:{keep_labels[0]}+{remove_labels[0]}", labels=keep_labels + remove_labels)
        return UrlClassification(url=url, bucket="remove", reason=remove_labels[0], labels=keep_labels + remove_labels)
    if remove_labels:
        return UrlClassification(url=url, bucket="remove", reason=remove_labels[0], labels=remove_labels)
    return UrlClassification(url=url, bucket="review", reason="unmatched", labels=[])


def build_review_report(
    approved_path: Path,
    *,
    http_check_limit: int = 0,
    fetcher: Any | None = None,
    now: str | None = None,
) -> UrlApprovalReviewReport:
    entries = parse_approved_urls(approved_path)
    classifications = [classify_url(entry.url) for entry in entries]
    if http_check_limit > 0:
        _apply_http_checks(classifications, limit=http_check_limit, fetcher=fetcher)

    counts = Counter(item.bucket for item in classifications)
    top_level_counts = Counter(_top_level_path(item.url) for item in classifications)
    dedman_items = [item for item in classifications if _is_dedman(item.url)]
    dedman_counts = Counter(item.bucket for item in dedman_items)
    samples: dict[str, list[str]] = defaultdict(list)
    for item in classifications:
        key = f"{item.bucket}:{item.reason}"
        if len(samples[key]) < 8:
            samples[key].append(item.url)

    remove_patterns: dict[str, list[str]] = defaultdict(list)
    for item in classifications:
        if item.bucket == "remove":
            remove_patterns[item.reason].append(_pattern_for_url(item.url, item.reason))
    compact_patterns = {reason: sorted(set(patterns))[:16] for reason, patterns in remove_patterns.items()}

    high_priority_keep = [item.url for item in classifications if item.bucket == "keep"][:75]
    dedman_keep = [item.url for item in dedman_items if item.bucket in {"keep", "review"}][:75]
    http_failures = [
        {"url": item.url, "status": item.http_status, "error": item.http_error, "bucket": item.bucket, "reason": item.reason}
        for item in classifications
        if item.http_status and item.http_status >= 400 or item.http_error
    ]
    return UrlApprovalReviewReport(
        generated_at=now or datetime.now(timezone.utc).isoformat(),
        approved_path=str(approved_path),
        total_urls=len(classifications),
        counts=dict(counts),
        top_level_counts=dict(top_level_counts.most_common(30)),
        dedman_counts=dict(dedman_counts),
        classifications=classifications,
        samples=dict(samples),
        remove_patterns=compact_patterns,
        high_priority_keep_urls=high_priority_keep,
        dedman_keep_urls=dedman_keep,
        http_failures=http_failures,
    )


def write_report_files(report: UrlApprovalReviewReport, report_prefix: Path) -> dict[str, str]:
    report_prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = report_prefix.with_suffix(".json")
    md_path = report_prefix.with_suffix(".md")
    json_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(render_markdown_report(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def render_markdown_report(report: UrlApprovalReviewReport) -> str:
    lines = [
        "# Agent-Assisted URL Approval Review",
        "",
        f"Generated: `{report.generated_at}`",
        f"Approved file: `{report.approved_path}`",
        "",
        "## Counts",
        "",
        f"- Total approved URLs: **{report.total_urls:,}**",
    ]
    for bucket in ("keep", "remove", "review"):
        lines.append(f"- {bucket.title()}: **{int(report.counts.get(bucket, 0)):,}**")
    lines.extend(["", "## Top-level path groups", ""])
    for group, count in report.top_level_counts.items():
        lines.append(f"- `{group}`: {count:,}")
    lines.extend(["", "## Dedman College", ""])
    for bucket in ("keep", "remove", "review"):
        lines.append(f"- {bucket.title()}: **{int(report.dedman_counts.get(bucket, 0)):,}**")
    lines.extend(["", "### Dedman keep/review examples", ""])
    for url in report.dedman_keep_urls[:25]:
        lines.append(f"- {url}")
    lines.extend(["", "## Proposed removal patterns", ""])
    for reason, patterns in sorted(report.remove_patterns.items()):
        lines.append(f"### {reason}")
        for pattern in patterns[:16]:
            lines.append(f"- `{pattern}`")
        lines.append("")
    lines.extend(["## Representative samples", ""])
    for key, urls in sorted(report.samples.items()):
        lines.append(f"### {key}")
        for url in urls[:8]:
            lines.append(f"- {url}")
        lines.append("")
    if report.http_failures:
        lines.extend(["## HTTP failures", ""])
        for failure in report.http_failures[:100]:
            lines.append(f"- `{failure.get('status') or failure.get('error')}` {failure.get('url')}")
        lines.append("")
    lines.extend([
        "## Confirmation gate",
        "",
        "This is a dry-run report. Do not update `approved_urls.md` until the operator confirms exact URL or pattern removals.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def apply_confirmed_removals(approved_path: Path, remove_urls: Iterable[str]) -> dict[str, Any]:
    remove_set = {str(url).strip() for url in remove_urls if str(url).strip()}
    if not remove_set:
        return {"removed": 0, "remaining": len(parse_approved_urls(approved_path))}
    lines = approved_path.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    removed: list[str] = []
    for line in lines:
        match = APPROVED_LINE_RE.match(line)
        if match and match.group("url").strip() in remove_set:
            removed.append(match.group("url").strip())
            continue
        output.append(line)
    approved_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    return {"removed": len(removed), "remaining": len(parse_approved_urls(approved_path)), "removed_urls": removed}


def validate_approved_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    entries = parse_approved_urls(path)
    urls = [entry.url for entry in entries]
    canonical_categories = {
        "catalog": any("catalog" in url.lower() for url in urls),
        "advising": any("advis" in url.lower() for url in urls),
        "financial_aid": any(("financial-aid" in url.lower() or "scholarship" in url.lower()) for url in urls),
        "calendar": any("calendar" in url.lower() or "deadline" in url.lower() for url in urls),
        "student_services": any("student" in url.lower() for url in urls),
        "dedman_academics": any("/dedman" in url.lower() and ("academic" in url.lower() or "program" in url.lower()) for url in urls),
    }
    return {
        "has_marker": APPROVED_MARKER in text,
        "total_urls": len(urls),
        "duplicate_count": len(urls) - len(set(urls)),
        "canonical_categories": canonical_categories,
        "ok": APPROVED_MARKER in text and bool(urls) and all(canonical_categories.values()),
    }


def default_session_name(site_id: str) -> str:
    # Avoid dots/colons in tmux target names; tmux treats them as window/pane separators.
    slug = re.sub(r"[^a-zA-Z0-9-]+", "-", site_id.strip().lower()).strip("-") or "site"
    return f"{DEFAULT_SESSION_PREFIX}-{slug}"


def launch_url_review_session(
    *,
    site_root: Path,
    site_id: str,
    repo_root: Path,
    session_name: str | None = None,
    runner: TmuxRunner | None = None,
    http_check_limit: int = 0,
) -> dict[str, Any]:
    session = session_name or default_session_name(site_id)
    tmux = runner or TmuxRunner()
    attach_command = f"tmux attach -t {shlex.quote(session)}"
    capture_command = f"tmux capture-pane -p -S -200 -t {shlex.quote(session)}"
    if tmux.session_exists(session):
        return {
            "status": "existing",
            "tmux_session": session,
            "attach_command": attach_command,
            "capture_command": capture_command,
        }
    report_prefix = site_root / "url_approval_review"
    approved_path = site_root / "approved_urls.md"
    command = " ".join(
        [
            "python3", "-m", "src.scrape_planner.scrape.url_approval_review", "dry-run",
            "--approved-path", shlex.quote(str(approved_path)),
            "--report-prefix", shlex.quote(str(report_prefix)),
            "--http-check-limit", str(int(http_check_limit)),
        ]
    )
    result = tmux.start(session, command, str(repo_root))
    return {
        "status": "started" if result.get("ok") else "failed",
        "tmux_session": session,
        "attach_command": attach_command,
        "capture_command": capture_command,
        "command": command,
        "error": result.get("error", ""),
    }


def _matching_labels(path: str, tokens: tuple[str, ...], rules: tuple[tuple[str, tuple[str, ...]], ...]) -> list[str]:
    labels: list[str] = []
    token_set = set(tokens)
    for label, needles in rules:
        if any(needle in path or needle in token_set for needle in needles):
            labels.append(label)
    return labels


def _top_level_path(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    return f"/{parts[0]}" if parts else "/"


def _is_dedman(url: str) -> bool:
    return urlparse(url).path.lower().startswith("/dedman")


def _pattern_for_url(url: str, reason: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if not parts:
        return "/"
    if reason == "dated-path":
        for index, part in enumerate(parts):
            if re.fullmatch(r"(?:19|20)\d{2}", part):
                return "/" + "/".join(parts[: index + 1]) + "/…"
    return "/" + "/".join(parts[: min(len(parts), 3)]) + ("/…" if len(parts) > 3 else "")


def _apply_http_checks(classifications: list[UrlClassification], *, limit: int, fetcher: Any | None = None) -> None:
    client = fetcher or requests
    checked = 0
    candidates = [item for item in classifications if item.bucket in {"remove", "review"} or _is_dedman(item.url)]
    for item in candidates:
        if checked >= limit:
            break
        checked += 1
        try:
            response = client.head(item.url, allow_redirects=True, timeout=(3, 8))
            if getattr(response, "status_code", 0) in {405, 403}:
                response = client.get(item.url, allow_redirects=True, timeout=(3, 10), stream=True)
            item.http_status = int(getattr(response, "status_code", 0) or 0) or None
            if item.http_status and item.http_status >= 500:
                item.bucket = "remove" if item.bucket == "remove" else "review"
                item.reason = f"http-{item.http_status}"
                item.labels.append(item.reason)
        except Exception as exc:  # pragma: no cover - requests exceptions vary by version
            item.http_error = exc.__class__.__name__
            if item.bucket == "keep":
                item.bucket = "review"
                item.reason = "http-error"
                item.labels.append("http-error")


def _load_report_remove_urls(report_path: Path) -> list[str]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    rows = payload.get("classifications") if isinstance(payload, dict) else []
    return [str(row.get("url")) for row in rows if isinstance(row, dict) and row.get("bucket") == "remove" and row.get("url")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review and safely update approved_urls.md for student-focused wiki sources.")
    sub = parser.add_subparsers(dest="command", required=True)

    dry = sub.add_parser("dry-run", help="Classify approved URLs and write JSON/Markdown preview reports.")
    dry.add_argument("--approved-path", type=Path, required=True)
    dry.add_argument("--report-prefix", type=Path, required=True)
    dry.add_argument("--http-check-limit", type=int, default=0)

    apply = sub.add_parser("apply", help="Apply remove URLs from a dry-run JSON report after explicit confirmation.")
    apply.add_argument("--approved-path", type=Path, required=True)
    apply.add_argument("--report-json", type=Path, required=True)
    apply.add_argument("--confirm-apply", action="store_true")

    validate = sub.add_parser("validate", help="Validate approved_urls.md format and canonical student category coverage.")
    validate.add_argument("--approved-path", type=Path, required=True)

    launch = sub.add_parser("launch-agent", help="Start or reuse the tmux-backed URL approval review agent.")
    launch.add_argument("--site-root", type=Path, required=True)
    launch.add_argument("--site-id", required=True)
    launch.add_argument("--repo-root", type=Path, default=Path.cwd())
    launch.add_argument("--session-name")
    launch.add_argument("--http-check-limit", type=int, default=0)

    args = parser.parse_args(argv)
    if args.command == "dry-run":
        report = build_review_report(args.approved_path, http_check_limit=max(int(args.http_check_limit), 0))
        paths = write_report_files(report, args.report_prefix)
        print(json.dumps({"status": "dry-run-complete", "counts": report.counts, "paths": paths}, indent=2, sort_keys=True))
        return 0
    if args.command == "apply":
        if not args.confirm_apply:
            raise SystemExit("Refusing to modify approved_urls.md without --confirm-apply")
        remove_urls = _load_report_remove_urls(args.report_json)
        result = apply_confirmed_removals(args.approved_path, remove_urls)
        result["validation"] = validate_approved_file(args.approved_path)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "validate":
        print(json.dumps(validate_approved_file(args.approved_path), indent=2, sort_keys=True))
        return 0
    if args.command == "launch-agent":
        result = launch_url_review_session(
            site_root=args.site_root,
            site_id=args.site_id,
            repo_root=args.repo_root,
            session_name=args.session_name,
            http_check_limit=max(int(args.http_check_limit), 0),
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("status") in {"started", "existing"} else 1
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
