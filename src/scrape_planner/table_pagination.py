from __future__ import annotations


BASE_PAGE_SIZE_OPTIONS = (25, 50, 100, 200, 500)


def dynamic_page_size_options(total_rows: int, default_page_size: int = 100) -> list[int]:
    options = {size for size in BASE_PAGE_SIZE_OPTIONS if size <= max(total_rows, 1)}
    options.add(min(max(total_rows, 1), 1_000))
    options.add(min(max(total_rows, 1), 2_500))
    options.add(min(max(total_rows, 1), 5_000))
    options.add(min(max(total_rows, 1), 10_000))
    options.add(max(1, int(default_page_size)))
    options.add(max(total_rows, 1))
    return sorted(options)
