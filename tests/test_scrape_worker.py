import json
from pathlib import Path
from types import SimpleNamespace
import threading
import time

from src.scrape_planner.models import DiscoveredURL
from src.scrape_planner.scrape_worker import ScrapeRunner, _extract_response_parts
from src.scrape_planner.state import RunStateStore


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "<html>ok</html>", content_type: str = "text/html"):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _FakeScraplingResponse:
    status = 200
    text = "None"
    body = "<html>scrapling body</html>"
    headers = {"content-type": "text/html; charset=utf-8"}


def _make_runner(tmp_path: Path) -> tuple[ScrapeRunner, RunStateStore]:
    state = RunStateStore(redis_url="redis://127.0.0.1:0/0")
    return ScrapeRunner(state=state, base_data_dir=tmp_path), state


def _selected_urls(*urls: str) -> list[DiscoveredURL]:
    return [DiscoveredURL(url=url, source_sitemap="https://example.com/sitemap.xml", selected=True) for url in urls]


def test_extract_response_parts_supports_scrapling_response_shape():
    status, content_type, html = _extract_response_parts(_FakeScraplingResponse())

    assert status == 200
    assert content_type == "text/html; charset=utf-8"
    assert html == "<html>scrapling body</html>"


def test_execute_success_path(monkeypatch, tmp_path: Path):
    runner, state = _make_runner(tmp_path)

    monkeypatch.setattr(runner, "_fetch_with_mode", lambda mode, url: _FakeResponse())
    monkeypatch.setattr(
        "src.scrape_planner.scrape_worker.extract_content",
        lambda html: ("text", "# title\nbody", 1200, 0.02),
    )

    runner._execute("site-a", "run-1", _selected_urls("https://example.com/a"))

    status = state.get_status("site-a", "run-1")
    pages = state.get_pages("site-a", "run-1")
    events = state.get_events("site-a", "run-1")
    assert status["state"] == "completed"
    assert status["success"] == 1
    assert status["failed"] == 0
    assert len(pages) == 1
    assert pages[0]["status"] == "success"
    assert pages[0]["markdown_path"]
    assert any(e["event"] == "artifacts_saved" for e in events)
    assert (tmp_path / "sites" / "site-a" / "run-1" / "scrape_manifest.json").exists()


def test_execute_pdf_url_downloads_and_writes_pdf_chunks(monkeypatch, tmp_path: Path):
    runner, state = _make_runner(tmp_path)
    item = DiscoveredURL(
        url="https://example.com/catalog.pdf",
        source_sitemap="https://example.com/sitemap.xml",
        content_type_guess="pdf",
        selected=True,
    )

    monkeypatch.setattr(
        "src.scrape_planner.scrape_worker.requests.get",
        lambda url, timeout, stream=False: _FakeResponse(text="%PDF-1.7", content_type="application/pdf"),
    )

    class Source:
        accepted = True

        def to_dict(self):
            return {"pdf_source_id": "pdf-1", "path": str(tmp_path / "catalog.pdf"), "accepted": True}

    class Chunk:
        char_count = 19

        def to_dict(self):
            return {"chunk_id": "chunk-1", "pdf_source_id": "pdf-1", "text": "PDF catalog content", "char_count": 19}

    monkeypatch.setattr(
        "src.scrape_planner.scrape_worker.ingest_pdfs",
        lambda paths, config: SimpleNamespace(sources=[Source()], chunks=[Chunk()], quarantine=[]),
    )

    runner._execute("site-a", "run-pdf", [item])

    run_root = tmp_path / "sites" / "site-a" / "run-pdf"
    pages = state.get_pages("site-a", "run-pdf")
    events = state.get_events("site-a", "run-pdf")
    chunks = [json.loads(line) for line in (run_root / "s05" / "pdf_chunks.jsonl").read_text(encoding="utf-8").splitlines()]

    assert pages[0]["status"] == "success"
    assert pages[0]["fetch_mode"] == "pdf"
    assert pages[0]["raw_html_path"].endswith("catalog.pdf")
    assert pages[0]["markdown_path"] is None
    assert chunks[0]["text"] == "PDF catalog content"
    assert any(event["event"] == "pdf_artifacts_saved" for event in events)


