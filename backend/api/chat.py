import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from backend.agent.graphs.supervisor_graph import get_supervisor_graph
from backend.models.schemas import ChatRequest
from backend.rate_limit import limiter

router = APIRouter(tags=["chat"])

# Exactly one of these runs per turn, depending on which branch the planner picked.
_TERMINAL_NODES = {"synthesize_answer", "report_export", "presentation_build"}


def _friendly_error_message(exc: Exception) -> str:
    text = str(exc)
    name = type(exc).__name__
    if "ResourceExhausted" in name or "429" in text or "quota" in text.lower():
        return (
            "The AI model has hit its Gemini API usage limit right now. Try again in a bit, "
            "switch LLM_MODEL/REPORT_LLM_MODEL in .env to a different model, or enable billing "
            "on your Google AI Studio project to remove this limit."
        )
    return "Something went wrong while generating a response. Please try again."


@router.post("/chat")
@limiter.limit("30/minute")
async def chat(request: Request, body: ChatRequest):
    graph = get_supervisor_graph()
    config = {"configurable": {"thread_id": body.thread_id}}
    inputs = {"query": body.query, "doc_ids": body.doc_ids}

    async def event_generator():
        result: dict = {}
        used_rag = False
        used_web = False

        try:
            async for event in graph.astream_events(inputs, config=config, version="v2"):
                kind = event["event"]
                node = event.get("metadata", {}).get("langgraph_node")

                if kind == "on_chat_model_stream" and node == "synthesize_answer":
                    chunk = event["data"]["chunk"]
                    if chunk.content:
                        yield {"event": "token", "data": chunk.content}

                elif kind == "on_chain_end" and node in _TERMINAL_NODES:
                    output = event["data"].get("output")
                    if isinstance(output, dict):
                        result.update(output)

                elif kind == "on_chain_end" and node == "pdf_agent":
                    output = event["data"].get("output")
                    if isinstance(output, dict):
                        used_rag = bool(output.get("retrieved_chunks"))

                elif kind == "on_chain_end" and node == "web_agent":
                    output = event["data"].get("output")
                    if isinstance(output, dict):
                        used_web = bool(output.get("web_results"))
        except Exception as exc:
            yield {"event": "error", "data": json.dumps({"message": _friendly_error_message(exc)})}
            return

        yield {
            "event": "done",
            "data": json.dumps(
                {
                    "answer": result.get("answer", ""),
                    "citations": result.get("citations", []),
                    "used_rag": used_rag,
                    "used_web_search": used_web,
                    "markdown_path": result.get("markdown_path"),
                    "docx_path": result.get("docx_path"),
                    "pdf_path": result.get("pdf_path"),
                    "pptx_path": result.get("pptx_path"),
                }
            ),
        }

    return EventSourceResponse(event_generator())
