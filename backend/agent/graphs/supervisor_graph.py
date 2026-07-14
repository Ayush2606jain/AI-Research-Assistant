from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from backend.agent.nodes import (
    pdf_agent,
    planner,
    presentation_build,
    presentation_generate_slides,
    presentation_plan_slides,
    report_export,
    report_generate_sections,
    report_plan_outline,
    route_urls,
    synthesize_answer,
    url_agent,
    web_agent,
)
from backend.agent.state import AgentState

_checkpointer = MemorySaver()
_graph = None

_AGENT_DESTINATIONS = ["synthesize_answer", "report_generate_sections", "presentation_generate_slides"]


def _wanted_context_agents(state: AgentState) -> list[str]:
    agents = []
    if state.get("needs_docs", True):
        agents.append("pdf_agent")
    if state.get("needs_web", False):
        agents.append("web_agent")
    return agents


def _route_after_planning(state: AgentState) -> list[str]:
    intent = state.get("intent", "qa")
    if intent == "report":
        return ["report_plan_outline"]
    if intent == "presentation":
        return ["presentation_plan_slides"]

    agents = _wanted_context_agents(state)
    if state.get("detected_urls"):
        agents.append("url_agent")
    return agents or ["synthesize_answer"]


def _route_report_context(state: AgentState) -> list[str]:
    return _wanted_context_agents(state) or ["report_generate_sections"]


def _route_presentation_context(state: AgentState) -> list[str]:
    return _wanted_context_agents(state) or ["presentation_generate_slides"]


def _route_after_agents(state: AgentState) -> str:
    intent = state.get("intent", "qa")
    if intent == "report":
        return "report_generate_sections"
    if intent == "presentation":
        return "presentation_generate_slides"
    return "synthesize_answer"


def _build() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("route_urls", route_urls)
    graph.add_node("planner", planner)
    graph.add_node("pdf_agent", pdf_agent)
    graph.add_node("web_agent", web_agent)
    graph.add_node("url_agent", url_agent)
    graph.add_node("synthesize_answer", synthesize_answer)
    graph.add_node("report_plan_outline", report_plan_outline)
    graph.add_node("report_generate_sections", report_generate_sections)
    graph.add_node("report_export", report_export)
    graph.add_node("presentation_plan_slides", presentation_plan_slides)
    graph.add_node("presentation_generate_slides", presentation_generate_slides)
    graph.add_node("presentation_build", presentation_build)

    graph.set_entry_point("route_urls")
    graph.add_edge("route_urls", "planner")

    graph.add_conditional_edges(
        "planner",
        _route_after_planning,
        ["pdf_agent", "web_agent", "url_agent", "synthesize_answer", "report_plan_outline", "presentation_plan_slides"],
    )
    graph.add_conditional_edges("pdf_agent", _route_after_agents, _AGENT_DESTINATIONS)
    graph.add_conditional_edges("web_agent", _route_after_agents, _AGENT_DESTINATIONS)
    graph.add_conditional_edges("url_agent", _route_after_agents, _AGENT_DESTINATIONS)

    graph.add_conditional_edges(
        "report_plan_outline", _route_report_context, ["pdf_agent", "web_agent", "report_generate_sections"]
    )
    graph.add_conditional_edges(
        "presentation_plan_slides",
        _route_presentation_context,
        ["pdf_agent", "web_agent", "presentation_generate_slides"],
    )

    graph.add_edge("synthesize_answer", END)
    graph.add_edge("report_generate_sections", "report_export")
    graph.add_edge("report_export", END)
    graph.add_edge("presentation_generate_slides", "presentation_build")
    graph.add_edge("presentation_build", END)

    return graph.compile(checkpointer=_checkpointer)


def get_supervisor_graph():
    global _graph
    if _graph is None:
        _graph = _build()
    return _graph
