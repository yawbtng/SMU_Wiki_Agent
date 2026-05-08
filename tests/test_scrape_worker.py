from pathlib import Path

from src.scrape_planner.models import DiscoveredURL
from src.scrape_planner.scrape_worker import ScrapeRunner
from src.scrape_planner.state import RunStateStore


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "<html>ok</html>", content_type: str = "text/html"):
        self.status_code = status_code
        self.text = text
        self.headers = {"content-type": content_type}


def _make_runner(tmp_path: Path) -> tuple[ScrapeRunner, RunStateStore]:
    state = RunStateStore(redis_url="redis://127.0.0.1:0/0")
    return ScrapeRunner(state=state, base_data_dir=tmp_path), state


def _selected_urls(*urls: str) -> list[DiscoveredURL]:
    return [DiscoveredURL(url=url, source_sitemap="https://example.com/sitemap.xml", selected=True) for url in urls]


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


def test_execute_retry_then_success(monkeypatch, tmp_path: Path):
    runner, state = _make_runner(tmp_path)
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
    assert calls[:2] == ["fetcher", "dynamic"]
    assert any(e["event"] == "fetch_retrying_next_mode" for e in events)
    assert pages[0]["status"] == "success"
    assert pages[0]["fetch_mode"] == "dynamic"


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
    )
    status = state.get_status("site-a", "run-5")
    pages = state.get_pages("site-a", "run-5")

    assert status["state"] == "cancelled"
    assert status["success"] == 1
    assert len(pages) == 1
