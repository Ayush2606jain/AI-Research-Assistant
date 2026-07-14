# AI Research Assistant

A single-page, multi-agent research assistant: ask a question, paste a URL,
or ask for a report/presentation — all through one chat box. A planner
decides which specialized agent(s) handle each message, powered by **Google
Gemini**, **LangGraph**, **ChromaDB**, and **FastAPI + Streamlit**.

## Architecture

- **Backend**: FastAPI (`backend/`) — document ingestion, RAG retrieval, and
  one multi-agent LangGraph supervisor graph.
- **Frontend**: Streamlit (`frontend/app.py`) — a single page, no sidebar/nav:
  an inline document uploader plus one chat box for everything else.
- **Vector store**: ChromaDB, persisted locally under `storage/chroma_db`, one
  global document set (no project/workspace grouping).

### The supervisor graph (`backend/agent/graphs/supervisor_graph.py`)

One LangGraph `StateGraph` handles every request — Q&A, reports, and
presentations all go through the same `POST /chat`. A planner decides which
downstream agent(s) run:

```
route_urls (regex, no LLM call)
      │
      ▼
   planner  (Gemini structured output: intent=qa|report|presentation, needs_web, needs_docs, ...)
      │
      ├─ qa ──┬─► pdf_agent ──┐
      │       ├─► web_agent ─┤   (only the agents the planner actually
      │       └─► url_agent ─┴─► synthesize_answer ─► END       picks are invoked)
      │
      ├─ report ─► report_plan_outline ─► [pdf_agent/web_agent] ─► report_generate_sections ─► report_export ─► END
      │
      └─ presentation ─► presentation_plan_slides ─► [pdf_agent/web_agent] ─► presentation_generate_slides ─► presentation_build ─► END
```

- **`pdf_agent`** — searches your uploaded/ingested documents (ChromaDB).
- **`web_agent`** — searches the web via Tavily.
- **`url_agent`** — when your message contains a URL, scrapes it, **persists**
  it into the document store (so later questions can reference it too), and
  feeds its content directly into the answer.
- **`report_agent`** / **`presentation_agent`** (the report/presentation node
  chains) — triggered by natural language ("write a summary report on X",
  "make a slide deck about Y"), produce downloadable `.md`/`.docx`/`.pdf` or
  `.pptx` files, and post a short confirmation message in the chat.

The graph is checkpointed with LangGraph's `MemorySaver`, keyed by
`thread_id`, so the whole conversation (across Q&A, reports, and
presentations) shares memory — a follow-up like "make that shorter" has
context from the prior turn. Every agent node degrades gracefully on failure
(e.g. a missing/invalid `TAVILY_API_KEY` just means `web_agent` returns no
results, not a crash) instead of failing the whole request.

### What's intentionally not included

- **OCR / image ingestion** — only PDF, DOCX, TXT, PPTX, and URLs are
  ingestible. (Scanned/image-based PDFs will extract no text.)
- **Workspace/projects** — dropped in favor of one single-page, one global
  document set experience.
- **Auth (Google Login/JWT)** and **Docker/Redis/Celery** infra — omitted to
  keep this runnable locally with a single `pip install`. Rate limiting is
  done in-memory via `slowapi` instead of Redis.

## Setup

1. `pip install -r requirements.txt`
2. One-time browser install for URL scraping's fallback path (only needed
   the first time): `playwright install chromium`. This downloads a
   headless Chromium (~300MB) used when a plain HTTP fetch returns too
   little content — e.g. JS-rendered pages, or sites that serve a
   stripped-down response to non-browser clients.
3. Edit `.env`:
   - `GEMINI_API_KEY` is already set.
   - Replace `TAVILY_API_KEY` with a real key from
     [tavily.com](https://tavily.com) to enable web search — until then, the
     agent will still answer from your uploaded documents only.
   - `LLM_MODEL` and `REPORT_LLM_MODEL` both default to `gemini-2.5-flash-lite`
     — chosen over plain `gemini-2.5-flash` because the free tier's daily
     request cap for `gemini-2.5-flash` (observed: 20/day) is easy to hit
     while testing; `-lite` is a separate model with its own quota bucket
     and a typically more generous free-tier allowance. If you hit a `429
     RESOURCE_EXHAUSTED` error, that's this same kind of daily cap — either
     wait for the reset or switch to yet another model.
     Gemini's **free tier has zero quota for Pro models** (`gemini-2.5-pro`
     etc. return `429 RESOURCE_EXHAUSTED` with `limit: 0`, not a transient
     rate limit) — only switch to a Pro model once your Google AI Studio
     project has billing enabled.
4. Start the backend:
   ```bash
   uvicorn backend.main:app --reload --port 8000
   ```
5. Start the frontend (separate terminal):
   ```bash
   streamlit run frontend/app.py
   ```
6. Open the Streamlit URL it prints (usually http://localhost:8501).

## Running tests

```bash
pytest tests/ -v
```

## Environment variables

See `.env.example` for the full list: Gemini model names, Tavily key,
storage paths, chunk size/overlap, and the in-memory rate limit.
