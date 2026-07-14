from backend.agent.graphs.supervisor_graph import (
    _route_after_agents,
    _route_after_planning,
    _route_presentation_context,
    _route_report_context,
)
from backend.agent.tools import extract_urls


def test_extract_urls_finds_and_dedupes():
    text = "See https://example.com/a and https://example.com/a again, plus http://foo.com."
    assert extract_urls(text) == ["https://example.com/a", "http://foo.com"]


def test_extract_urls_strips_trailing_punctuation():
    assert extract_urls("Check this out: https://example.com/page.") == ["https://example.com/page"]


def test_extract_urls_empty_when_none_present():
    assert extract_urls("no links here") == []


def test_route_after_planning_qa_with_docs_and_web():
    state = {"intent": "qa", "needs_docs": True, "needs_web": True, "detected_urls": []}
    assert _route_after_planning(state) == ["pdf_agent", "web_agent"]


def test_route_after_planning_qa_with_url():
    state = {"intent": "qa", "needs_docs": False, "needs_web": False, "detected_urls": ["https://x.com"]}
    assert _route_after_planning(state) == ["url_agent"]


def test_route_after_planning_qa_falls_back_to_synthesize():
    state = {"intent": "qa", "needs_docs": False, "needs_web": False, "detected_urls": []}
    assert _route_after_planning(state) == ["synthesize_answer"]


def test_route_after_planning_report_and_presentation():
    assert _route_after_planning({"intent": "report"}) == ["report_plan_outline"]
    assert _route_after_planning({"intent": "presentation"}) == ["presentation_plan_slides"]


def test_route_after_agents_matches_intent():
    assert _route_after_agents({"intent": "qa"}) == "synthesize_answer"
    assert _route_after_agents({"intent": "report"}) == "report_generate_sections"
    assert _route_after_agents({"intent": "presentation"}) == "presentation_generate_slides"


def test_route_report_and_presentation_context_fallback():
    empty_state = {"needs_docs": False, "needs_web": False}
    assert _route_report_context(empty_state) == ["report_generate_sections"]
    assert _route_presentation_context(empty_state) == ["presentation_generate_slides"]
