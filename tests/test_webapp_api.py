from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.scrape_planner.core.storage import write_json
from src.scrape_planner.runtime.agent_run_metrics import AgentRunMetricsRepository, build_embedding_metric_event, build_llm_metric_event
from src.scrape_planner.webapp.api import create_app, run_embedding_job, sse_event, tmux_session_exists


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    data_root = tmp_path / "data"
    site_root = data_root / "sites" / "demo.edu"
    reports = site_root / "wiki" / "reports"
    reports.mkdir(parents=True)
    (site_root / "raw_sources").mkdir(parents=True)
    (site_root / "raw_sources" / "registry.jsonl").write_text("", encoding="utf-8")
    (reports / "wiki-agent-run-latest.json").write_text(
        json.dumps({"status": "running", "tmux_session": "wiki-demo-stale"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))
    return TestClient(create_app())


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data_root"].endswith("/data")


def test_put_app_state_persists_wiki_tmux_settings(client: TestClient) -> None:
    response = client.put(
        "/api/app-state",
        json={
            "payload": {
                "tmux_session_grace_seconds": 600,
                "wiki_builder_runtime": "python",
                "wiki_skip_pi": True,
                "tmux_archive_sessions": False,
                "tmux_reconcile_expired_sessions": False,
                "pi_cmd": "/usr/local/bin/pi",
            }
        },
    )
    assert response.status_code == 200
    state = response.json()["state"]
    assert state["tmux_session_grace_seconds"] == 600
    assert state["wiki_builder_runtime"] == "python"
    assert state["wiki_skip_pi"] is True
    assert state["tmux_archive_sessions"] is False
    assert state["tmux_reconcile_expired_sessions"] is False
    assert state["pi_cmd"] == "/usr/local/bin/pi"


def test_put_app_state_refreshes_openrouter_env_for_running_app(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    response = client.put(
        "/api/app-state",
        json={"payload": {"openrouter_api_key": "saved-openrouter-key"}},
    )

    assert response.status_code == 200
    assert response.json()["state"]["openrouter_api_key"] == "saved-openrouter-key"
    assert os.environ["OPENROUTER_API_KEY"] == "saved-openrouter-key"


def test_list_sites(client: TestClient) -> None:
    response = client.get("/api/sites")
    assert response.status_code == 200
    payload = response.json()
    assert payload["sites"][0]["id"] == "demo.edu"
    assert payload["sites"][0]["has_wiki"] is True


def test_delete_site_removes_data_and_app_state(client: TestClient, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    remove_root = data_root / "sites" / "remove-me.edu"
    remove_root.mkdir(parents=True)
    (remove_root / "raw_sources").mkdir()
    write_json(
        data_root / "app_state.json",
        {
            "active_workspace_id": "remove-me.edu",
            "last_site_id": "remove-me.edu",
            "workspaces": [
                {"id": "demo.edu", "name": "demo.edu", "url": "https://demo.edu"},
                {"id": "remove-me.edu", "name": "remove-me.edu", "url": "https://remove-me.edu"},
            ],
            "site_history": ["https://remove-me.edu", "https://demo.edu"],
        },
    )

    response = client.delete("/api/sites/remove-me.edu")
    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] is True
    assert payload["site_id"] == "remove-me.edu"
    assert not remove_root.exists()
    assert all(site["id"] != "remove-me.edu" for site in payload["sites"])
    state = payload["app_state"]
    assert state["active_workspace_id"] == ""
    assert state["last_site_id"] == ""
    assert all(item.get("id") != "remove-me.edu" for item in state["workspaces"])
    assert "https://remove-me.edu" not in state["site_history"]


def test_delete_site_removes_symlink_without_following_target(client: TestClient, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    external = tmp_path / "external-site"
    external.mkdir(parents=True)
    (external / "wiki").mkdir()
    link_root = data_root / "sites" / "linked.example"
    link_root.parent.mkdir(parents=True, exist_ok=True)
    link_root.symlink_to(external, target_is_directory=True)
    write_json(
        data_root / "app_state.json",
        {
            "workspaces": [{"id": "linked.example", "name": "linked.example", "url": "https://linked.example"}],
            "site_history": ["https://linked.example"],
        },
    )

    response = client.delete("/api/sites/linked.example")

    assert response.status_code == 200
    assert not link_root.exists()
    assert external.exists()
    payload = response.json()
    assert all(site["id"] != "linked.example" for site in payload["sites"])
    assert all(item.get("id") != "linked.example" for item in payload["app_state"]["workspaces"])


def test_delete_site_not_found(client: TestClient) -> None:
    response = client.delete("/api/sites/missing.example")
    assert response.status_code == 404


def test_site_overview_compact_payload(client: TestClient) -> None:
    response = client.get("/api/sites/demo.edu/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["site_id"] == "demo.edu"
    assert "wiki" in payload
    assert "agent" in payload
    assert "rows" not in payload.get("raw_sources", {})
    assert "latest_report" not in payload.get("wiki", {})


def test_wiki_agent_stale_running(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.scrape_planner.webapp.api.tmux_session_exists",
        lambda session: False,
    )
    response = client.get("/api/sites/demo.edu/wiki/agent")
    assert response.status_code == 200
    payload = response.json()
    assert payload["stale_running"] is True
    assert payload["run"]["status"] == "running"


def test_sse_framing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.scrape_planner.webapp.api as api_module

    async def one_shot_stream(site_id: str, interval: float, is_disconnected=None):
        yield sse_event("site", {"site_id": site_id, "ok": True})

    monkeypatch.setattr(api_module, "site_event_stream", one_shot_stream)

    with client.stream("GET", "/api/stream/sites/demo.edu?interval=0.5") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = response.read().decode("utf-8")
        assert "event: site" in body
        assert "data:" in body
        assert "demo.edu" in body


def test_site_overview_missing_site(client: TestClient) -> None:
    response = client.get("/api/sites/missing.example/overview")
    assert response.status_code == 404


def test_discover_endpoint_persists_any_university_from_robots_sitemap(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.scrape_planner.core.models import DiscoveredURL
    from src.scrape_planner.scrape.sitemap_discovery import DiscoveryResult

    def fake_discover(site_url: str, timeout: int = 15) -> DiscoveryResult:
        return DiscoveryResult(
            site_url="https://www.example.edu",
            sitemap_sources=["https://www.example.edu/sitemap.xml"],
            urls=[
                DiscoveredURL(url="https://www.example.edu/admission/apply", source_sitemap="https://www.example.edu/sitemap.xml", selected=True),
                DiscoveredURL(url="https://www.example.edu/news/2020/01/01/old", source_sitemap="https://www.example.edu/sitemap.xml", selected=False, excluded_reason="old_dated_news_or_article"),
            ],
            notes=["Using sitemap from robots.txt."],
        )

    monkeypatch.setattr("src.scrape_planner.webapp.api.discover_site_urls", fake_discover)

    response = client.post("/api/discover", json={"site_url": "https://www.example.edu/robots.txt", "timeout": 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["site_id"] == "www.example.edu"
    assert payload["discovered_total"] == 2
    assert payload["eligible_total"] == 1
    site_root = tmp_path / "data" / "sites" / "www.example.edu"
    assert json.loads((site_root / "discovered_urls.json").read_text(encoding="utf-8"))[0]["url"] == "https://www.example.edu/admission/apply"
    app_state = json.loads((tmp_path / "data" / "app_state.json").read_text(encoding="utf-8"))
    assert app_state["active_workspace_id"] == "www.example.edu"
    assert app_state["workspaces"] == [{"id": "www.example.edu", "name": "www.example.edu", "url": "https://www.example.edu"}]


def test_approved_urls_markdown_round_trip_draft_and_chat(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    site_root = tmp_path / "data" / "sites" / "demo.edu"
    write_json(
        site_root / "discovered_urls.json",
        [
            {"url": "https://demo.edu/enrollment-services/registrar/academic-calendar", "title": "Academic Calendar"},
            {"url": "https://demo.edu/enrollment-services/registrar/transcripts", "title": "Transcripts"},
            {"url": "https://demo.edu/student-life/housing", "title": "Housing"},
            {"url": "https://demo.edu/cox/academics/mba", "title": "MBA"},
            {"url": "https://demo.edu/cox/admission/apply", "title": "Cox Apply"},
            {"url": "https://demo.edu/dedman/academics", "title": "Dedman Academics"},
            {"url": "https://demo.edu/news/2021/01/01/old-story", "title": "Old Story"},
        ],
    )

    saved = client.post(
        "/api/sites/demo.edu/approved-urls/chat",
        json={"message": "approve registrar calendar", "autosave": True, "limit": 20},
    )
    assert saved.status_code == 200
    assert "academic-calendar" in saved.json()["markdown"]
    assert "old-story" not in saved.json()["markdown"]
    assert saved.json()["count"] == 2
    assert saved.json()["groups"] == [{"subpath": "/enrollment-services/registrar", "count": 2, "examples": ["https://demo.edu/enrollment-services/registrar/academic-calendar", "https://demo.edu/enrollment-services/registrar/transcripts"]}]
    available = {row["subpath"]: row["count"] for row in saved.json()["available_groups"]}
    assert available["/cox"] == 2
    assert available["/dedman"] == 1
    assert (site_root / "approved_urls.md").exists()

    add = client.post(
        "/api/sites/demo.edu/approved-urls/chat",
        json={"base_prompt": "approve student services", "message": "also approve housing", "autosave": True, "limit": 20},
    )
    assert add.status_code == 200
    assert "housing" in add.json()["markdown"]
    assert add.json()["saved"] is True

    schools = client.post(
        "/api/sites/demo.edu/approved-urls/chat",
        json={"message": "approve schools", "markdown": add.json()["markdown"], "autosave": True, "limit": 20},
    )
    assert schools.status_code == 200
    school_groups = {row["subpath"]: row["count"] for row in schools.json()["groups"]}
    assert school_groups["/cox"] == 2
    assert school_groups["/dedman"] == 1

    remove = client.post(
        "/api/sites/demo.edu/approved-urls/chat",
        json={"message": "remove academic-calendar", "markdown": schools.json()["markdown"], "autosave": True},
    )
    assert remove.status_code == 200
    assert "academic-calendar" not in remove.json()["markdown"]
    assert remove.json()["removed"] == [{"url": "https://demo.edu/enrollment-services/registrar/academic-calendar", "reason": "academic-calendar"}]

    analysis = client.post(
        "/api/sites/demo.edu/approved-urls/chat",
        json={"message": "how many urls could we select and show top groups", "markdown": remove.json()["markdown"], "autosave": True},
    )
    assert analysis.status_code == 200
    assert analysis.json()["saved"] is False
    assert analysis.json()["analysis"]["discovered_total"] == 7
    assert analysis.json()["analysis"]["eligible_total"] == 6
    assert analysis.json()["analysis"]["selected_total"] == 5
    assert "Could select 6 policy-eligible URLs" in analysis.json()["assistant_message"]

    committed = client.post(
        "/api/sites/demo.edu/approved-urls/commit",
        json={"markdown": remove.json()["markdown"], "remove_terms": ["dedman"]},
    )
    assert committed.status_code == 200
    available_after_commit = {row["subpath"]: row["count"] for row in committed.json()["available_groups"]}
    assert "/dedman" not in available_after_commit

    loaded = client.get("/api/sites/demo.edu/approved-urls")
    assert loaded.status_code == 200
    assert loaded.json()["urls"] == [
        "https://demo.edu/cox/academics/mba",
        "https://demo.edu/cox/admission/apply",
        "https://demo.edu/dedman/academics",
        "https://demo.edu/enrollment-services/registrar/transcripts",
        "https://demo.edu/student-life/housing",
    ]
    assert (site_root / "approved_urls_chat.jsonl").exists()


def test_choose_dedman_analysis_uses_school_path_not_title_lexicon(client: TestClient, tmp_path: Path) -> None:
    site_root = tmp_path / "data" / "sites" / "demo.edu"
    write_json(
        site_root / "discovered_urls.json",
        [
            {"url": "https://demo.edu/dedman/academics", "title": "Dedman Academics"},
            {"url": "https://demo.edu/news/2021/01/01/dedman-professor-feature", "title": "Dedman Professor Feature"},
            {"url": "https://demo.edu/cox/academics/mba", "title": "MBA"},
            {"url": "https://demo.edu/giving/ways-to-give", "title": "Giving"},
            {"url": "https://demo.edu/human-resources/benefits", "title": "Benefits"},
        ],
    )

    response = client.post(
        "/api/sites/demo.edu/approved-urls/chat",
        json={"message": "how many urls could we select for Choose Dedman", "autosave": False},
    )

    assert response.status_code == 200
    assert response.json()["intent"] == "analyze"
    analysis = response.json()["analysis"]
    assert analysis["matched_eligible_total"] == 1
    assert analysis["matched_groups"] == [{"subpath": "/dedman", "count": 1, "examples": ["https://demo.edu/dedman/academics"]}]
    assert analysis["matched_school_roots"] == ["dedman"]
    assert any(item["reason"] == "donor_advancement_or_alumni" for item in analysis["reject_reasons"])
    assert any(item["reason"] == "hr_or_employee" for item in analysis["reject_reasons"])
    assert "Top rejection reasons:" in response.json()["assistant_message"]


def test_choose_dedman_analysis_prefers_scoped_rejected_samples(client: TestClient, tmp_path: Path) -> None:
    site_root = tmp_path / "data" / "sites" / "demo.edu"
    write_json(
        site_root / "discovered_urls.json",
        [
            {"url": "https://demo.edu/giving/ways-to-give", "title": "Giving"},
            {"url": "https://demo.edu/human-resources/benefits", "title": "Benefits"},
            {"url": "https://demo.edu/dedman/academics", "title": "Dedman Academics"},
            {"url": "https://demo.edu/dedman/news/archive", "title": "Dedman News Archive"},
            {"url": "https://demo.edu/dedman/faculty/profiles/jane-doe", "title": "Faculty Profile"},
        ],
    )

    response = client.post(
        "/api/sites/demo.edu/approved-urls/chat",
        json={"message": "how many urls could we select for Choose Dedman", "autosave": False},
    )

    assert response.status_code == 200
    payload = response.json()
    samples = payload["analysis"]["rejected_samples"]
    assert samples == [
        {"url": "https://demo.edu/dedman/news/archive", "reason": "generic_news_archive"},
        {"url": "https://demo.edu/dedman/faculty/profiles/jane-doe", "reason": "staff_faculty_bio"},
    ]
    assert "Sample rejected noisy URLs:" in payload["assistant_message"]
    assert "https://demo.edu/dedman/news/archive (generic_news_archive)" in payload["assistant_message"]


def test_commit_filters_noisy_urls_and_reports_rejections(client: TestClient, tmp_path: Path) -> None:
    site_root = tmp_path / "data" / "sites" / "demo.edu"
    markdown = """# Approved URLs

<!-- scrape-planner:approved-urls:v1 -->

- [x] https://demo.edu/enrollment-services/registrar/transcripts
- [x] https://demo.edu/human-resources/benefits
- [x] https://demo.edu/news/archive
"""

    response = client.post(
        "/api/sites/demo.edu/approved-urls/commit",
        json={"markdown": markdown, "remove_terms": []},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["urls"] == ["https://demo.edu/enrollment-services/registrar/transcripts"]
    assert payload["filtered_rejected_urls"] == [
        {"url": "https://demo.edu/human-resources/benefits", "reason": "hr_or_employee"},
        {"url": "https://demo.edu/news/archive", "reason": "generic_news_archive"},
    ]
    saved = (site_root / "approved_urls.md").read_text(encoding="utf-8")
    assert "https://demo.edu/enrollment-services/registrar/transcripts" in saved
    assert "https://demo.edu/human-resources/benefits" not in saved
    assert "https://demo.edu/news/archive" not in saved


def test_put_approved_urls_filters_noisy_urls_and_normalizes_markdown(client: TestClient, tmp_path: Path) -> None:
    site_root = tmp_path / "data" / "sites" / "demo.edu"
    markdown = """# Approved URLs

<!-- scrape-planner:approved-urls:v1 -->

Keep this prose https://demo.edu/enrollment-services/registrar/transcripts
- [ ] https://demo.edu/student-life/housing
- [x] https://demo.edu/aboutsmu/office-of-the-president/messages
- [x] https://demo.edu/development/ways-to-give
"""

    response = client.put("/api/sites/demo.edu/approved-urls", json={"markdown": markdown})

    assert response.status_code == 200
    payload = response.json()
    assert payload["urls"] == [
        "https://demo.edu/enrollment-services/registrar/transcripts",
        "https://demo.edu/student-life/housing",
    ]
    assert payload["filtered_rejected_urls"] == [
        {"url": "https://demo.edu/aboutsmu/office-of-the-president/messages", "reason": "governance_or_admin"},
        {"url": "https://demo.edu/development/ways-to-give", "reason": "donor_advancement_or_alumni"},
    ]
    assert payload["markdown"] == (
        "# Approved URLs\n\n"
        "<!-- scrape-planner:approved-urls:v1 -->\n\n"
        "## Approved for next scrape\n\n"
        "- [x] https://demo.edu/enrollment-services/registrar/transcripts\n"
        "- [x] https://demo.edu/student-life/housing\n"
    )
    saved = (site_root / "approved_urls.md").read_text(encoding="utf-8")
    assert saved == payload["markdown"]
    assert "Keep this prose" not in saved
    assert "- [ ]" not in saved


DEFAULT_APPROVAL_BASE_PROMPT = (
    "Select a broad but high-signal set of URLs for a student-facing university knowledge base. "
    "Include admissions, registrar, academic calendar, tuition, financial aid, housing, dining, student life, "
    "schools and colleges, Cox, Dedman, Dedman Law, Law, Meadows, Lyle, Simmons, and Perkins. "
    "Exclude HR employee pages, donor/giving/alumni/event/news noise, and thin navigation."
)


def test_choose_top_100_with_base_prompt_ignores_school_lexicon_in_base_prompt(
    client: TestClient, tmp_path: Path
) -> None:
    site_root = tmp_path / "data" / "sites" / "demo.edu"
    discovered = [
        {"url": f"https://demo.edu/admissions/page-{index}", "title": f"Admissions {index}"}
        for index in range(60)
    ]
    discovered.extend(
        {"url": f"https://demo.edu/student-life/service-{index}", "title": f"Student Life {index}"}
        for index in range(60)
    )
    write_json(site_root / "discovered_urls.json", discovered)

    response = client.post(
        "/api/sites/demo.edu/approved-urls/chat",
        json={
            "message": "choose top 100 url",
            "base_prompt": DEFAULT_APPROVAL_BASE_PROMPT,
            "autosave": False,
            "limit": 30000,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "approve"
    assert len(payload["added"]) == 100
    assert payload["count"] == 100


def test_choose_dedman_approve_does_not_add_unrelated_lexical_matches(client: TestClient, tmp_path: Path) -> None:
    site_root = tmp_path / "data" / "sites" / "demo.edu"
    write_json(
        site_root / "discovered_urls.json",
        [
            {"url": "https://demo.edu/dedman/academics", "title": "Dedman Academics"},
            {"url": "https://demo.edu/dedmanlaw/academics", "title": "Dedman Law Academics"},
            {"url": "https://demo.edu/news/2021/01/01/dedman-professor-feature", "title": "Dedman Professor Feature"},
            {"url": "https://demo.edu/cox/academics/mba", "title": "MBA"},
        ],
    )

    response = client.post(
        "/api/sites/demo.edu/approved-urls/chat",
        json={"message": "choose dedman", "autosave": True, "limit": 20},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["urls"] == ["https://demo.edu/dedman/academics"]
    assert payload["added"] == [{"url": "https://demo.edu/dedman/academics", "reason": "subpath:/dedman"}]


@pytest.mark.parametrize("message", ["choose law", "choose dedman law", "choose dedmanlaw"])
def test_choose_law_phrases_scope_to_dedman_law_only(client: TestClient, tmp_path: Path, message: str) -> None:
    site_root = tmp_path / "data" / "sites" / "demo.edu"
    write_json(
        site_root / "discovered_urls.json",
        [
            {"url": "https://demo.edu/law/academics", "title": "Law Academics"},
            {"url": "https://demo.edu/law/admission/apply", "title": "Law Apply"},
            {"url": "https://demo.edu/dedmanlaw/academics", "title": "Dedman Law Academics"},
            {"url": "https://demo.edu/dedmanlaw/admission/apply", "title": "Dedman Law Apply"},
            {"url": "https://demo.edu/dedman/academics", "title": "Dedman College Academics"},
            {"url": "https://demo.edu/student-life/law-housing", "title": "Law Student Housing"},
            {"url": "https://demo.edu/news/2024/05/01/dedman-law-story", "title": "Dedman Law Story"},
        ],
    )

    response = client.post(
        "/api/sites/demo.edu/approved-urls/chat",
        json={"message": message, "autosave": True, "limit": 20},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["urls"] == [
        "https://demo.edu/dedmanlaw/academics",
        "https://demo.edu/dedmanlaw/admission/apply",
        "https://demo.edu/law/academics",
        "https://demo.edu/law/admission/apply",
    ]
    assert payload["groups"] == [
        {
            "subpath": "/dedmanlaw",
            "count": 2,
            "examples": [
                "https://demo.edu/dedmanlaw/academics",
                "https://demo.edu/dedmanlaw/admission/apply",
            ],
        },
        {
            "subpath": "/law",
            "count": 2,
            "examples": [
                "https://demo.edu/law/academics",
                "https://demo.edu/law/admission/apply",
            ],
        }
    ]
    assert payload["added"] == [
        {"url": "https://demo.edu/law/academics", "reason": "subpath:/law"},
        {"url": "https://demo.edu/law/admission/apply", "reason": "subpath:/law"},
        {"url": "https://demo.edu/dedmanlaw/academics", "reason": "subpath:/dedmanlaw"},
        {"url": "https://demo.edu/dedmanlaw/admission/apply", "reason": "subpath:/dedmanlaw"},
    ]
    assert "https://demo.edu/dedman/academics" not in payload["markdown"]
    assert "https://demo.edu/student-life/law-housing" not in payload["markdown"]
    assert "https://demo.edu/news/2024/05/01/dedman-law-story" not in payload["markdown"]


@pytest.mark.parametrize("message", ["choose law", "choose dedman law", "choose dedmanlaw"])
def test_law_analysis_scopes_to_law_roots_only(client: TestClient, tmp_path: Path, message: str) -> None:
    site_root = tmp_path / "data" / "sites" / "demo.edu"
    write_json(
        site_root / "discovered_urls.json",
        [
            {"url": "https://demo.edu/law/academics", "title": "Law Academics"},
            {"url": "https://demo.edu/law/admission/apply", "title": "Law Apply"},
            {"url": "https://demo.edu/dedmanlaw/academics", "title": "Dedman Law Academics"},
            {"url": "https://demo.edu/dedmanlaw/admission/apply", "title": "Dedman Law Apply"},
            {"url": "https://demo.edu/dedman/academics", "title": "Dedman College Academics"},
            {"url": "https://demo.edu/student-life/law-housing", "title": "Law Student Housing"},
            {"url": "https://demo.edu/news/2024/05/01/dedman-law-story", "title": "Dedman Law Story"},
        ],
    )

    response = client.post(
        "/api/sites/demo.edu/approved-urls/chat",
        json={"message": f"how many urls could we select for {message}", "autosave": False},
    )

    assert response.status_code == 200
    analysis = response.json()["analysis"]
    assert analysis["matched_school_roots"] == ["dedmanlaw", "law"]
    assert analysis["matched_eligible_total"] == 4
    assert analysis["matched_groups"] == [
        {
            "subpath": "/dedmanlaw",
            "count": 2,
            "examples": [
                "https://demo.edu/dedmanlaw/academics",
                "https://demo.edu/dedmanlaw/admission/apply",
            ],
        },
        {
            "subpath": "/law",
            "count": 2,
            "examples": [
                "https://demo.edu/law/academics",
                "https://demo.edu/law/admission/apply",
            ],
        },
    ]


def test_approved_url_chat_autosave_returns_filtered_payload(client: TestClient, tmp_path: Path) -> None:
    site_root = tmp_path / "data" / "sites" / "demo.edu"
    write_json(
        site_root / "discovered_urls.json",
        [{"url": "https://demo.edu/student-life/housing", "title": "Housing"}],
    )
    (site_root / "approved_urls.md").write_text(
        "# Approved URLs\n\n"
        "<!-- scrape-planner:approved-urls:v1 -->\n\n"
        "- [x] https://demo.edu/human-resources/benefits\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/sites/demo.edu/approved-urls/chat",
        json={"message": "approve path:/student-life/housing", "autosave": True, "limit": 20},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["urls"] == ["https://demo.edu/student-life/housing"]
    assert payload["count"] == 1
    assert "https://demo.edu/human-resources/benefits" not in payload["markdown"]
    assert payload["filtered_rejected_urls"] == [
        {"url": "https://demo.edu/human-resources/benefits", "reason": "hr_or_employee"}
    ]
    saved = (site_root / "approved_urls.md").read_text(encoding="utf-8")
    assert saved == payload["markdown"]
    assert "https://demo.edu/human-resources/benefits" not in saved
    assert "https://demo.edu/student-life/housing" in saved


def test_approved_url_area_addition_preserves_root_pages_and_pdf(client: TestClient, tmp_path: Path) -> None:
    site_root = tmp_path / "data" / "sites" / "demo.edu"
    write_json(
        site_root / "discovered_urls.json",
        [
            {"url": "https://demo.edu/", "title": "Home"},
            {"url": "https://demo.edu/pages/admissions.html", "title": "Admissions"},
            {"url": "https://demo.edu/pages/calendar.html", "title": "Calendar"},
            {"url": "https://demo.edu/pages/tuition.html", "title": "Tuition"},
            {"url": "https://demo.edu/docs/student-handbook.pdf", "title": "Student Handbook"},
        ],
    )

    response = client.post(
        "/api/sites/demo.edu/approved-urls/chat",
        json={
            "message": (
                "approve path:/ path:/pages/admissions.html path:/pages/calendar.html "
                "path:/pages/tuition.html path:/docs/student-handbook.pdf"
            ),
            "autosave": True,
            "limit": 20,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 5
    assert set(payload["urls"]) == {
        "https://demo.edu/",
        "https://demo.edu/docs/student-handbook.pdf",
        "https://demo.edu/pages/admissions.html",
        "https://demo.edu/pages/calendar.html",
        "https://demo.edu/pages/tuition.html",
    }
    markdown = (site_root / "approved_urls.md").read_text(encoding="utf-8")
    assert "https://demo.edu/" in markdown
    assert "https://demo.edu/docs/student-handbook.pdf" in markdown


def test_sse_event_helper() -> None:
    framed = sse_event("site", {"ok": True})
    assert framed.startswith("event: site\n")
    assert "data:" in framed
    assert framed.endswith("\n\n")


def test_tmux_session_exists_false_for_empty() -> None:
    assert tmux_session_exists("") is False


def test_document_preview_reads_site_relative_markdown(client: TestClient, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    site_root = data_root / "sites" / "demo.edu"
    markdown_path = site_root / "raw_sources" / "web" / "welcome.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("# Welcome\n\nRendered source.", encoding="utf-8")

    response = client.get("/api/sites/demo.edu/document-preview", params={"path": "raw_sources/web/welcome.md"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == "raw_sources/web/welcome.md"
    assert payload["content"].startswith("# Welcome")


def test_document_preview_rejects_path_escape(client: TestClient) -> None:
    response = client.get("/api/sites/demo.edu/document-preview", params={"path": "../secret.md"})

    assert response.status_code == 400


def test_document_upload_extracts_pdf_and_refreshes_registry(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.scrape_planner.pdf_contracts import PdfChunkRow, PdfSourceRow
    from src.scrape_planner.pdf.pdf_ingest import PdfIngestResult
    from src.scrape_planner.sources.raw_source_normalizer import NormalizationReport

    captured: dict[str, object] = {}

    def fake_ingest(paths: list[Path], config: object) -> PdfIngestResult:
        captured["paths"] = paths
        captured["page_markdown_dir"] = getattr(config, "page_markdown_dir", None)
        page_dir = Path(str(captured["page_markdown_dir"])) / "pdf123"
        page_dir.mkdir(parents=True)
        page_path = page_dir / "page-0001.md"
        page_path.write_text("Admissions document page.", encoding="utf-8")
        (page_dir / "pages.json").write_text(
            json.dumps(
                [
                    {
                        "pdf_source_id": "pdf123",
                        "source_path": str(paths[0]),
                        "page_number": 1,
                        "parser": "markitdown",
                        "markdown_path": str(page_path),
                        "char_count": 25,
                    }
                ]
            ),
            encoding="utf-8",
        )
        return PdfIngestResult(
            sources=[PdfSourceRow("pdf123", str(paths[0]), 21, 1, True, "now")],
            chunks=[PdfChunkRow("chunk123", "pdf123", 1, 0, "Admissions document page.", 25, "now")],
            quarantine=[],
        )

    def fake_normalize(site_root: Path) -> NormalizationReport:
        captured["normalized_site_root"] = site_root
        registry = site_root / "raw_sources" / "registry.jsonl"
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text(
            json.dumps(
                {
                    "source_id": "rawpdf123",
                    "source_kind": "pdf",
                    "status": "ready",
                    "title": "catalog.pdf p. 1",
                    "markdown_path": "raw_sources/pdf/rawpdf123.md",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return NormalizationReport(
            counts={"added": 1, "updated": 0, "unchanged": 0, "removed": 0},
            registry_path=str(registry),
            report_path=str(site_root / "raw_sources" / "reports" / "normalization-pdf-test.json"),
            sources=[],
        )

    monkeypatch.setattr("src.scrape_planner.webapp.api.ingest_pdfs", fake_ingest)
    monkeypatch.setattr("src.scrape_planner.webapp.api.normalize_pdf_pages", fake_normalize)

    response = client.post(
        "/api/sites/demo.edu/documents/upload",
        files=[("files", ("catalog.pdf", b"%PDF-1.7 fake content", "application/pdf"))],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["uploaded_count"] == 1
    assert payload["accepted_count"] == 1
    assert payload["chunk_count"] == 1
    assert payload["registry"]["counts"]["added"] == 1
    upload_path = tmp_path / "data" / "sites" / "demo.edu" / "sources" / "pdf_uploads" / "catalog.pdf"
    assert upload_path.exists()
    assert captured["paths"] == [upload_path]
    assert captured["page_markdown_dir"] == tmp_path / "data" / "sites" / "demo.edu" / "sources" / "pdf_pages"
    manifest = json.loads((tmp_path / "data" / "sites" / "demo.edu" / "sources" / "pdf_manifest.json").read_text(encoding="utf-8"))
    assert manifest == [{"path": str(upload_path), "filename": "catalog.pdf", "uploaded_at": payload["uploaded"][0]["uploaded_at"]}]
    ingest_dir = tmp_path / "data" / "sites" / "demo.edu" / "sources" / "pdf_ingest"
    assert "pdf123" in (ingest_dir / "pdf_sources.jsonl").read_text(encoding="utf-8")
    assert "chunk123" in (ingest_dir / "pdf_chunks.jsonl").read_text(encoding="utf-8")


def test_document_upload_route_is_exposed_in_openapi(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/sites/{site_id}/documents/upload" in response.json()["paths"]


def write_embedding_ready_site(data_root: Path, *, changed: int = 3, embedding_enabled: bool = True) -> Path:
    site_root = data_root / "sites" / "demo.edu"
    raw_sources = site_root / "raw_sources"
    wiki_dir = site_root / "wiki"
    indexes_dir = site_root / "indexes"
    (raw_sources / "reports").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "reports").mkdir(parents=True, exist_ok=True)
    (indexes_dir / "reports").mkdir(parents=True, exist_ok=True)
    (raw_sources / "registry.jsonl").write_text(
        json.dumps({"source_id": "src-1", "source_kind": "web", "status": "ready", "change_state": "changed"}) + "\n",
        encoding="utf-8",
    )
    write_json(wiki_dir / "build_report.json", {"status": "complete", "pages_created": 1, "integrated_sources": 1})
    write_json(
        indexes_dir / "reports" / "embedding-20260528T120000Z.json",
        {
            "status": "ready",
            "index_health": "stale" if changed else "ready",
            "raw_index_count": 5,
            "wiki_index_count": 2,
            "changed_raw_count": changed,
            "changed_wiki_count": 0,
            "reranker_ready": True,
        },
    )
    write_json(data_root / "app_state.json", {"embedding_enabled": embedding_enabled})
    write_json(
        indexes_dir / "llm_wiki_manifest.json",
        {
            "status": "ready",
            "version": "llm-wiki-hybrid-v2",
            "wiki_index_count": 2,
            "raw_index_count": 5,
            "vector_store": {"ready": True, "backend": "zvec", "documents": 7},
        },
    )
    (indexes_dir / "llm_wiki_documents.jsonl").write_text("{}\n", encoding="utf-8")
    (indexes_dir / "llm_wiki_postings.json").write_text("{}", encoding="utf-8")
    return site_root


def test_overview_auto_queues_embedding_rebuild_for_changed_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    site_root = write_embedding_ready_site(data_root, changed=4, embedding_enabled=True)
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))

    response = TestClient(create_app()).get("/api/sites/demo.edu/overview")

    assert response.status_code == 200
    embeddings = response.json()["embeddings"]
    assert embeddings["changed_document_count"] == 4
    assert embeddings["auto_rebuild_enabled"] is True
    assert embeddings["job_state"]["status"] == "queued"
    assert embeddings["job_state"]["trigger"] == "auto"
    assert (site_root / "indexes" / "embedding-job-latest.json").exists()


def test_overview_does_not_auto_queue_when_embeddings_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    site_root = write_embedding_ready_site(data_root, changed=4, embedding_enabled=False)
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))

    response = TestClient(create_app()).get("/api/sites/demo.edu/overview")

    assert response.status_code == 200
    embeddings = response.json()["embeddings"]
    assert embeddings["auto_rebuild_enabled"] is False
    assert embeddings["auto_rebuild_reason"] == "embedding_disabled"
    assert embeddings["job_state"]["status"] == "idle"
    assert not (site_root / "indexes" / "embedding-job-latest.json").exists()


def test_embedding_rebuild_blocked_without_prerequisites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    site_root = data_root / "sites" / "demo.edu"
    (site_root / "raw_sources").mkdir(parents=True)
    (site_root / "raw_sources" / "registry.jsonl").write_text("", encoding="utf-8")
    write_json(data_root / "app_state.json", {"embedding_enabled": True})
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))

    response = TestClient(create_app()).post("/api/sites/demo.edu/embeddings/rebuild")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["reason"] == "prerequisites_unhealthy"
    assert payload["job_state"]["status"] != "running"


def test_embedding_rebuild_endpoint_coalesces_running_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    site_root = write_embedding_ready_site(data_root, changed=2, embedding_enabled=True)
    write_json(
        site_root / "indexes" / "embedding-job-latest.json",
        {"site_id": "demo.edu", "status": "running", "trigger": "auto", "started_at": "2026-05-28T12:00:00+00:00"},
    )
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))

    response = TestClient(create_app()).post("/api/sites/demo.edu/embeddings/rebuild")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "already_running"
    assert payload["job_state"]["status"] == "running"
    assert payload["job_state"]["trigger"] == "manual"


def test_embedding_rebuild_endpoint_can_skip_when_no_documents_changed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    site_root = write_embedding_ready_site(data_root, changed=0, embedding_enabled=True)
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))

    response = TestClient(create_app()).post("/api/sites/demo.edu/embeddings/rebuild?force=false")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "skipped"
    assert payload["job_state"]["changed_document_count"] == 0
    assert payload["job_state"]["report_path"].endswith(".json")
    report = json.loads(Path(payload["job_state"]["report_path"]).read_text(encoding="utf-8"))
    assert "no changed documents" in report["message"]
    assert not (site_root / "indexes" / ".embedding-job.lock").exists()


def test_embedding_job_failure_state_keeps_report_and_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    site_root = write_embedding_ready_site(data_root, changed=1, embedding_enabled=True)

    def fail_build(site_root: Path) -> dict:
        raise RuntimeError(f"boom for {site_root.name}")

    run_embedding_job(site_root, "demo.edu", trigger="manual", build_index=fail_build)

    state = json.loads((site_root / "indexes" / "embedding-job-latest.json").read_text(encoding="utf-8"))
    assert state["status"] == "failed"
    assert state["last_error"] == "boom for demo.edu"
    assert Path(state["report_path"]).exists()
    assert Path(state["log_path"]).exists()


class FakeMcpRunner:
    def __init__(self, *, exists: bool = False, ok: bool = True, kill_ok: bool = True) -> None:
        self.exists = exists
        self.ok = ok
        self.kill_ok = kill_ok
        self.started: list[tuple[str, str, str]] = []
        self.killed: list[str] = []

    def available(self) -> bool:
        return True

    def session_exists(self, name: str) -> bool:
        return self.exists

    def start(self, name: str, command: str, workdir: str) -> dict:
        self.started.append((name, command, workdir))
        if not self.ok:
            return {"ok": False, "error": "tmux refused"}
        self.exists = True
        return {"ok": True, "command": command}

    def kill(self, name: str) -> dict:
        self.killed.append(name)
        if not self.kill_ok:
            return {"ok": False, "error": "kill refused"}
        self.exists = False
        return {"ok": True}


def test_mcp_start_endpoint_starts_global_gateway_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    write_embedding_ready_site(data_root, changed=0, embedding_enabled=True)
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))
    fake_runner = FakeMcpRunner()
    monkeypatch.setattr("src.scrape_planner.webapp.api.mcp_runner", lambda: fake_runner)

    response = TestClient(create_app()).post("/api/mcp/start")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "started"
    assert payload["mcp"]["running"] is True
    assert payload["mcp"]["session_name"] == "llm-wiki-mcp-global"
    assert payload["ready_count"] == 1
    assert "mcp_servers.llm_wiki_mcp" in fake_runner.started[0][1]
    assert "--data-root" in fake_runner.started[0][1]
    assert str(data_root) in fake_runner.started[0][1]
    assert (data_root / "runtime" / "mcp-server-latest.json").exists()


def test_mcp_start_endpoint_reuses_existing_global_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    write_embedding_ready_site(data_root, changed=0, embedding_enabled=True)
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))
    fake_runner = FakeMcpRunner(exists=True)
    monkeypatch.setattr("src.scrape_planner.webapp.api.mcp_runner", lambda: fake_runner)

    response = TestClient(create_app()).post("/api/mcp/start")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "already_running"
    assert payload["mcp"]["running"] is True
    assert fake_runner.started == []


def test_mcp_stop_endpoint_kills_global_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    write_embedding_ready_site(data_root, changed=0, embedding_enabled=True)
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))
    fake_runner = FakeMcpRunner(exists=True)
    monkeypatch.setattr("src.scrape_planner.webapp.api.mcp_runner", lambda: fake_runner)

    response = TestClient(create_app()).post("/api/mcp/stop")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "stopped"
    assert payload["mcp"]["running"] is False
    assert fake_runner.killed == ["llm-wiki-mcp-global"]
    assert fake_runner.exists is False


def test_mcp_stop_endpoint_when_not_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    write_embedding_ready_site(data_root, changed=0, embedding_enabled=True)
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))
    fake_runner = FakeMcpRunner(exists=False)
    monkeypatch.setattr("src.scrape_planner.webapp.api.mcp_runner", lambda: fake_runner)

    response = TestClient(create_app()).post("/api/mcp/stop")

    assert response.status_code == 200
    assert response.json()["status"] == "not_running"


def write_agent_metrics(data_root: Path) -> None:
    repo = AgentRunMetricsRepository(data_root)
    repo.append_event(
        build_llm_metric_event(
            run_id="agent-run-1",
            site_id="demo.edu",
            timestamp="2026-05-20T12:00:00Z",
            stage="wiki",
            operation="draft_page",
            provider="openrouter",
            model="model-a",
            prompt_tokens=100,
            completion_tokens=25,
            cost_usd=0.03,
            cost_source="estimated",
        )
    )
    repo.append_event(
        build_embedding_metric_event(
            run_id="agent-run-1",
            site_id="demo.edu",
            timestamp="2026-05-20T12:05:00Z",
            stage="embed",
            operation="build_llm_wiki_index",
            provider="deterministic",
            model="hash-v1",
            input_tokens=200,
            document_count=4,
            chunk_count=12,
            vector_count=12,
            cost_usd=None,
            cost_source="unknown",
        )
    )
    repo.rebuild_run_summary("demo.edu", "agent-run-1", status="completed")


def test_metrics_runs_endpoint_returns_agent_summaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    write_embedding_ready_site(data_root, changed=0, embedding_enabled=True)
    write_agent_metrics(data_root)
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))

    response = TestClient(create_app()).get("/api/sites/demo.edu/metrics/runs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["runs"][0]["run_id"] == "agent-run-1"
    assert payload["runs"][0]["llm_usage"]["total_tokens"] == 125
    assert payload["runs"][0]["embedding_usage"]["input_tokens"] == 200
    assert payload["runs"][0]["cost"]["source"] == "partial"


def test_metrics_run_endpoint_returns_one_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    write_embedding_ready_site(data_root, changed=0, embedding_enabled=True)
    write_agent_metrics(data_root)
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))

    response = TestClient(create_app()).get("/api/sites/demo.edu/metrics/runs/agent-run-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["run_id"] == "agent-run-1"
    assert payload["run"]["llm_usage"]["request_count"] == 1
    assert payload["run"]["embedding_usage"]["vector_count"] == 12


def test_metrics_rollups_endpoint_supports_windows_and_as_of(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    write_embedding_ready_site(data_root, changed=0, embedding_enabled=True)
    write_agent_metrics(data_root)
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))

    response = TestClient(create_app()).get(
        "/api/sites/demo.edu/metrics/rollups",
        params={"windows": "30d,60d,90d,365d", "as_of": "2026-05-29T00:00:00Z", "include_all_time": "true"},
    )

    assert response.status_code == 200
    rollups = response.json()["rollups"]
    assert {"30d", "60d", "90d", "365d", "all_time"}.issubset(rollups)
    assert rollups["30d"]["total_tokens"] == 325
    assert rollups["30d"]["llm_tokens"] == 125
    assert rollups["30d"]["embedding_tokens"] == 200
    assert rollups["30d"]["embedding_cost"] == {"amount_usd": None, "source": "unknown"}


def test_start_scrape_uses_approved_urls(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    site_root = tmp_path / "data" / "sites" / "demo.edu"
    site_root.mkdir(parents=True, exist_ok=True)
    write_json(
        site_root / "discovered_urls.json",
        [
            {"url": "https://demo.edu/giving/donate", "source_sitemap": "sitemap", "selected": True},
            {"url": "https://demo.edu/admission/apply", "source_sitemap": "sitemap", "selected": True},
        ],
    )
    (site_root / "approved_urls.md").write_text(
        "# Approved URLs\n\n- [x] https://demo.edu/admission/apply\n",
        encoding="utf-8",
    )

    started: dict[str, object] = {}

    class _Runner:
        def start(self, site_id, run_id, urls, concurrency=4, browser_mode=None, lightpanda_cdp_url=None):
            started["site_id"] = site_id
            started["run_id"] = run_id
            started["urls"] = urls

    monkeypatch.setattr("src.scrape_planner.webapp.api.scrape_runner", lambda: _Runner())

    response = client.post("/api/sites/demo.edu/scrape", json={"concurrency": 2, "prefer_approved": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["url_count"] == 1
    assert started["urls"][0].url == "https://demo.edu/admission/apply"


def test_confidence_gaps_endpoint(client: TestClient, tmp_path: Path) -> None:
    site_root = tmp_path / "data" / "sites" / "demo.edu"
    indexes = site_root / "indexes"
    indexes.mkdir(parents=True, exist_ok=True)
    (indexes / "self_improving_gaps.jsonl").write_text(
        json.dumps({"question": "fall 2026 schedule", "recommended_action": "re_discovery_and_rebuild"}) + "\n",
        encoding="utf-8",
    )

    response = client.get("/api/sites/demo.edu/self-improving/gaps")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["gaps"][0]["question"] == "fall 2026 schedule"


def test_operator_skills_catalog(client: TestClient) -> None:
    response = client.get("/api/operator/skills")
    assert response.status_code == 200
    skills = {item["id"] for item in response.json()["skills"]}
    assert {"site-discovery", "site-url-curation", "llm-wiki-noninteractive"}.issubset(skills)


def test_start_site_job_launches_tmux(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_launch(site_root, skill_id, **kwargs):
        captured["skill"] = skill_id
        captured["site_root"] = site_root
        return {
            "ok": True,
            "session_name": "discover-demo.edu-test",
            "report_path": str(site_root / "jobs" / "reports" / "site-discovery-latest.json"),
            "builder_command": "bash discover_site.sh",
        }

    monkeypatch.setattr("src.scrape_planner.webapp.jobs.launch_operator_job", fake_launch)

    response = client.post(
        "/api/sites/demo.edu/jobs",
        json={"skill": "site-discovery", "prompt": "discover registrar URLs"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["skill"] == "site-discovery"
    assert payload["session_name"] == "discover-demo.edu-test"
    assert captured["skill"] == "site-discovery"


def test_start_site_job_unknown_skill(client: TestClient) -> None:
    response = client.post("/api/sites/demo.edu/jobs", json={"skill": "not-a-skill"})
    assert response.status_code == 400


def test_site_job_status(client: TestClient, tmp_path: Path) -> None:
    report_dir = tmp_path / "data" / "sites" / "demo.edu" / "jobs" / "reports"
    report_dir.mkdir(parents=True)
    (report_dir / "site-discovery-latest.json").write_text(
        json.dumps({"status": "completed", "tmux_session": "discover-demo-old"}),
        encoding="utf-8",
    )
    response = client.get("/api/sites/demo.edu/jobs/site-discovery")
    assert response.status_code == 200
    payload = response.json()
    assert payload["skill"] == "site-discovery"
    assert payload["report"]["status"] == "completed"


def test_mcp_universities_excludes_non_query_ready_indexes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    sites = data_root / "sites"
    v1_site = sites / "127.0.0.1:8765"
    v2_site = sites / "127.0.0.1:8766"
    for site_root in (v1_site, v2_site):
        (site_root / "wiki" / "pages").mkdir(parents=True)
        (site_root / "wiki" / "pages" / "index.md").write_text("# Wiki\n", encoding="utf-8")
        (site_root / "indexes").mkdir(parents=True)
    write_json(
        v1_site / "indexes" / "llm_wiki_manifest.json",
        {
            "status": "ready",
            "version": "llm-wiki-hybrid-v1",
            "wiki_index_count": 3,
            "raw_index_count": 3,
        },
    )
    write_json(
        v2_site / "indexes" / "llm_wiki_manifest.json",
        {
            "status": "ready",
            "version": "llm-wiki-hybrid-v2",
            "wiki_index_count": 3,
            "raw_index_count": 3,
            "vector_store": {"ready": True, "backend": "zvec", "documents": 3},
        },
    )
    (v2_site / "indexes" / "llm_wiki_documents.jsonl").write_text("{}\n", encoding="utf-8")
    (v2_site / "indexes" / "llm_wiki_postings.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))

    response = TestClient(create_app()).get("/api/mcp/universities")

    assert response.status_code == 200
    payload = response.json()
    rows = {row["site_id"]: row for row in payload["universities"]}
    assert payload["ready_count"] == 1
    assert rows["127.0.0.1:8765"]["mcp_enabled"] is False
    assert rows["127.0.0.1:8765"]["mcp_block_reason"]
    assert "version" in rows["127.0.0.1:8765"]["mcp_block_reason"].lower()
    assert rows["127.0.0.1:8766"]["mcp_enabled"] is True


def test_wiki_job_status_marks_stale_pi_model_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.scrape_planner.app.job_launcher import job_status_payload

    site_root = tmp_path / "sites" / "demo.edu"
    reports = site_root / "wiki" / "reports"
    reports.mkdir(parents=True)
    events_path = reports / "wiki-build.events.jsonl"
    events_path.write_text(
        json.dumps({"type": "stderr", "message": 'Warning: No models match pattern "github-copilot/gpt-4o"'}) + "\n",
        encoding="utf-8",
    )
    write_json(
        reports / "wiki-build-latest.json",
        {
            "status": "running",
            "job_status": "running",
            "tmux_session": "wiki-demo-old",
            "pi_events_path": str(events_path),
        },
    )
    monkeypatch.setattr("src.scrape_planner.wiki.wiki_launcher.tmux_session_alive", lambda *args, **kwargs: False)

    payload = job_status_payload(site_root, "llm-wiki-noninteractive")

    assert payload["report"]["job_status"] == "failed"
    assert "no models match pattern" in str(payload["report"]["last_error"]).lower()


def test_wiki_job_status_marks_silent_live_pi_job_stalled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.scrape_planner.app.job_launcher import job_status_payload

    site_root = tmp_path / "sites" / "demo.edu"
    reports = site_root / "wiki" / "reports"
    reports.mkdir(parents=True)
    events_path = reports / "wiki-build.events.jsonl"
    events_path.write_text(json.dumps({"type": "session", "id": "demo"}) + "\n", encoding="utf-8")
    old_mtime = time.time() - 600
    os.utime(events_path, (old_mtime, old_mtime))
    write_json(
        reports / "wiki-build-latest.json",
        {
            "status": "running",
            "job_status": "running",
            "tmux_session": "wiki-demo-live",
            "pi_events_path": str(events_path),
        },
    )

    class AliveTmux:
        def available(self) -> bool:
            return True

        def session_exists(self, session: str) -> bool:
            return session == "wiki-demo-live"

    monkeypatch.setattr("src.scrape_planner.app.job_launcher.TmuxRunner", lambda: AliveTmux())
    monkeypatch.setattr("src.scrape_planner.wiki.wiki_launcher.tmux_session_alive", lambda *args, **kwargs: True)

    payload = job_status_payload(site_root, "llm-wiki-noninteractive")

    assert payload["report"]["job_status"] == "stalled"
    assert payload["report"]["reported_job_status"] == "running"
    assert payload["report"]["stalled_running"] is True
    assert payload["report"]["tmux_session_alive"] is True
    assert payload["report"]["last_event_age_seconds"] >= 300
    assert "has not emitted build output" in payload["report"]["last_error"]
