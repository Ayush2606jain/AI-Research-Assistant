import uuid

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from backend import workspace_store
from backend.agent.state import AgentState
from backend.agent.tools import extract_urls, get_chat_llm, get_report_llm, web_search_tool, with_retry
from backend.rag.prompt_templates import (
    GENERAL_ANSWER_SYSTEM,
    PLANNER_SYSTEM,
    RAG_ANSWER_SYSTEM,
    REPORT_OUTLINE_SYSTEM,
    REPORT_SECTION_SYSTEM,
    SLIDE_CONTENT_SYSTEM,
    SLIDE_OUTLINE_SYSTEM,
    format_context,
)
from backend.rag.retriever import ingest_chunks, retrieve

REPORT_RETRIEVAL_K = 10
CHAT_RETRIEVAL_K = 5


class _PlannerOutput(BaseModel):
    intent: str
    needs_docs: bool
    needs_web: bool
    report_type: str = "summary"
    num_slides: int = 8


class _Outline(BaseModel):
    title: str
    sections: list[str]


class _SlideOutline(BaseModel):
    title: str
    slide_titles: list[str]


def _build_citations(chunks: list, web_results: list[dict], url_context: list[dict] | None = None) -> list[dict]:
    citations = [
        {
            "source": chunk.source,
            "doc_id": chunk.doc_id,
            "page": chunk.page,
            "url": None,
            "snippet": chunk.text[:240],
        }
        for chunk in chunks
    ]
    citations += [
        {
            "source": result.get("title", "Web result"),
            "doc_id": None,
            "page": None,
            "url": result.get("url"),
            "snippet": result.get("content", "")[:240],
        }
        for result in web_results
    ]
    citations += [
        {
            "source": entry.get("title", entry.get("url", "URL")),
            "doc_id": None,
            "page": None,
            "url": entry.get("url"),
            "snippet": entry.get("text", "")[:240],
        }
        for entry in (url_context or [])
    ]
    return citations


# ── Routing / planning ───────────────────────────────────────────────
def route_urls(state: AgentState) -> dict:
    return {"detected_urls": extract_urls(state["query"])}


def planner(state: AgentState) -> dict:
    has_documents = bool(workspace_store.list_documents())
    urls = state.get("detected_urls", [])
    url_note = (
        "The message includes a URL, so needs_web should usually be false, and needs_docs should "
        "also usually be false unless the question clearly also asks about the user's own document "
        "library — that URL's own content will be fetched and used directly."
        if urls
        else ""
    )
    llm = with_retry(get_chat_llm().with_structured_output(_PlannerOutput))
    prompt = (
        f"{PLANNER_SYSTEM.format(has_documents=has_documents, detected_urls=urls or 'none', url_note=url_note)}"
        f"\n\nUser message: {state['query']}"
    )
    result: _PlannerOutput = llm.invoke(prompt)
    return {
        "intent": result.intent,
        "needs_docs": result.needs_docs,
        "needs_web": result.needs_web,
        "report_type": result.report_type,
        "num_slides": max(3, min(20, result.num_slides)),
    }


# ── QA agents ─────────────────────────────────────────────────────────
def pdf_agent(state: AgentState) -> dict:
    if not state.get("needs_docs", True):
        return {"retrieved_chunks": []}
    k = REPORT_RETRIEVAL_K if state.get("intent") in {"report", "presentation"} else CHAT_RETRIEVAL_K
    chunks = retrieve(state["query"], k=k, doc_ids=state.get("doc_ids"))
    return {"retrieved_chunks": chunks}


def web_agent(state: AgentState) -> dict:
    if not state.get("needs_web", False):
        return {"web_results": []}
    return {"web_results": web_search_tool(state["query"])}


def url_agent(state: AgentState) -> dict:
    urls = state.get("detected_urls", [])
    if not urls:
        return {"url_context": []}

    from backend.processing.chunker import chunk_text
    from backend.processing.web_scraper import WebScrapeError, scrape_url

    context_entries = []
    for url in urls:
        try:
            scraped = scrape_url(url)
        except WebScrapeError:
            continue
        doc_id = uuid.uuid4().hex[:12]
        chunks = chunk_text(scraped["text"], {"doc_id": doc_id, "source": scraped["title"]})
        if chunks:
            ingest_chunks(chunks)
            workspace_store.create_document(doc_id, scraped["title"], "url", len(chunks))
        context_entries.append({"title": scraped["title"], "url": url, "text": scraped["text"][:4000]})
    return {"url_context": context_entries}


