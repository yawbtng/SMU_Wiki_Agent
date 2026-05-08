from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from .claude_manifest import build_claude_manifest
from .llm_orchestrator import build_wiki_with_claude
from .storage import read_json
from .wiki_planner import build_topic_wiki_prompt, suggest_wiki_topics


def render_claude_plan_section(*, run_root: Path, site_url: str, run_id: str) -> None:
    st.subheader("Topic Wiki Planner")
    if st.button("Suggest Wiki Topics from Source Data", type="primary"):
        plan = suggest_wiki_topics(run_root)
        st.session_state["wiki_topic_plan"] = plan
        st.success(f"Suggested topics from {plan['source_count']} source files.")

    topic_plan = st.session_state.get("wiki_topic_plan") or read_json(run_root / "wiki_topic_plan.json", {})
    if topic_plan.get("topics"):
        topic_df = pd.DataFrame(
            [
                {
                    "selected": row.get("selected", False),
                    "topic": row.get("topic"),
                    "source_count": row.get("source_count", 0),
                }
                for row in topic_plan["topics"]
            ]
        )
        edited_topics = st.data_editor(
            topic_df,
            hide_index=True,
            use_container_width=True,
            column_config={"selected": st.column_config.CheckboxColumn(default=True)},
            key="topic_wiki_editor",
        )
        if st.button("Generate Topic Wiki Prompt"):
            selected_by_topic = {row["topic"]: row["selected"] for row in edited_topics.to_dict("records")}
            selected_topics = []
            for row in topic_plan["topics"]:
                row = dict(row)
                row["selected"] = bool(selected_by_topic.get(row["topic"]))
                selected_topics.append(row)
            prompt = build_topic_wiki_prompt(run_root, selected_topics)
            st.success("Topic wiki prompt generated.")
            st.code(prompt, language="markdown")

    if st.button("Generate Claude Manifest + Prompt", type="primary"):
        manifest = build_claude_manifest(run_root, site_url, run_id)
        st.success("Claude artifacts generated.")
        st.json(manifest["counts"])
    if st.button("Run Claude Wiki Build"):
        manifest_path = run_root / "claude_wiki_manifest.json"
        wiki_root = run_root / "wiki"
        result = build_wiki_with_claude(run_root, manifest_path, wiki_root)
        st.json(result)
    manifest_path = run_root / "claude_wiki_manifest.json"
    prompt_path = run_root / "claude_wiki_prompt.md"
    st.write(f"Manifest path: `{manifest_path}`")
    st.write(f"Prompt path: `{prompt_path}`")
    if prompt_path.exists():
        st.code(prompt_path.read_text(encoding="utf-8"), language="markdown")

