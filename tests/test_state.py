from src.scrape_planner.state import RunStateStore


def test_port_zero_redis_url_disables_redis_client() -> None:
    store = RunStateStore(redis_url="redis://127.0.0.1:0/0")

    assert store._client is None