def synthesize_answer(state: AgentState) -> dict:
    chunks = state.get("retrieved_chunks", [])
    web_results = state.get("web_results", [])
    url_context = state.get("url_context", [])
    if chunks or web_results or url_context:
        context = format_context(chunks, web_results, url_context)
        system = SystemMessage(RAG_ANSWER_SYSTEM.format(context=context))
    else:
        system = SystemMessage(GENERAL_ANSWER_SYSTEM)
    history = state.get("messages", [])
    response = with_retry(get_chat_llm()).invoke([system, *history, HumanMessage(state["query"])])
    citations = _build_citations(
        state.get("retrieved_chunks", []), state.get("web_results", []), state.get("url_context", [])
    )
    return {
        "answer": response.content,
        "citations": citations,
        "messages": [HumanMessage(state["query"]), AIMessage(response.content)],
    }


# ── Report agent ──────────────────────────────────────────────────────
def report_plan_outline(state: AgentState) -> dict:
    llm = with_retry(get_report_llm().with_structured_output(_Outline))
    prompt = f"{REPORT_OUTLINE_SYSTEM.format(report_type=state.get('report_type', 'summary'))}\n\nTopic: {state['query']}"
    result: _Outline = llm.invoke(prompt)
    return {"title": result.title, "outline": result.sections}


def report_generate_sections(state: AgentState) -> dict:
    llm = with_retry(get_report_llm())
    context = format_context(
        state.get("retrieved_chunks", []), state.get("web_results", []), state.get("url_context", [])
    )
    sections: dict[str, str] = {}
    for section_title in state.get("outline", []):
        system = SystemMessage(
            REPORT_SECTION_SYSTEM.format(
                report_title=state.get("title", state["query"]),
                section_title=section_title,
                context=context,
            )
        )
        response = llm.invoke([system, HumanMessage(f"Write the '{section_title}' section.")])
        sections[section_title] = response.content
    citations = _build_citations(
        state.get("retrieved_chunks", []), state.get("web_results", []), state.get("url_context", [])
    )
    return {"sections": sections, "citations": citations}


def report_export(state: AgentState) -> dict:
    from backend.generators.report_generator import generate_report

    paths = generate_report(
        title=state.get("title", state["query"]),
        sections=state.get("sections", {}),
        citations=state.get("citations", []),
    )
    answer = f"I've generated your {state.get('report_type', 'summary')} report on \"{paths['title']}\". Download it below."
    return {
        **paths,
        "answer": answer,
        "messages": [HumanMessage(state["query"]), AIMessage(answer)],
    }


# ── Presentation agent ────────────────────────────────────────────────
def presentation_plan_slides(state: AgentState) -> dict:
    llm = with_retry(get_report_llm().with_structured_output(_SlideOutline))
    num_slides = state.get("num_slides", 8)
    prompt = f"{SLIDE_OUTLINE_SYSTEM.format(num_slides=num_slides)}\n\nTopic: {state['query']}"
    result: _SlideOutline = llm.invoke(prompt)
    return {"title": result.title, "slide_titles": result.slide_titles}


def presentation_generate_slides(state: AgentState) -> dict:
    llm = with_retry(get_report_llm())
    context = format_context(
        state.get("retrieved_chunks", []), state.get("web_results", []), state.get("url_context", [])
    )
    slide_content: dict[str, list[str]] = {}
    for slide_title in state.get("slide_titles", []):
        if slide_title.lower() in {"title", "agenda", "references"}:
            slide_content[slide_title] = []
            continue
        system = SystemMessage(
            SLIDE_CONTENT_SYSTEM.format(slide_title=slide_title, topic=state.get("title", state["query"]), context=context)
        )
        response = llm.invoke([system, HumanMessage(f"Write bullets for '{slide_title}'.")])
        bullets = [line.strip("-• ").strip() for line in response.content.splitlines() if line.strip()]
        slide_content[slide_title] = bullets
    citations = _build_citations(
        state.get("retrieved_chunks", []), state.get("web_results", []), state.get("url_context", [])
    )
    return {"slide_content": slide_content, "citations": citations}


def presentation_build(state: AgentState) -> dict:
    from backend.generators.pptx_generator import generate_presentation

    slide_titles = state.get("slide_titles", [])
    pptx_path = generate_presentation(
        title=state.get("title", state["query"]),
        slide_titles=slide_titles,
        slide_content=state.get("slide_content", {}),
        citations=state.get("citations", []),
    )
    answer = (
        f"I've generated your presentation \"{state.get('title', state['query'])}\" "
        f"({len(slide_titles)} slides). Download it below."
    )
    return {
        "pptx_path": pptx_path,
        "answer": answer,
        "messages": [HumanMessage(state["query"]), AIMessage(answer)],
    }
