from __future__ import annotations

import json
from pathlib import Path

from src.scrape_planner.app.pi_agent import (
    build_pi_json_command,
    read_pi_events_after,
    summarize_pi_event,
)


def test_build_pi_json_command_uses_json_mode(tmp_path: Path) -> None:
    events = tmp_path / "job-pi-events.jsonl"
    command = build_pi_json_command(
        pi_bin="/usr/bin/pi",
        prompt="rebuild wiki",
        events_path=events,
        skill_paths=[Path("/repo/.pi/skills/llm-wiki-noninteractive")],
    )
    assert "--mode" in command
    assert "json" in command
    assert str(events) in command
    assert "tee -a" in command


def test_read_pi_events_after_offset(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        json.dumps({"type": "agent_start"}) + "\n"
        + json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "Hi"}}) + "\n",
        encoding="utf-8",
    )
    first, offset = read_pi_events_after(path, 0, limit=10)
    assert len(first) == 2
    second, _ = read_pi_events_after(path, offset, limit=10)
    assert second == []


def test_summarize_pi_event_text_delta() -> None:
    label = summarize_pi_event(
        {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "hello"}},
    )
    assert label == "hello"