def test_execute_retry_then_success(monkeypatch, tmp_path: Path):
    runner, state = _make_runner(tmp_path)
    monkeypatch.setenv("SCRAPE_BROWSER_MODE", "lightpanda")
    monkeypatch.setenv("LIGHTPANDA_CDP_URL", "ws://127.0.0.1:9222")
    calls: list[str] = []

    def fake_fetch(mode: str, url: str):
        calls.append(mode)
        if mode == "fetcher":
            return _FakeResponse(status_code=403)
        return _FakeResponse(status_code=200)

    monkeypatch.setattr(runner, "_fetch_with_mode", fake_fetch)
    monkeypatch.setattr(
        "src.scrape_planner.scrape_worker.extract_content",
        lambda html: ("text", "# ok", 900, 0.03),
    )

    runner._execute("site-a", "run-2", _selected_urls("https://example.com/retry"))
    events = state.get_events("site-a", "run-2")
    pages = state.get_pages("site-a", "run-2")
    assert calls[:2] == ["fetcher", "lightpanda"]
    assert any(e["event"] == "fetch_retrying_next_mode" for e in events)
    assert pages[0]["status"] == "success"
    assert pages[0]["fetch_mode"] == "lightpanda"


def test_execute_failed_path_and_grouped_failures(monkeypatch, tmp_path: Path):
    runner, state = _make_runner(tmp_path)

    monkeypatch.setattr(runner, "_fetch_with_mode", lambda mode, url: _FakeResponse(status_code=500))
    monkeypatch.setattr(
        "src.scrape_planner.scrape_worker.extract_content",
        lambda html: ("", "", 0, 0.0),
    )

    runner._execute(
        "site-a",
        "run-3",
        _selected_urls("https://example.com/f1", "https://example.com/f2"),
    )

    status = state.get_status("site-a", "run-3")
    failures_path = tmp_path / "sites" / "site-a" / "run-3" / "failures.json"
    failures = __import__("json").loads(failures_path.read_text(encoding="utf-8"))
    grouped: dict[str, int] = {}
    for row in failures:
        grouped[row["reason"]] = grouped.get(row["reason"], 0) + 1

    assert status["failed"] == 2
    assert status["success"] == 0
    assert grouped == {"http_error": 2}


def test_cancel_before_run(monkeypatch, tmp_path: Path):
    runner, state = _make_runner(tmp_path)
    state.set_cancel("site-a", "run-4", True)
    monkeypatch.setattr(runner, "_fetch_with_mode", lambda mode, url: _FakeResponse())
    monkeypatch.setattr(
        "src.scrape_planner.scrape_worker.extract_content",
        lambda html: ("text", "ok", 1000, 0.01),
    )

    runner._execute("site-a", "run-4", _selected_urls("https://example.com/a"))

    status = state.get_status("site-a", "run-4")
    events = state.get_events("site-a", "run-4")
    assert status["state"] == "cancelled"
    assert status["success"] == 0
    assert status["failed"] == 0
    assert any(e["event"] == "run_cancelled" for e in events)


def test_cancel_mid_run(monkeypatch, tmp_path: Path):
    runner, state = _make_runner(tmp_path)
    seen = {"count": 0}

    def fake_fetch(mode: str, url: str):
        seen["count"] += 1
        if seen["count"] == 1:
            state.set_cancel("site-a", "run-5", True)
        return _FakeResponse()

    monkeypatch.setattr(runner, "_fetch_with_mode", fake_fetch)
    monkeypatch.setattr(
        "src.scrape_planner.scrape_worker.extract_content",
        lambda html: ("text", "# ok", 1000, 0.01),
    )

    runner._execute(
        "site-a",
        "run-5",
        _selected_urls("https://example.com/1", "https://example.com/2"),
        concurrency=1,
    )
    status = state.get_status("site-a", "run-5")
    pages = state.get_pages("site-a", "run-5")

    assert status["state"] == "cancelled"
    assert status["success"] == 0
    assert len(pages) == 2
    assert [page["status"] for page in pages] == ["cancelled", "cancelled"]


