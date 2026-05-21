from __future__ import annotations

from html import escape
from typing import Any, Iterable, Mapping


_STATUS_COLORS: dict[str, dict[str, str]] = {
    "active": {
        "background": "#ecfeff",
        "border": "#67e8f9",
        "text": "#155e75",
    },
    "ready": {
        "background": "#ecfdf5",
        "border": "#6ee7b7",
        "text": "#065f46",
    },
    "warning": {
        "background": "#fffbeb",
        "border": "#fcd34d",
        "text": "#92400e",
    },
    "danger": {
        "background": "#fef2f2",
        "border": "#fca5a5",
        "text": "#991b1b",
    },
    "neutral": {
        "background": "#f8fafc",
        "border": "#cbd5e1",
        "text": "#334155",
    },
}


def status_badge_html(label: str, tone: str = "neutral") -> str:
    colors = _STATUS_COLORS.get(tone, _STATUS_COLORS["neutral"])
    safe_label = escape(str(label), quote=True)
    return (
        "<span style=\""
        "display: inline-flex; "
        "align-items: center; "
        "gap: 6px; "
        "padding: 4px 9px; "
        "border-radius: 8px; "
        f"border: 1px solid {colors['border']}; "
        f"background: {colors['background']}; "
        f"color: {colors['text']}; "
        "font-size: 0.78rem; "
        "font-weight: 700; "
        "letter-spacing: 0.02em; "
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

    safe_title = escape(str(title), quote=True)
    safe_subtitle = escape(str(subtitle), quote=True)
    badge = status_badge_html(status_label, tone)
    safe_action = escape(str(action_label), quote=True) if action_label else ""
    action_html = (
        "<div style=\""
        "font-size: 0.82rem; "
        "font-weight: 700; "
        "color: #475569; "
        "text-align: right; "
        "\">"
        f"{safe_action}"
        "</div>"
        if safe_action
        else ""
    )
    st.markdown(
        (
            "<section style=\""
            "border: 1px solid #dbe3ef; "
            "border-radius: 14px; "
            "padding: 16px 18px; "
            "background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%); "
            "margin: 0 0 14px 0; "
            "\">"
            "<div style=\""
            "display: flex; "
            "align-items: flex-start; "
            "justify-content: space-between; "
            "gap: 16px; "
            "\">"
            "<div>"
            "<div style=\"font-size: 1.05rem; font-weight: 800; "
            f"color: #0f172a;\">{safe_title}</div>"
            "<div style=\"font-size: 0.9rem; color: #475569; "
            f"margin-top: 4px;\">{safe_subtitle}</div>"
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

    columns = st.columns(len(metric_items))
    for column, metric in zip(columns, metric_items):
        label = str(metric.get("label", ""))
        value = metric.get("value", "")
        delta = metric.get("delta")
        help_text = metric.get("help")
        column.metric(
            label=label,
            value=value,
            delta=delta,
            help=str(help_text) if help_text is not None else None,
        )


def render_operator_details(
    label: str,
    body: Mapping[str, Any] | str,
    *,
    expanded: bool = False,
) -> None:
    import streamlit as st

    with st.expander(label or "Operator Details", expanded=expanded):
        if isinstance(body, Mapping):
            st.json(dict(body))
        else:
            st.code(str(body))
