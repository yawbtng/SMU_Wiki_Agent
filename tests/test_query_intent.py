from __future__ import annotations

from src.scrape_planner.wiki.query_intent import is_person_lookup_query, prepare_retrieval_query


def test_networking_director_query_expands_to_network_engineering() -> None:
    plan = prepare_retrieval_query("Who is the director of SMU networking?")

    assert plan.person_lookup is True
    assert "network engineering" in plan.effective.lower()
    assert "lyle" in plan.effective.lower()
    assert "network engineering" in plan.expansions


def test_admissions_query_is_not_person_lookup() -> None:
    plan = prepare_retrieval_query("When is the graduate admissions deadline?")

    assert plan.person_lookup is False
    assert plan.effective == plan.original


def test_who_question_is_person_lookup() -> None:
    assert is_person_lookup_query("Who teaches linear algebra?") is True