def test_pause_then_unpause_blocks_new_queue_items(monkeypatch, tmp_path: Path):
    runner, state = _make_runner(tmp_path)
    release = threading.Event()
    seen: list[str] = []

    def fake_fetch(mode: str, url: str):
        seen.append(url)
        if url.endswith("/1"):
            runner.pause("site-a", "run-6")
            release.wait(timeout=2.0)
        return _FakeResponse()

    monkeypatch.setattr(runner, "_fetch_with_mode", fake_fetch)
    monkeypatch.setattr(
        "src.scrape_planner.scrape_worker.extract_content",
        lambda html: ("text", "# ok", 1000, 0.01),
    )

    runner.start(
        "site-a",
        "run-6",
        _selected_urls("https://example.com/1", "https://example.com/2"),
        concurrency=1,
    )
    time.sleep(0.25)
    paused_status = state.get_status("site-a", "run-6")
    assert paused_status["state"] in {"pausing", "paused"}
    assert seen == ["https://example.com/1"]

    runner.unpause("site-a", "run-6")
    release.set()
    time.sleep(0.35)

    final_status = state.get_status("site-a", "run-6")
    assert final_status["state"] == "completed"
    assert final_status["success"] == 2
    assert seen == ["https://example.com/1", "https://example.com/2"]


