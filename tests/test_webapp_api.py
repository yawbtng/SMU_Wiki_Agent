from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.scrape_planner.storage import write_json
from src.scrape_planner.agent_run_metrics import AgentRunMetricsRepository, build_embedding_metric_event, build_llm_metric_event
from src.scrape_planner.webapp.api import create_app, run_embedding_job, start_mcp_server_for_site, sse_event, tmux_session_exists


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


def test_list_sites(client: TestClient) -> None:
    response = client.get("/api/sites")
    assert response.status_code == 200
    payload = response.json()
    assert payload["sites"][0]["id"] == "demo.edu"
    assert payload["sites"][0]["has_wiki"] is True


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

    async def one_shot_stream(site_id: str, interval: float):
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
    from src.scrape_planner.models import DiscoveredURL
    from src.scrape_planner.sitemap_discovery import DiscoveryResult

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
    def fake_llm(message: str, base_prompt: str, analysis: dict) -> dict:
        if "remove" in message:
            return {"provider": "test", "status": "success", "intent": "remove", "terms": ["academic-calendar"], "response": ""}
        if "registrar" in message:
            return {"provider": "test", "status": "success", "intent": "approve", "terms": ["registrar", "calendar"], "response": ""}
        if "approve" in message or "housing" in message:
            terms = ["schools"] if "schools" in message else ["housing"]
            return {"provider": "test", "status": "success", "intent": "approve", "terms": terms, "response": ""}
        return {"provider": "test", "status": "success", "intent": "analyze", "terms": [], "response": ""}

    monkeypatch.setattr("src.scrape_planner.webapp.api._llm_decide_url_chat", fake_llm)

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
    def __init__(self, *, exists: bool = False, ok: bool = True) -> None:
        self.exists = exists
        self.ok = ok
        self.started: list[tuple[str, str, str]] = []

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


def test_mcp_start_endpoint_starts_site_scoped_server_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    site_root = write_embedding_ready_site(data_root, changed=0, embedding_enabled=True)
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))
    fake_runner = FakeMcpRunner()
    monkeypatch.setattr("src.scrape_planner.webapp.api.mcp_runner", lambda: fake_runner)

    response = TestClient(create_app()).post("/api/sites/demo.edu/mcp/start")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "started"
    assert payload["mcp"]["running"] is True
    assert payload["mcp"]["session_name"] == "llm-wiki-mcp-demo-edu"
    assert "mcp_servers.llm_wiki_mcp" in fake_runner.started[0][1]
    assert str(site_root) in fake_runner.started[0][1]
    assert (site_root / "indexes" / "mcp-server-latest.json").exists()


def test_mcp_start_endpoint_reuses_existing_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = tmp_path / "data"
    write_embedding_ready_site(data_root, changed=0, embedding_enabled=True)
    monkeypatch.setenv("SCRAPE_PLANNER_DATA_ROOT", str(data_root))
    fake_runner = FakeMcpRunner(exists=True)
    monkeypatch.setattr("src.scrape_planner.webapp.api.mcp_runner", lambda: fake_runner)

    response = TestClient(create_app()).post("/api/sites/demo.edu/mcp/start")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "already_running"
    assert payload["mcp"]["running"] is True
    assert fake_runner.started == []


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
