from pathlib import Path

from src.scrape_planner.runtime.run_persistence import write_run_status
from src.scrape_planner.core.site_layout import site_layout
from src.scrape_planner.runtime.state import RunStateStore
from src.scrape_planner.wiki.stepper_status import (
    load_embedding_status,
    load_mcp_status,
    load_wiki_status,
    raw_source_status,
)
from src.scrape_planner.core.storage import write_json
from src.scrape_planner.sources.source_registry import build_source_row, read_registry_rows, write_registry_rows


def test_port_zero_redis_url_disables_redis_client() -> None:
    store = RunStateStore(redis_url="redis://127.0.0.1:0/0")

    assert store._client is None


def test_app_state_repository_loads_defaults_and_preserves_existing_keys(tmp_path: Path) -> None:
    from src.scrape_planner.app.repositories import AppStateRepository

    path = tmp_path / "app_state.json"
    path.write_text('{"last_site_id":"www.smu.edu","custom_flag":true}', encoding="utf-8")

    repo = AppStateRepository(path)
    loaded = repo.load()

    assert loaded["active_workspace_id"] == ""
    assert loaded["workspaces"] == []
    assert loaded["last_site_id"] == "www.smu.edu"
    assert loaded["custom_flag"] is True
    assert path.read_text(encoding="utf-8") == '{"last_site_id":"www.smu.edu","custom_flag":true}'


def test_app_state_repository_normalizes_malformed_top_level_shapes(tmp_path: Path) -> None:
    from src.scrape_planner.app.repositories import AppStateRepository

    path = tmp_path / "app_state.json"
    path.write_text(
        '{"active_workspace_id":["bad"],"workspaces":{"bad":1},"last_run_by_site":[],"site_history":[1,"ok"]}',
        encoding="utf-8",
    )

    loaded = AppStateRepository(path).load()

    assert loaded["active_workspace_id"] == ""
    assert loaded["workspaces"] == []
    assert loaded["last_run_by_site"] == {}
    assert loaded["site_history"] == ["ok"]


def test_app_state_repository_normalizes_wiki_tmux_settings(tmp_path: Path) -> None:
    from src.scrape_planner.app.repositories import AppStateRepository

    path = tmp_path / "app_state.json"
    path.write_text(
        '{"tmux_session_grace_seconds":"900","wiki_builder_runtime":"deterministic","wiki_skip_pi":"on",'
        '"tmux_archive_sessions":"off","tmux_reconcile_expired_sessions":0,"pi_cmd":"  /opt/pi  "}',
        encoding="utf-8",
    )

    loaded = AppStateRepository(path).load()

    assert loaded["tmux_session_grace_seconds"] == 900
    assert loaded["wiki_builder_runtime"] == "python"
    assert loaded["wiki_skip_pi"] is True
    assert loaded["tmux_archive_sessions"] is False
    assert loaded["tmux_reconcile_expired_sessions"] is False
    assert loaded["pi_cmd"] == "/opt/pi"


def test_site_artifact_repository_loads_discovered_rows_without_rewriting_file(tmp_path: Path) -> None:
    from src.scrape_planner.app.repositories import SiteArtifactRepository

    path = tmp_path / "sites" / "www.smu.edu" / "discovered_urls.json"
    path.parent.mkdir(parents=True)
    payload = (
        '[{"url":"https://www.smu.edu/academics","source_sitemap":"https://www.smu.edu/sitemap.xml",'
        '"selected":true,"extra_note":"keep"}]'
    )
    path.write_text(payload, encoding="utf-8")

    repo = SiteArtifactRepository(tmp_path)
    rows = repo.load_discovered_rows("www.smu.edu")

    assert rows == [
        {
            "url": "https://www.smu.edu/academics",
            "source_sitemap": "https://www.smu.edu/sitemap.xml",
            "selected": True,
            "extra_note": "keep",
        }
    ]
    assert path.read_text(encoding="utf-8") == payload


def test_site_artifact_repository_normalizes_discovered_rows_conservatively(tmp_path: Path) -> None:
    from src.scrape_planner.app.repositories import SiteArtifactRepository

    path = tmp_path / "sites" / "www.smu.edu" / "discovered_urls.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        '[1,{"url":["bad"],"source_sitemap":9,"selected":"","extra_note":"keep"},{"url":"https://www.smu.edu/about","selected":false}]',
        encoding="utf-8",
    )

    rows = SiteArtifactRepository(tmp_path).load_discovered_rows("www.smu.edu")

    assert rows == [
        {"url": "", "source_sitemap": "9", "selected": False, "extra_note": "keep"},
        {"url": "https://www.smu.edu/about", "selected": False},
    ]