def test_resume_reuses_existing_success_pages(monkeypatch, tmp_path: Path):
    runner, state = _make_runner(tmp_path)
    run_root = tmp_path / "sites" / "site-a" / "run-7"
    run_root.mkdir(parents=True, exist_ok=True)
    selected = _selected_urls("https://example.com/1", "https://example.com/2")
    (run_root / "selected_urls.json").write_text(
        json.dumps([item.to_dict() for item in selected], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    state.set_pages(
        "site-a",
        "run-7",
        [
            {"url": "https://example.com/1", "status": "success", "fetch_mode": "fetcher"},
            {"url": "https://example.com/2", "status": "cancelled", "fetch_mode": "fetcher"},
        ],
    )
    state.set_status(
        "site-a",
        "run-7",
        {"state": "cancelled", "running": 0, "success": 1, "failed": 0, "cancelled": 1, "queued": 0, "total": 2},
    )

    seen: list[str] = []

    def fake_fetch(mode: str, url: str):
        seen.append(url)
        return _FakeResponse()

    monkeypatch.setattr(runner, "_fetch_with_mode", fake_fetch)
    monkeypatch.setattr(
        "src.scrape_planner.scrape_worker.extract_content",
        lambda html: ("text", "# ok", 1000, 0.01),
    )

    resumed = runner.resume("site-a", "run-7", concurrency=1)
    assert resumed is True
    time.sleep(0.35)

    pages = state.get_pages("site-a", "run-7")
    by_url = {row["url"]: row for row in pages}
    status = state.get_status("site-a", "run-7")

    assert seen == ["https://example.com/2"]
    assert by_url["https://example.com/1"]["status"] == "success"
    assert by_url["https://example.com/2"]["status"] == "success"
    assert status["state"] == "completed"


def test_has_live_run_reflects_background_thread_liveness(monkeypatch, tmp_path: Path):
    runner, _state = _make_runner(tmp_path)
    release = threading.Event()

    def fake_fetch(mode: str, url: str):
        release.wait(timeout=2.0)
        return _FakeResponse()

    monkeypatch.setattr(runner, "_fetch_with_mode", fake_fetch)
    monkeypatch.setattr(
        "src.scrape_planner.scrape_worker.extract_content",
        lambda html: ("text", "# ok", 1000, 0.01),
    )

    runner.start("site-a", "run-live", _selected_urls("https://example.com/1"), concurrency=1)
    time.sleep(0.1)
    assert runner.has_live_run("site-a", "run-live") is True

    release.set()
    time.sleep(0.25)
    assert runner.has_live_run("site-a", "run-live") is False


def test_execute_batches_durable_page_state_writes(monkeypatch, tmp_path: Path):
    runner, _state = _make_runner(tmp_path)
    page_state_writes: list[int] = []
    run_status_writes: list[str] = []

    monkeypatch.setattr(runner, "_fetch_with_mode", lambda mode, url: _FakeResponse())
    monkeypatch.setattr(
        "src.scrape_planner.scrape_worker.extract_content",
        lambda html: ("text", "# ok", 1000, 0.01),
    )
    monkeypatch.setattr(
        "src.scrape_planner.scrape_worker.write_page_states",
        lambda run_root, pages: page_state_writes.append(len(pages)),
    )
    monkeypatch.setattr(
        "src.scrape_planner.scrape_worker.write_run_status",
        lambda run_root, status: run_status_writes.append(str(status.get("state") or "")),
    )

    runner._execute(
        "site-a",
        "run-batched",
        _selected_urls("https://example.com/1", "https://example.com/2", "https://example.com/3"),
        concurrency=1,
    )

    assert len(page_state_writes) <= 3
    assert len(run_status_writes) <= 3


def test_pause_interrupts_inflight_request_and_resume_finishes(monkeypatch, tmp_path: Path):
    runner, state = _make_runner(tmp_path)
    selected = _selected_urls("https://example.com/interrupt-me")
    first_chunk_seen = threading.Event()
    request_calls = {"count": 0}

    class _StreamingResponse:
        def __init__(self, body_parts: list[bytes]):
            self.status_code = 200
            self.headers = {"content-type": "text/html; charset=utf-8"}
            self._body_parts = body_parts
            self.closed = False

        def close(self):
            self.closed = True

        def iter_content(self, chunk_size: int = 65536):
            for idx, part in enumerate(self._body_parts):
                if idx == 0:
                    first_chunk_seen.set()
                    yield part
                    continue
                time.sleep(0.2)
                yield part

    def fake_get(url: str, timeout=None, stream: bool = False):
        request_calls["count"] += 1
        if request_calls["count"] == 1:
            return _StreamingResponse([b"<html>", b"body</html>"])
        return _StreamingResponse([b"<html>body</html>"])

    monkeypatch.setattr("src.scrape_planner.scrape_worker.requests.get", fake_get)
    monkeypatch.setattr(
        "src.scrape_planner.scrape_worker.extract_content",
        lambda html: ("text", "# ok", 1000, 0.01),
    )

    runner.start("site-a", "run-interrupt", selected, concurrency=1, browser_mode="none")
    assert first_chunk_seen.wait(timeout=2.0)

    runner.pause("site-a", "run-interrupt")
    time.sleep(0.25)
    paused_status = state.get_status("site-a", "run-interrupt")
    paused_pages = state.get_pages("site-a", "run-interrupt")

    assert paused_status["state"] in {"pausing", "paused"}
    assert paused_pages[0]["status"] == "queued"

    resumed = runner.resume("site-a", "run-interrupt", concurrency=1, browser_mode="none")
    if not resumed:
        runner.unpause("site-a", "run-interrupt")
    time.sleep(0.35)

    final_status = state.get_status("site-a", "run-interrupt")
    final_pages = state.get_pages("site-a", "run-interrupt")

    assert request_calls["count"] >= 2
    assert final_status["state"] == "completed"
    assert final_pages[0]["status"] == "success"
