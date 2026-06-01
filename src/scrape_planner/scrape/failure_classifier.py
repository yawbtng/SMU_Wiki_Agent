from __future__ import annotations

from typing import Any


def classify_failure(
    *,
    http_status: int | None,
    content_type: str | None,
    text_length: int,
    link_density: float,
    error: Exception | None = None,
) -> str | None:
    if error is not None:
        name = type(error).__name__.lower()
        msg = str(error).lower()
        if "timeout" in name or "timeout" in msg:
            return "timeout"
        if "robot" in msg:
            return "robots_disallowed"
        if "blocked" in msg or "captcha" in msg:
            return "blocked"
        return "parse_error"

    if http_status is not None and http_status >= 400:
        if http_status in (403, 429):
            return "blocked"
        return "http_error"

    if content_type and "html" not in content_type.lower():
        return "non_html"

    if text_length == 0:
        return "empty_content"

    if link_density > 0.25 and text_length < 700:
        return "too_low_signal"

    return None


def to_failure_record(url: str, reason: str, context: dict[str, Any]) -> dict[str, Any]:
    payload = {"url": url, "reason": reason}
    payload.update(context)
    return payload

