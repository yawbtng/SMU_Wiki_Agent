from __future__ import annotations

from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..runtime.agent_run_metrics import STANDARD_WINDOWS
from ..app.navigation import WORKFLOW_TABS
from . import api as payloads
from .approved_urls import approval_chat_payload, approved_urls_payload, commit_approved_urls_payload, write_approved_urls_payload
from .deps import app_state_path, data_root, site_root, state_repo, status_model, to_jsonable, utc_now
from .embeddings import (
    embedding_enabled,
    embedding_job_status_payload,
    embedding_prerequisites_ready,
    load_embedding_job_state,
    trigger_embedding_rebuild,
)
from .jobs import operator_skills_payload, site_job_status_payload, start_site_job_payload
from .tmux_sessions import archive_site_tmux_session_payload, list_site_tmux_sessions_payload
from .schemas import (
    AppStateUpdate,
    ApprovedUrlsChatRequest,
    ApprovedUrlsCommitRequest,
    ApprovedUrlsUpdate,
    DiscoverSiteRequest,
    SiteJobRequest,
    StartScrapeRequest,
)


def register_routes(app: FastAPI) -> None:
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "data_root": str(data_root()), "generated_at": utc_now()}

    @app.get("/api/navigation")
    def navigation() -> dict[str, Any]:
        return {"tabs": WORKFLOW_TABS}

    @app.get("/api/operator/skills")
    def operator_skills() -> dict[str, Any]:
        return to_jsonable(operator_skills_payload())

    @app.get("/api/app-state")
    def get_app_state() -> dict[str, Any]:
        return {"state": state_repo().load(), "path": str(app_state_path())}

    @app.put("/api/app-state")
    def put_app_state(update: AppStateUpdate) -> dict[str, Any]:
        repo = state_repo()
        current = dict(repo.load())
        current.update(update.payload)
        repo.save(current)
        return {"state": repo.load(), "path": str(app_state_path())}

    @app.post("/api/discover")
    def discover_site(request: DiscoverSiteRequest) -> dict[str, Any]:
        return to_jsonable(payloads.discover_site_payload(request.site_url, timeout=request.timeout))

    @app.get("/api/sites")
    def list_sites() -> dict[str, Any]:
        return to_jsonable(payloads.list_sites_payload())

    @app.get("/api/mcp/status")
    def global_mcp_status() -> dict[str, Any]:
        return to_jsonable(payloads.global_mcp_status_payload())

    @app.get("/api/mcp/universities")
    def global_mcp_universities() -> dict[str, Any]:
        return to_jsonable(payloads.list_mcp_universities_payload())

    @app.post("/api/mcp/start")
    def start_global_mcp() -> dict[str, Any]:
        return to_jsonable(payloads.start_global_mcp_server())

    @app.post("/api/mcp/stop")
    def stop_global_mcp() -> dict[str, Any]:
        return to_jsonable(payloads.stop_global_mcp_server())

    @app.post("/api/mcp/restart")
    def restart_global_mcp() -> dict[str, Any]:
        return to_jsonable(payloads.restart_global_mcp_server())

    @app.get("/api/sites/{site_id}/overview")
    def site_overview(site_id: str) -> dict[str, Any]:
        return to_jsonable(payloads.site_overview_payload(site_id))

    @app.post("/api/sites/{site_id}/mcp/start")
    def start_mcp_server(site_id: str) -> dict[str, Any]:
        root = site_root(site_id)
        if not root.exists():
            raise HTTPException(status_code=404, detail="site not found")
        mcp_status = status_model().load_mcp_status(site_id)
        return to_jsonable(payloads.start_mcp_server_for_site(root, site_id, mcp_status))

    @app.post("/api/sites/{site_id}/mcp/stop")
    def stop_mcp_server(site_id: str) -> dict[str, Any]:
        root = site_root(site_id)
        if not root.exists():
            raise HTTPException(status_code=404, detail="site not found")
        return to_jsonable(payloads.stop_mcp_server_for_site(root, site_id))

    @app.get("/api/sites/{site_id}/embeddings/job")
    def embedding_job_status(site_id: str) -> dict[str, Any]:
        root = site_root(site_id)
        if not root.exists():
            raise HTTPException(status_code=404, detail="site not found")
        return to_jsonable(embedding_job_status_payload(site_id, root))

    @app.post("/api/sites/{site_id}/embeddings/rebuild")
    def rebuild_embeddings(
        site_id: str,
        background_tasks: BackgroundTasks,
        force: bool = Query(True),
    ) -> dict[str, Any]:
        root = site_root(site_id)
        if not root.exists():
            raise HTTPException(status_code=404, detail="site not found")
        statuses = status_model()
        raw_status = statuses.load_raw_source_status(site_id)
        wiki_status = statuses.load_wiki_status(site_id)
        index_status = statuses.load_index_status(site_id)
        if not embedding_enabled():
            return {
                "status": "disabled",
                "reason": "embedding_disabled",
                "job_state": load_embedding_job_state(root, site_id),
            }
        if not embedding_prerequisites_ready(raw_status, wiki_status):
            return {
                "status": "blocked",
                "reason": "prerequisites_unhealthy",
                "job_state": load_embedding_job_state(root, site_id),
            }
        result = trigger_embedding_rebuild(
            site_id,
            root,
            trigger="manual",
            changed_document_count=int(index_status.get("changed_document_count") or 0),
            force=force,
            launch=True,
            background_tasks=background_tasks,
        )
        return to_jsonable(result)

    @app.get("/api/sites/{site_id}/sources")
    def site_sources(site_id: str, limit: int = Query(500, ge=1, le=5000), offset: int = Query(0, ge=0)) -> dict[str, Any]:
        return to_jsonable(payloads.sources_payload(site_id, limit=limit, offset=offset))

    @app.get("/api/sites/{site_id}/approved-urls")
    def get_approved_urls(site_id: str) -> dict[str, Any]:
        return to_jsonable(approved_urls_payload(site_id))

    @app.put("/api/sites/{site_id}/approved-urls")
    def put_approved_urls(site_id: str, update: ApprovedUrlsUpdate) -> dict[str, Any]:
        return to_jsonable(write_approved_urls_payload(site_id, update.markdown))

    @app.post("/api/sites/{site_id}/approved-urls/commit")
    def commit_approved_urls(site_id: str, request: ApprovedUrlsCommitRequest) -> dict[str, Any]:
        return to_jsonable(commit_approved_urls_payload(site_id, request))

    @app.post("/api/sites/{site_id}/approved-urls/chat")
    def chat_approved_urls(site_id: str, request: ApprovedUrlsChatRequest) -> dict[str, Any]:
        return to_jsonable(approval_chat_payload(site_id, request))

    @app.post("/api/sites/{site_id}/jobs")
    def start_site_job(site_id: str, request: SiteJobRequest) -> dict[str, Any]:
        return to_jsonable(
            start_site_job_payload(
                site_id,
                skill=request.skill,
                prompt=request.prompt,
                allow_concurrent=request.allow_concurrent,
                rebuild_wiki=request.rebuild_wiki,
                site_root_fn=site_root,
            )
        )

    @app.get("/api/sites/{site_id}/jobs/{skill}")
    def site_job_status(site_id: str, skill: str) -> dict[str, Any]:
        return to_jsonable(site_job_status_payload(site_id, skill, site_root_fn=site_root))

    @app.post("/api/sites/{site_id}/scrape")
    def start_site_scrape(site_id: str, request: StartScrapeRequest) -> dict[str, Any]:
        return to_jsonable(
            payloads.start_scrape_payload(
                site_id,
                concurrency=request.concurrency,
                prefer_approved=request.prefer_approved,
                browser_mode=request.browser_mode,
            )
        )

    @app.get("/api/sites/{site_id}/self-improving/gaps")
    def site_confidence_gaps(site_id: str, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
        return to_jsonable(payloads.confidence_gaps_payload(site_id, limit=limit))

    @app.get("/api/sites/{site_id}/runs")
    def site_runs(site_id: str) -> dict[str, Any]:
        return to_jsonable(payloads.list_runs_payload(site_id))

    @app.get("/api/sites/{site_id}/runs/{run_id}")
    def site_run(site_id: str, run_id: str, event_limit: int = Query(200, ge=1, le=5000)) -> dict[str, Any]:
        return to_jsonable(payloads.run_payload(site_id, run_id, event_limit=event_limit))

    @app.get("/api/sites/{site_id}/metrics/runs")
    def site_metrics_runs(site_id: str, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
        return to_jsonable(payloads.metrics_runs_payload(site_id, limit=limit))

    @app.get("/api/sites/{site_id}/metrics/runs/{run_id}")
    def site_metrics_run(site_id: str, run_id: str) -> dict[str, Any]:
        return to_jsonable(payloads.metrics_run_payload(site_id, run_id))

    @app.get("/api/sites/{site_id}/metrics/rollups")
    def site_metrics_rollups(
        site_id: str,
        windows: str = Query(",".join(STANDARD_WINDOWS)),
        as_of: str = "",
        include_all_time: bool = True,
    ) -> dict[str, Any]:
        return to_jsonable(payloads.metrics_rollups_payload(site_id, windows=windows, as_of=as_of or None, include_all_time=include_all_time))

    @app.get("/api/sites/{site_id}/wiki/agent")
    def wiki_agent(site_id: str) -> dict[str, Any]:
        return to_jsonable(payloads.wiki_agent_payload(site_id))

    @app.get("/api/sites/{site_id}/wiki/generation")
    def wiki_generation(site_id: str) -> dict[str, Any]:
        return to_jsonable(payloads.wiki_generation_payload(site_id))

    @app.get("/api/sites/{site_id}/wiki/pages")
    def wiki_pages(
        site_id: str,
        q: str = "",
        view: str = Query("guides", pattern="^(guides|sources|all)$"),
        limit: int = Query(200, ge=1, le=2000),
    ) -> dict[str, Any]:
        return to_jsonable(payloads.wiki_pages_payload(site_id, query=q, limit=limit, view=view))

    @app.get("/api/sites/{site_id}/tmux-sessions")
    def list_site_tmux_sessions(site_id: str) -> dict[str, Any]:
        return to_jsonable(list_site_tmux_sessions_payload(site_id, site_root_fn=site_root))

    @app.post("/api/sites/{site_id}/tmux-sessions/{session_name}/archive")
    def archive_site_tmux_session(site_id: str, session_name: str) -> dict[str, Any]:
        return to_jsonable(archive_site_tmux_session_payload(site_id, session_name, site_root_fn=site_root))

    @app.get("/api/sites/{site_id}/document-preview")
    def document_preview(site_id: str, path: str, limit_chars: int = Query(80_000, ge=1, le=500_000)) -> dict[str, Any]:
        return to_jsonable(payloads.site_relative_text_payload(site_id, path, limit_chars=limit_chars))

    @app.get("/api/stream/sites/{site_id}")
    async def stream_site(site_id: str, request: Request, interval: float = Query(2.5, ge=0.5, le=10.0)) -> StreamingResponse:
        async def disconnected() -> bool:
            return await request.is_disconnected()

        return StreamingResponse(
            payloads.site_event_stream(site_id, interval, is_disconnected=disconnected),
            media_type="text/event-stream",
        )
