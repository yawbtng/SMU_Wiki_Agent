from pathlib import Path

from src.scrape_planner.content_organizer import build_content_organizer_task
from src.scrape_planner.source_exclusion import (
    DO_NOT_PARSE_DECISION,
    SCRAPE_DECISION,
    apply_source_exclusion_plan,
    build_local_source_exclusion_plan,
    normalize_source_decisions,
    summarize_source_exclusion_plan,
)


def test_local_source_exclusion_schema_and_payload_counts():
    rows = [
        {"url": "https://www.smu.edu/admission/apply"},
        {"url": "https://www.smu.edu/search?q=tuition"},
        {"url": "https://www.smu.edu/news/2024/05/story"},
    ]

    plan = build_local_source_exclusion_plan(site_url="https://www.smu.edu", discovered_rows=rows)
    counts = summarize_source_exclusion_plan(plan)

    assert plan["selection_method"] == "local_source_exclusion_fallback"
    assert {row["url"] for row in plan["decisions"]} == {row["url"] for row in rows}
    assert counts["scrape"] == 1
    assert counts["do_not_parse"] == 2
    assert {"url", "decision", "category", "reason", "confidence"}.issubset(plan["decisions"][0])


def test_spam_news_archive_search_excluded_but_university_sources_scrape():
    rows = [
        {"url": "https://www.smu.edu/search?q=registrar"},
        {"url": "https://www.smu.edu/news/2023/old-story"},
        {"url": "https://www.smu.edu/archive/2019/page"},
        {"url": "https://www.smu.edu/events/2023-05-01/open-house"},
        {"url": "https://www.smu.edu/academics/departments/biology"},
        {"url": "https://www.smu.edu/registrar/catalog.pdf"},
        {"url": "https://www.smu.edu/people/faculty/jane-professor"},
        {"url": "https://www.smu.edu/student-affairs/office-of-accessibility"},
    ]

    plan = build_local_source_exclusion_plan(site_url="https://www.smu.edu", discovered_rows=rows)
    by_url = {row["url"]: row for row in plan["decisions"]}

    assert by_url["https://www.smu.edu/search?q=registrar"]["category"] == "search"
    assert by_url["https://www.smu.edu/news/2023/old-story"]["category"] == "news"
    assert by_url["https://www.smu.edu/archive/2019/page"]["category"] == "archive"
    assert by_url["https://www.smu.edu/events/2023-05-01/open-house"]["category"] == "event"
    assert by_url["https://www.smu.edu/academics/departments/biology"]["decision"] == SCRAPE_DECISION
    assert by_url["https://www.smu.edu/registrar/catalog.pdf"]["decision"] == SCRAPE_DECISION
    assert by_url["https://www.smu.edu/people/faculty/jane-professor"]["decision"] == SCRAPE_DECISION
    assert by_url["https://www.smu.edu/student-affairs/office-of-accessibility"]["decision"] == SCRAPE_DECISION


def test_scrape_queue_uses_only_scrape_decisions():
    rows = [
        {"url": "https://www.smu.edu/admission/apply", "source_sitemap": "sitemap"},
        {"url": "https://www.smu.edu/login", "source_sitemap": "sitemap"},
    ]
    plan = {
        "decisions": [
            {"url": rows[0]["url"], "decision": SCRAPE_DECISION, "category": "scrape_candidate", "reason": "ok", "confidence": 0.9},
            {"url": rows[1]["url"], "decision": DO_NOT_PARSE_DECISION, "category": "login", "reason": "auth", "confidence": 0.9},
        ]
    }

    queue_rows = apply_source_exclusion_plan(rows, plan)

    assert [row["url"] for row in queue_rows if row["selected"]] == ["https://www.smu.edu/admission/apply"]
    assert [row["source_category"] for row in queue_rows if not row["selected"]] == ["login"]


def test_normalize_source_decisions_falls_back_for_missing_model_rows():
    rows = [
        {"url": "https://www.smu.edu/admission/apply"},
        {"url": "https://www.smu.edu/feed"},
    ]

    normalized = normalize_source_decisions(rows, [{"url": rows[0]["url"], "decision": "scrape", "category": "weird"}])

    assert normalized[0]["category"] == "scrape_candidate"
    assert normalized[1]["decision"] == DO_NOT_PARSE_DECISION
    assert normalized[1]["category"] == "feed"


def test_content_organizer_task_points_to_expected_artifacts(tmp_path: Path):
    run_root = tmp_path / "sites" / "www.smu.edu" / "run-1"
    skill_path = tmp_path / ".pi" / "skills" / "content-organizer" / "SKILL.md"

    task = build_content_organizer_task(
        run_root=run_root,
        site_url="https://www.smu.edu",
        run_id="run-1",
        skill_path=skill_path,
    )

    assert str(skill_path) in task
    assert str(run_root / "scrape_manifest.json") in task
    assert str(run_root / "cleanup_manifest.json") in task
    assert str(run_root / "wiki" / "graph.json") in task
    assert str(run_root / "content_organizer" / "quarantine.json") in task
