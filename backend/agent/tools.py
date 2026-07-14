import re
from functools import lru_cache

from google.api_core.exceptions import DeadlineExceeded, ServiceUnavailable
from langchain_google_genai import ChatGoogleGenerativeAI
from tavily import TavilyClient

from backend.config import get_settings

_URL_PATTERN = re.compile(r"https?://[^\s<>\"')\]]+")


def extract_urls(text: str) -> list[str]:
    """Pull http(s) URLs out of free text via regex — deterministic and
    free, so the planner doesn't have to spend an LLM call detecting them."""
    seen: list[str] = []
    for match in _URL_PATTERN.findall(text):
        url = match.rstrip(".,;:!?")
        if url not in seen:
            seen.append(url)
    return seen


@lru_cache
def get_chat_llm() -> ChatGoogleGenerativeAI:
    settings = get_settings()
    return ChatGoogleGenerativeAI(
        model=settings.llm_model,
        google_api_key=settings.gemini_api_key,
        temperature=0.3,
    )


@lru_cache
def get_report_llm() -> ChatGoogleGenerativeAI:
    settings = get_settings()
    return ChatGoogleGenerativeAI(
        model=settings.report_llm_model,
        google_api_key=settings.gemini_api_key,
        temperature=0.4,
    )


def with_retry(runnable):
    """Wrap a Runnable (a plain chat model OR a `.with_structured_output()`
    chain) with retry-on-failure. Applied at each call site rather than
    baked into the cached LLM singletons above, because `.with_structured_output()`
    only exists on the raw chat model — the `RunnableRetry` that `.with_retry()`
    produces doesn't proxy it.

    Only retries genuinely transient errors (service unavailable, deadline
    exceeded) — deliberately NOT quota/rate-limit errors (ResourceExhausted),
    which won't succeed no matter how many times or how long we wait within
    one request. Retrying those just stalls the response for 30-50+ seconds
    before failing anyway, so we fail fast instead and let the caller show a
    clean error immediately."""
    return runnable.with_retry(
        retry_if_exception_type=(ServiceUnavailable, DeadlineExceeded),
        stop_after_attempt=2,
    )


@lru_cache
def _get_tavily_client() -> TavilyClient | None:
    settings = get_settings()
    if not settings.tavily_api_key or settings.tavily_api_key.startswith("tvly-REPLACE"):
        return None
    return TavilyClient(api_key=settings.tavily_api_key)


def web_search_tool(query: str, max_results: int = 5) -> list[dict]:
    """Search the web via Tavily. Returns [] on any failure (missing/invalid
    key, network error, rate limit) so callers can degrade to RAG-only."""
    client = _get_tavily_client()
    if client is None:
        return []
    try:
        response = client.search(query=query, max_results=max_results)
    except Exception:
        return []
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
        for r in response.get("results", [])
    ]
