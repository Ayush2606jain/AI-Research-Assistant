from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # Input
    query: str
    thread_id: str
    doc_ids: Optional[list[str]]
    messages: Annotated[list, add_messages]

    # Routing / planning
    detected_urls: list[str]
    intent: str  # "qa" | "report" | "presentation"
    needs_web: bool
    needs_docs: bool

    # QA agents
    retrieved_chunks: list[Any]
    web_results: list[dict]
    url_context: list[dict]
    answer: str
    citations: list[dict]

    # Report agent
    report_type: str
    title: str
    outline: list[str]
    sections: dict[str, str]
    markdown_path: str
    docx_path: str
    pdf_path: str

    # Presentation agent
    num_slides: int
    slide_titles: list[str]
    slide_content: dict[str, list[str]]
    pptx_path: str
