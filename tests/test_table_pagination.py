from src.scrape_planner.table_pagination import dynamic_page_size_options


def test_dynamic_page_size_options_include_large_row_counts() -> None:
    assert dynamic_page_size_options(25_384, default_page_size=100) == [
        25,
        50,
        100,
        200,
        500,
        1_000,
        2_500,
        5_000,
        10_000,
        25_384,
    ]


def test_dynamic_page_size_options_stay_small_for_small_tables() -> None:
    assert dynamic_page_size_options(73, default_page_size=100) == [25, 50, 73, 100]
