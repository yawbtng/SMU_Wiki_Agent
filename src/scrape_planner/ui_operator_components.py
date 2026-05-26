from __future__ import annotations

from html import escape
from typing import Any, Iterable, Mapping


_STATUS_COLORS: dict[str, dict[str, str]] = {
    "active": {
        "background": "rgba(var(--primary-rgb, 204, 120, 92), 0.18)",
        "border": "rgba(var(--primary-rgb, 204, 120, 92), 0.46)",
        "text": "rgba(var(--on-dark-rgb, 250, 249, 245), 0.94)",
    },
    "ready": {
        "background": "rgba(154, 194, 146, 0.18)",
        "border": "rgba(154, 194, 146, 0.42)",
        "text": "#d5ebcb",
    },
    "warning": {
        "background": "rgba(216, 162, 97, 0.18)",
        "border": "rgba(216, 162, 97, 0.44)",
        "text": "#f4d6ae",
    },
    "danger": {
        "background": "rgba(191, 92, 84, 0.22)",
        "border": "rgba(191, 92, 84, 0.50)",
        "text": "#f6beb8",
    },
    "neutral": {
        "background": "rgba(var(--primary-rgb, 204, 120, 92), 0.13)",
        "border": "rgba(var(--primary-rgb, 204, 120, 92), 0.30)",
        "text": "rgba(var(--on-dark-rgb, 250, 249, 245), 0.84)",
    },
}


def _status_tone_tokens(tone: str) -> dict[str, str]:
    colors = _STATUS_COLORS.get(tone, _STATUS_COLORS["neutral"])
    if tone == "active":
        return {
            "panel_background": "linear-gradient(145deg, rgba(24, 23, 21, 0.98), rgba(37, 35, 32, 0.96))",
            "panel_border": "rgba(var(--on-dark-rgb, 250, 249, 245), 0.12)",
            "panel_title": "var(--on-dark, #faf9f5)",
            "panel_body": "rgba(var(--on-dark-rgb, 250, 249, 245), 0.86)",
            "panel_muted": "rgba(var(--on-dark-rgb, 250, 249, 245), 0.78)",
            "badge_background": colors["background"],
            "badge_border": colors["border"],
            "badge_text": colors["text"],
            "accent": "rgba(102, 242, 213, 0.72)",
            "sheen": "radial-gradient(circle at top right, rgba(102, 242, 213, 0.18), transparent 28%), radial-gradient(circle at bottom left, rgba(255, 209, 102, 0.12), transparent 24%)",
        }
    return {
        "panel_background": "linear-gradient(145deg, rgba(24, 23, 21, 0.96), rgba(32, 30, 28, 0.94))",
        "panel_border": "rgba(var(--on-dark-rgb, 250, 249, 245), 0.10)",
        "panel_title": "var(--on-dark, #faf9f5)",
        "panel_body": "rgba(var(--on-dark-rgb, 250, 249, 245), 0.86)",
        "panel_muted": "rgba(var(--on-dark-rgb, 250, 249, 245), 0.76)",
        "badge_background": colors["background"],
        "badge_border": colors["border"],
        "badge_text": colors["text"],
        "accent": "rgba(102, 242, 213, 0.70)" if tone in {"ready", "neutral"} else colors["border"],
        "sheen": (
            "radial-gradient(circle at top right, rgba(191, 92, 84, 0.22), transparent 30%), radial-gradient(circle at bottom left, rgba(255, 209, 102, 0.10), transparent 24%)"
            if tone == "danger"
            else "radial-gradient(circle at top right, rgba(102, 242, 213, 0.16), transparent 30%), radial-gradient(circle at bottom left, rgba(255, 209, 102, 0.11), transparent 24%)"
        ),
    }


def status_badge_html(label: str, tone: str = "neutral") -> str:
    colors = _status_tone_tokens(tone)
    safe_label = escape(str(label), quote=True)
    return (
        "<span style=\""
        "display: inline-flex; "
        "align-items: center; "
        "gap: 6px; "
        "padding: 5px 10px; "
        "border-radius: 999px; "
        f"border: 1px solid {colors['badge_border']}; "
        f"background: {colors['badge_background']}; "
        f"color: {colors['badge_text']}; "
        "font-size: 0.72rem; "
        "font-weight: 650; "
        "letter-spacing: 0.12em; "
        "text-transform: uppercase; "
        "\">"
        f"{safe_label}"
        "</span>"
    )