def test_site_artifact_repository_normalizes_legacy_selected_flags_safely(tmp_path: Path) -> None:
    from src.scrape_planner.app.repositories import SiteArtifactRepository

    repo = SiteArtifactRepository(tmp_path)
    discovered_path = tmp_path / "sites" / "www.smu.edu" / "discovered_urls.json"
    discovered_path.parent.mkdir(parents=True)
    discovered_path.write_text(
        (
            '[{"url":"https://www.smu.edu/false-a","selected":"false"},'
            '{"url":"https://www.smu.edu/false-b","selected":"0"},'
            '{"url":"https://www.smu.edu/true-a","selected":"true"},'
            '{"url":"https://www.smu.edu/true-b","selected":"1"},'
            '{"url":"https://www.smu.edu/unknown","selected":"maybe"}]'
        ),
        encoding="utf-8",
    )
    write_json(
        tmp_path / "sites" / "www.smu.edu" / "20260522T120000Z-run" / "selected_urls.json",
        [
            {"url": "https://www.smu.edu/off", "selected": "off"},
            {"url": "https://www.smu.edu/on", "selected": "on"},
            {"url": "https://www.smu.edu/int0", "selected": 0},
            {"url": "https://www.smu.edu/int1", "selected": 1},
            {"url": "https://www.smu.edu/noise", "selected": " definitely "},
        ],
    )

    discovered_rows = repo.load_discovered_rows("www.smu.edu")
    selected_rows = repo.load_selected_url_rows("www.smu.edu", "20260522T120000Z-run")

    assert [row["selected"] for row in discovered_rows] == [False, False, True, True, False]
    assert [row["selected"] for row in selected_rows] == [False, True, False, True, False]


def test_site_artifact_repository_and_status_read_model_expose_existing_site_level_loaders(tmp_path: Path) -> None:
    from src.scrape_planner.app.repositories import SiteArtifactRepository, SiteStatusReadModel

    site_id = "www.smu.edu"
    run_id = "20260522T120000Z-run"
    artifact_repo = SiteArtifactRepository(tmp_path)
    status_model = SiteStatusReadModel(tmp_path)
    run_root = artifact_repo.site_root(site_id) / run_id
    layout = site_layout(artifact_repo.site_root(site_id))

    selected_urls_payload = [
        {"url": "https://www.smu.edu/academics", "selected": True, "score": 0.9},
    ]
    write_json(run_root / "selected_urls.json", selected_urls_payload)
    write_run_status(run_root, {"state": "completed", "done": 1, "extra": "keep"})

    registry_row = build_source_row(
        source_kind="web",
        title="Academics",
        original_url="https://www.smu.edu/academics",
        original_path="",
        markdown_path="raw_sources/web/academics.md",
        metadata_path="raw_sources/web/academics.metadata.json",
        checksum="abc123",
        parser="scrape_worker.markdown",
        status="ready",
        now="2026-05-22T12:00:00+00:00",
    )
    write_registry_rows(layout.registry_path, [registry_row])
    write_json(
        layout.wiki_dir / "build_report.json",
        {"status": "completed", "pages_created": 2, "integrated_sources": 1},
    )
    write_json(
        layout.indexes_dir / "zvec_index_manifest.json",
        {"raw_documents": 3, "wiki_documents": 2, "status": "ready"},
    )

    expected_raw_status = raw_source_status(layout)

    assert artifact_repo.load_selected_url_rows(site_id, run_id) == selected_urls_payload
    assert artifact_repo.load_run_status(site_id, run_id) == {"state": "completed", "done": 1, "extra": "keep"}
    assert artifact_repo.load_raw_source_rows(site_id) == read_registry_rows(layout.registry_path)
    assert status_model.load_raw_source_status(site_id) == expected_raw_status
    assert status_model.load_wiki_status(site_id) == load_wiki_status(layout, expected_raw_status)
    assert status_model.load_index_status(site_id) == load_embedding_status(layout)
    assert status_model.load_mcp_status(site_id) == load_mcp_status(layout)