def render_status_band(
    *,
    title: str,
    subtitle: str,
    status_label: str,
    tone: str,
    action_label: str | None = None,
) -> None:
    import streamlit as st

    colors = _status_tone_tokens(tone)
    safe_title = escape(str(title), quote=True)
    safe_subtitle = escape(str(subtitle), quote=True)
    badge = status_badge_html(status_label, tone)
    safe_action = escape(str(action_label), quote=True) if action_label else ""
    action_html = (
        "<div style=\""
        "font-size: 0.78rem; "
        "font-weight: 820; "
        f"color: {colors['panel_title']}; "
        "text-align: right; "
        "letter-spacing: 0.10em; "
        "text-transform: uppercase; "
        "text-shadow: 0 1px 0 rgba(0,0,0,0.45); "
        "\">"
        f"↳ {safe_action}"
        "</div>"
        if safe_action
        else ""
    )
    st.markdown(
        (
            "<section style=\""
            "border: 0; "
            "border-radius: 18px; "
            "padding: 18px 21px; "
            f"background: {colors['sheen']}, {colors['panel_background']}; "
            "margin: 0 0 14px 0; "
            "box-shadow: 0 16px 38px rgba(24, 23, 21, 0.14), inset 0 1px 0 rgba(255,255,255,0.05); "
            "position: relative; "
            "overflow: hidden; "
            "\">"
            "<div style=\""
            "display: flex; "
            "align-items: flex-start; "
            "justify-content: space-between; "
            "gap: 16px; "
            "\">"
            "<div>"
            "<div style=\"font-family: var(--code-font, monospace); font-size: 0.62rem; font-weight: 780; letter-spacing: 0.16em; text-transform: uppercase; margin-bottom: 0.38rem; "
            f"color: {colors['accent']}; text-shadow: 0 0 14px rgba(102,242,213,0.24);\">COMMAND CENTER // {escape(str(status_label), quote=True)}</div>"
            "<div style=\"font-family: var(--display-font, 'Iowan Old Style', 'Palatino Linotype', Georgia, serif); font-size: 1.24rem; font-weight: 650; "
            f"color: {colors['panel_title']}; letter-spacing: -0.025em; text-shadow: 0 1px 0 rgba(0,0,0,0.42);\">{safe_title}</div>"
            "<div style=\"font-size: 0.86rem; "
            f"color: {colors['panel_body']}; "
            f"margin-top: 3px;\">{safe_subtitle}</div>"
            "</div>"
            "<div style=\""
            "display: flex; "
            "flex-direction: column; "
            "gap: 8px; "
            "align-items: flex-end; "
            "\">"
            f"{badge}"
            f"{action_html}"
            "</div>"
            "</div>"
            "</section>"
        ),
        unsafe_allow_html=True,
    )


def render_metric_strip(metrics: Iterable[Mapping[str, Any]]) -> None:
    import streamlit as st

    metric_items = list(metrics)
    if not metric_items:
        return

    cards: list[str] = []
    for metric in metric_items:
        label = escape(str(metric.get("label", "")), quote=True)
        value = escape(str(metric.get("value", "")), quote=True)
        delta = metric.get("delta")
        help_text = metric.get("help")
        footer_parts = [str(part) for part in (delta, help_text) if part is not None and str(part).strip()]
        footer_html = (
            f'<div class="operator-metric-foot">{" · ".join(escape(part, quote=True) for part in footer_parts)}</div>'
            if footer_parts
            else ""
        )
        cards.append(
            "<article class=\"operator-metric-card\">"
            "<div class=\"operator-metric-label\">"
            "<span class=\"operator-metric-sigil\">◆</span>"
            f"<span>{label}</span>"
            "</div>"
            f"<div class=\"operator-metric-value\">{value}</div>"
            f"{footer_html}"
            "</article>"
        )

    column_count = max(1, min(len(metric_items), 4))
    st.markdown(
        f'<div class="operator-metric-strip" style="--metric-columns: {column_count};">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def render_operator_details(
    label: str,
    body: Mapping[str, Any] | str,
    *,
    expanded: bool = False,
) -> None:
    import streamlit as st

    with st.expander(label or "Operator Details", expanded=expanded):
        st.caption("Operator detail payload")
        if isinstance(body, Mapping):
            st.json(dict(body))
        else:
            st.code(str(body))
