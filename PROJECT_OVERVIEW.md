# AI Research Assistant — Project Overview

This document explains the project end-to-end: what was built, how it's put
together, and exactly how the multi-agent workflow executes. It's a
companion to [README.md](README.md), which only covers setup/run steps.

**Note on history**: this app was first built with a 5-page Streamlit UI and
three separate LangGraph graphs (one each for chat, report generation, and
presentation generation), each behind its own REST endpoint. It was then
redesigned — on request — into what's described below: one single-page UI
and one multi-agent supervisor graph reachable through a single `POST /chat`
endpoint. Section 9 covers what changed and why.

---

## 1. What this is

A local, single-page research assistant. One chat box handles everything:

- Ask a question about your uploaded documents (PDF / DOCX / TXT / PPTX).
- Paste a URL in your message — it gets scraped, permanently ingested, and
  used to answer, in the same turn.
- Ask something that needs current/web information — it searches the web.
- Ask for a report ("write a literature review on X") or a slide deck
  ("make a presentation about Y") — files are generated and offered as
  downloads right in the chat.
- Conversation memory persists across turns, across all of the above.

A **planner** (one Gemini call per turn) decides which of these paths a
message needs, and routes to the right specialized **agent(s)** — this is
the "multi-agent" part: `pdf_agent`, `web_agent`, `url_agent`, plus the
report/presentation agent chains.

Everything runs locally: FastAPI backend, Streamlit frontend, ChromaDB
vector store (a folder on disk), SQLite for document metadata (a file on
disk). The only external calls are to the Gemini API (LLM + embeddings) and,
optionally, the Tavily API (web search).

---

## 2. Tech stack and why

| Concern | Choice | Why |
|---|---|---|
| LLM + embeddings | **Google Gemini** via `langchain-google-genai` | `gemini-2.5-flash` for planning/chat/report writing, `gemini-embedding-001` for embeddings |
| Agent orchestration | **LangGraph** (one supervisor graph) | Explicit state machine — every step (plan, retrieve, search, write) is a visible, debuggable node, and routing is deterministic code, not an implicit agent loop |
| Vector store | **ChromaDB** (via `langchain-chroma`), persisted to `storage/chroma_db/` | Local, zero-setup, no external DB server |
| Backend | **FastAPI** | Async, plays well with LangGraph's async streaming, auto docs at `/docs` |
| Frontend | **Streamlit** | Single page, `st.chat_input`/`st.chat_message`/`st.write_stream` give a chat UI for free |
| Web search | **Tavily** | Purpose-built search API for LLM agents (returns clean content, not raw HTML) |
| URL scraping | **trafilatura** + **BeautifulSoup**, with a **Playwright** headless-Chromium fallback | Plain HTTP first (fast); real browser rendering only when that comes back thin (JS-heavy or bot-gated pages) |
| Document metadata | **stdlib `sqlite3`** | One small table (documents), no ORM needed |
| Rate limiting | **slowapi** (in-memory) | Redis was explicitly deferred to keep this runnable with a single `pip install` |
| Report export | **python-docx** + **reportlab** | Both pure pip installs (no system Cairo/Pango dependency like weasyprint needs) |
| Presentation export | **python-pptx** | Standard for programmatic .pptx generation |

**Deliberately not included:** OCR/image ingestion, authentication, Docker/
Redis/Celery infra, and (as of the redesign) the Workspace/project grouping
concept — all noted in the README.

---

## 3. Repository layout

```
backend/
  config.py              # pydantic-settings, reads .env
  database.py             # ChromaDB client + LangChain Chroma vector store singleton
  workspace_store.py       # sqlite3: the documents table (metadata for the UI's document list)
  rate_limit.py            # slowapi Limiter shared across routers

  models/schemas.py        # every Pydantic request/response model

  processing/              # ingestion pipeline (no LLM calls here)
    document_loader.py      # PDF/DOCX/TXT/PPTX -> list[LoadedPage]
    table_extractor.py       # pdfplumber -> Markdown tables (merged into PDF pages)
    chunker.py               # RecursiveCharacterTextSplitter -> LangChain Documents
    embedder.py               # Gemini embeddings client (singleton)
    web_scraper.py            # trafilatura/BeautifulSoup -> clean text from a URL

  rag/
    retriever.py             # ingest_chunks(), retrieve(), delete_document()
    prompt_templates.py        # every system prompt + format_context()

  agent/                     # the multi-agent layer — see section 5
    state.py                  # one unified AgentState TypedDict
    tools.py                   # Gemini LLM getters, URL regex extractor, Tavily tool wrapper
    nodes.py                   # every agent/node function
    graphs/supervisor_graph.py  # the one graph wiring them all together

  generators/                # turn agent output into files
    report_generator.py       # .md / .docx / .pdf writers
    pptx_generator.py          # .pptx writer

  api/                       # FastAPI routers
    documents.py               # upload, URL ingest (direct API use), list, delete
    chat.py                     # the single POST /chat SSE endpoint
  main.py                    # app assembly, CORS, rate limiting, router registration

frontend/
  app.py                     # the entire UI: uploader + document list + chat, one page
  utils/api_client.py          # httpx wrapper for every backend endpoint
  utils/ui_helpers.py           # citation rendering, download buttons

storage/                    # everything generated at runtime (gitignored)
  uploads/, chroma_db/, reports/, presentations/, workspace.db
```

---

## 4. Document ingestion pipeline (not a graph — just a pipeline)

This is a plain linear sequence, not LangGraph, because there's no
branching/decision-making involved — every file (or scraped URL) goes
through the same steps:

```
upload (POST /upload) OR a URL detected inside a chat message
   │
   ▼
document_loader.load_document()        # or web_scraper.scrape_url() for URLs
   │  -> list[LoadedPage(text, page_number)]
   ▼
table_extractor.extract_tables_as_markdown()   # PDFs only, merged in as extra "pages"
   ▼
chunker.chunk_pages() / chunk_text()
   │  -> list[langchain_core.documents.Document] with metadata:
   │     {doc_id, source, page, chunk_index}
   ▼
retriever.ingest_chunks()
   │  -> embedder.get_embeddings() embeds each chunk (Gemini, task_type=RETRIEVAL_DOCUMENT)
   │  -> stored in the single Chroma "documents" collection
   ▼
workspace_store.create_document()     # row in the documents SQLite table for the UI list
```

Deletion (`DELETE /documents/{doc_id}`) reverses this: `retriever.delete_document()`
removes all Chroma entries with that `doc_id` via a metadata filter, and
`workspace_store.delete_document_record()` removes the SQLite row.

**How a URL pasted in chat differs from `/upload`**: `url_agent` (section 5)
runs this exact same pipeline (`scrape_url` → `chunk_text` → `ingest_chunks`
→ `workspace_store.create_document`) inline, mid-conversation, so the URL is
permanently searchable afterward — but it *also* keeps the freshly scraped
text directly in that turn's context, so the very question that triggered
the scrape is guaranteed to be answered from it (not dependent on embedding
similarity ranking it highly enough on the first try).

**Scraping, three layers deep** (`web_scraper.scrape_url()`):
1. A plain HTTP fetch (`httpx`) with realistic desktop-browser headers (not
   a bot-like custom User-Agent — some sites serve a stripped-down response
   when they detect a non-browser client).
2. `trafilatura`'s "main article" extraction on that HTML, falling back to a
   fuller plain-text dump (`_full_text()`) if trafilatura's result looks too
   thin (< `MIN_USEFUL_CHARS`, currently 500 chars) — trafilatura's
   heuristics are tuned for articles/blogs and can over-prune non-article
   pages like product grids.
3. If the result is *still* thin after both of the above, falls back to
   `_render_with_browser()` — a real headless Chromium via **Playwright**
   that actually loads the page (runs its JavaScript, waits for network
   idle) before re-running step 2 on the rendered HTML. This is the only
   layer that can see content injected client-side after page load, or get
   past sites that serve bots a different, simpler page than what a real
   browser gets. Requires a one-time `playwright install chromium` (see
   README) — imported lazily so the rest of the app still works if that
   setup step was skipped; the fallback then just silently doesn't fire.

---

## 5. The agentic layer: one multi-agent supervisor graph

**Why one graph with a planner + agents, instead of separate
graphs/endpoints per capability:** the previous design had three separate
graphs behind three separate REST endpoints, and the frontend had to know
which endpoint to call for which kind of request. Moving the decision
*inside* the graph — a `planner` node that a single `/chat` call always goes
through — means the UI only needs one input box and one endpoint; the graph
itself figures out whether a message is a question, a report request, or a
presentation request, and which sources (docs/web/URL) it needs.

### 5.1 The graph (`backend/agent/graphs/supervisor_graph.py`)

```
route_urls (regex, no LLM)
      │
      ▼
   planner  (Gemini structured output: intent, needs_docs, needs_web, report_type, num_slides)
      │
      ├─ intent="qa" ──┬─► pdf_agent ──┐
      │                ├─► web_agent ─┤   only the agents the planner
      │                └─► url_agent ─┴─► synthesize_answer ─► END   actually selected run
      │
      ├─ intent="report" ─► report_plan_outline ─┬─► pdf_agent ─┐
      │                                           └─► web_agent ┴─► report_generate_sections ─► report_export ─► END
      │
      └─ intent="presentation" ─► presentation_plan_slides ─┬─► pdf_agent ─┐
                                                              └─► web_agent ┴─► presentation_generate_slides ─► presentation_build ─► END
```

Every node function lives in `backend/agent/nodes.py` and returns a
**partial state update** (a dict) that LangGraph merges into one shared
`AgentState` (`backend/agent/state.py`) — a single `TypedDict` covering every
field any branch might need (rather than three separate state schemas like
before), since all three intents now share the same graph run.

**Dynamic fan-out**: routing uses `add_conditional_edges(source, fn, [...])`
where `fn` returns a **list** of destination node names — LangGraph's
standard mechanism for fanning out to a variable subset of nodes. For
example, `_route_after_planning` returns `["pdf_agent", "web_agent"]` if the
planner wants both docs and web but no URL was found, or just `["url_agent"]`
if the message was only a URL. Only the returned nodes actually run — and
LangGraph's join at the downstream node (`synthesize_answer`,
`report_generate_sections`, etc.) correctly waits only for whichever
upstream nodes were actually scheduled that turn, not for every node that's
*statically* connected to it.

### 5.2 Routing and planning nodes

- **`route_urls`** — pure regex (`agent.tools.extract_urls`), no LLM call.
  Extracts and dedupes `http(s)://` URLs from the message text. Deterministic
  and free — saves a Gemini call versus asking the model to find URLs.
- **`planner`** — one structured-output Gemini call
  (`.with_structured_output()` forces the response into a Pydantic schema,
  not parsed from free text) that decides, in a single shot:
  - `intent`: `"qa"`, `"report"`, or `"presentation"`
  - `needs_docs` / `needs_web`: whether to search documents/the web
  - `report_type` / `num_slides`: parameters used only if intent matches
  It's told whether any documents exist at all (`workspace_store.list_documents()`)
  and what URLs were detected, so it can reason about e.g. "a URL was found,
  so needs_web should usually be false."

### 5.3 The three agents behind `intent="qa"`

- **`pdf_agent`** (searches uploaded/ingested documents) — a no-op returning
  `{"retrieved_chunks": []}` unless `needs_docs` is true, otherwise calls
  `rag.retriever.retrieve()`. Uses a higher `k` (10 vs. 5) when the intent is
  actually `report`/`presentation` (broader context for longer output),
  since this same node is reused by those branches too.
- **`web_agent`** (searches the web) — no-op unless `needs_web` is true,
  otherwise calls `agent.tools.web_search_tool()`, which itself returns `[]`
  silently if `TAVILY_API_KEY` is missing/invalid/rate-limited — so a bad or
  absent Tavily key degrades gracefully instead of failing the request.
- **`url_agent`** (handles a URL pasted in the message) — for each detected
  URL: scrapes it, persists it via the same ingestion pipeline as `/upload`
  (see section 4), and also returns the raw scraped text directly as
  `url_context` so this turn's answer is guaranteed to use it.

All three converge on **`synthesize_answer`**, which builds one context
string from `retrieved_chunks` + `web_results` + `url_context`
(`prompt_templates.format_context()`, labeling every source with a citation
tag like `[paper.pdf | Page 3]`, `[Web: Article Title]`, or `[Page Title]`
for a URL), then streams a Gemini completion instructed to cite inline using
those exact tags. It appends the turn to `messages` for conversation memory
and returns a structured `citations` list built independently of what the
model actually cited (so the UI's citation list doesn't depend on the LLM
citing correctly).

### 5.4 The report and presentation agents

Triggered when the planner sets `intent="report"` or `intent="presentation"`
— i.e., the user asked in natural language ("write a report on...", "make a
slide deck about..."). Each is a short chain of nodes rather than a single
function, mirroring the structure used for `qa`:

- **Report**: `report_plan_outline` (structured output: title + section
  list, adapted to `report_type`) → fan-out to `pdf_agent`/`web_agent` (same
  shared nodes as `qa`, just routed here instead of to `synthesize_answer`)
  → `report_generate_sections` (one Gemini call per section, all sharing the
  same retrieved context) → `report_export` (no LLM call — hands everything
  to `generators/report_generator.py`, which writes `.md`/`.docx`/`.pdf` to
  `storage/reports/`).
- **Presentation**: same shape — `presentation_plan_slides` → fan-out →
  `presentation_generate_slides` (one call per content slide; Title/Agenda/
  References slides are built from data, not generated) →
  `presentation_build` (no LLM call — `generators/pptx_generator.py` writes
  `.pptx` to `storage/presentations/`).

Both terminal nodes (`report_export`, `presentation_build`) also compose a
short **templated, non-LLM** confirmation string (e.g. `"I've generated your
summary report on 'X'. Download it below."`) as the turn's `answer`, and
append it to `messages` — so later turns in the same conversation ("make it
shorter") have context, and the single chat UI always has something to
display even though these branches don't stream token-by-token like `qa`
does.

### 5.5 Memory and streaming

- **Memory**: the graph is compiled with LangGraph's `MemorySaver`
  checkpointer, keyed by `thread_id` (one per browser conversation).
  `AgentState.messages` is `Annotated[list, add_messages]` — a reducer that
  appends rather than overwrites, so every turn's `HumanMessage`/`AIMessage`
  accumulate. This is shared across `qa`/`report`/`presentation` turns in
  the *same* conversation, since it's all one graph now.
- **Streaming**: `POST /chat` (`backend/api/chat.py`) calls
  `graph.astream_events(..., version="v2")` and filters the event stream:
  - `on_chat_model_stream` events tagged `langgraph_node == "synthesize_answer"`
    are forwarded token-by-token as SSE `token` events (only the `qa` path
    streams live text — report/presentation confirmations arrive whole in
    the final event).
  - `on_chain_end` events from `synthesize_answer` / `report_export` /
    `presentation_build` (whichever one actually ran) populate the final SSE
    `done` event's `answer`, `citations`, and any `markdown_path`/`docx_path`/
    `pdf_path`/`pptx_path`. Each handler checks `isinstance(output, dict)`
    before reading fields off it — a node's *internal* LLM call also emits
    an `on_chain_end` tagged with the same node name, but its `output` is a
    raw `AIMessage`, not the dict the node function returns; this check
    avoids crashing on that mismatch (a real bug hit and fixed during
    development — see section 9).

### 5.6 Retry handling

Both `get_chat_llm()` and `get_report_llm()` in `agent/tools.py` return the
**raw** `ChatGoogleGenerativeAI` model (no retry wrapper baked in). Retry is
applied at each call site via `tools.with_retry(runnable)`, which wraps
*whatever* runnable is passed — either the plain model (for `.invoke()`
calls) or a `.with_structured_output(...)` chain (for `planner` and the
outline/slide-plan nodes). This split exists because `.with_retry()`'s
return type (`RunnableRetry`) doesn't expose `.with_structured_output()` —
seen firsthand during development (section 9).

---

## 6. RAG layer details

- **Embeddings** (`processing/embedder.py`): a single cached
  `GoogleGenerativeAIEmbeddings` instance, model `gemini-embedding-001`.
  Deliberately *not* given an explicit `task_type` — the library defaults to
  `RETRIEVAL_DOCUMENT` for `embed_documents()` (used when ingesting) and
  `RETRIEVAL_QUERY` for `embed_query()` (used when searching).
- **Vector store** (`database.py`): one Chroma collection (`"documents"`)
  for everything, no per-project scoping (dropped in the redesign — see
  section 9). Optional `doc_ids` filtering still exists in
  `rag/retriever.retrieve()` for API flexibility, though the current UI
  doesn't expose a document filter.
- **Relevance threshold**: `retrieve()` drops any chunk scoring below
  `MIN_RAG_RELEVANCE_SCORE` (`.env`, default `0.5`) after the similarity
  search — without this, `similarity_search_with_relevance_scores(k=...)`
  always returns its top-`k` *closest* results even when nothing in the
  store is actually relevant, which surfaced as unrelated documents showing
  up as citations for a completely unrelated question (see section 10).
- **Citations end-to-end**: `prompt_templates.format_context()` labels every
  chunk/web result/URL with its citation tag before it ever reaches the LLM,
  the LLM is instructed to reuse those exact tags inline, and
  `nodes._build_citations()` independently builds the structured `citations`
  list returned to the frontend.

---

## 7. API surface

| Method & path | Purpose |
|---|---|
| `POST /upload` | Ingest a document file (PDF/DOCX/TXT/PPTX) |
| `POST /documents/ingest-url` | Ingest a URL directly (the chat UI instead uses `url_agent`, which calls the same underlying pipeline inline) |
| `GET /documents`, `DELETE /documents/{doc_id}` | List / delete documents |
| `POST /chat` (SSE stream) | **The single entry point for everything** — Q&A, reports, and presentations. Runs the supervisor graph; the planner inside it decides the rest. |
| `GET /health` | Liveness check |

Both routers are rate-limited via a shared `slowapi.Limiter` (`rate_limit.py`,
30/minute default). The standalone `/generate-report`, `/generate-presentation`,
`/web-search`, and `/projects` endpoints from the earlier design were
retired — everything now goes through `/chat`.

---

## 8. Frontend (Streamlit) — one page

`frontend/app.py` is the entire UI: no `pages/` directory, no multi-page
nav. There *is* a sidebar, but it holds only conversation history (see
below) — not the old app's page navigation or project selector.

1. **Sidebar** — `st.session_state.conversations` is a dict of
   `{thread_id: {"title": ..., "messages": [...]}}`. The sidebar lists all
   of them (titled from each conversation's first message) with a
   "➕ New conversation" button on top; clicking any past conversation
   switches `active_thread_id` and instantly shows its full history. This
   only lives in the browser session's `st.session_state` — no backend
   persistence — so it resets if the Streamlit process restarts (the same
   limitation `MemorySaver` already has on the backend side, see 5.5).
2. An inline, collapsible uploader (PDF/DOCX/TXT/PPTX) with a document list
   (delete button per row) — still needed since `pdf_agent` needs something
   to search.
3. Chat history for the *active* conversation (`st.chat_message` per turn)
   with citations (`render_citations()`) and, when present, inline download
   buttons (`render_downloads()`) for any `.md`/`.docx`/`.pdf`/`.pptx` files
   that turn produced.
4. A single `st.chat_input()` at the bottom — the only way to interact.
   Streaming uses `st.write_stream()` (wrapped in `st.spinner("Thinking...")`
   so there's visible feedback the instant a message is sent) over
   `api_client.chat_stream()`, which manually parses the backend's SSE
   frames (`event: token` / `event: done`) since Streamlit has no native SSE
   client. For non-streamed turns (report/presentation confirmations), the
   UI falls back to displaying the `done` event's `answer` text directly
   since no `token` events were emitted — the spinner covers that entire
   wait too, which is exactly where it's most useful.

Download buttons read files straight off disk (`utils/ui_helpers.download_file_button`)
rather than through a dedicated file-serving endpoint, since frontend and
backend run on the same machine locally.

---

## 9. The redesign: what changed and why

The app was originally built with 3 separate LangGraph graphs (one each for
chat, report, presentation) behind 3 separate REST endpoints, and a 5-page
Streamlit UI (Documents / Research / Web Search / Reports / Workspace) with
sidebar navigation and a "project" grouping concept for documents.

On request, it was redesigned into the single-page, single-graph,
multi-agent version described above. Concretely:

- **3 graphs → 1 graph**: `chat_graph.py`/`report_graph.py`/`presentation_graph.py`
  were deleted; `supervisor_graph.py` replaces all three, with a `planner`
  node (inserted after URL routing) deciding which path a message takes.
- **Nodes reframed as agents**: `rag_retrieve`/`classify_intent`/`generate_answer`
  etc. were renamed to `pdf_agent`/`planner`/`synthesize_answer`, and a new
  **`url_agent`** was added to handle URLs pasted directly into chat
  messages (previously, URL ingestion was a separate manual form on the Web
  Search page).
- **5 pages → 1 page**: `frontend/pages/` was deleted entirely;
  `frontend/app.py` became the whole UI.
- **Workspace/projects dropped**: `project_id` was removed from every layer
  (schemas, retriever filtering, SQLite table, ingestion endpoints) — one
  single global document set now, no grouping UI.
- **Report/presentation retired as standalone endpoints**: `/generate-report`,
  `/generate-presentation`, `/web-search`, and `/projects` were deleted;
  their functionality now lives entirely behind `/chat`, triggered by
  natural language and routed there by the planner.
- **Conversation memory widened**: previously only the chat graph had
  `MemorySaver`; now the single shared graph means report/presentation turns
  also get a message appended (a templated confirmation string, not the full
  report text) so a follow-up in the same conversation has context.

---

## 10. Things we hit and fixed during development

Documented here because they're useful context for anyone extending this,
not because they're still bugs:

1. **Dependency resolution**: hard-pinning exact versions across the
   LangChain/LangGraph/Chroma package family caused cascading
   `ResolutionImpossible` errors, because those packages cross-pin each
   other's versions internally and move fast. Fixed by using floor-only
   (`>=`) constraints for that cluster in `requirements.txt`.
2. **`RunnableRetry` has no `.with_structured_output()`**: see section 5.6.
3. **SSE handler crash on `AIMessage`**: an `on_chain_end` event from a
   node's *internal* LLM call carries the same `langgraph_node` tag as the
   node's own completion event, but a different `output` type — see 5.5.
4. **Gemini free-tier quotas**: `gemini-2.5-pro` has **zero** free-tier
   quota — `REPORT_LLM_MODEL` was switched to `gemini-2.5-flash`. Separately,
   the free tier caps `gemini-2.5-flash` at a low **daily** request count
   (observed: 20/day) — an account-level cap, not something the code can
   work around; the planner's single-call design (folding intent
   classification and parameter extraction into one Gemini call) helps
   conserve this budget.
5. **Tavily key placeholder**: until a real `TAVILY_API_KEY` is set,
   `web_search_tool()` returns `[]` by design (checked via a
   `startswith("tvly-REPLACE")` guard) rather than crashing.
6. **Irrelevant RAG citations**: pasting a URL and asking about it was also
   pulling in unrelated chunks from the user's own unrelated documents,
   because (a) the planner defaulted `needs_docs=true` even when the URL
   was clearly the sole intended source, and (b) `retrieve()` had no
   relevance floor, so it always returned its top-`k` closest matches even
   when none were actually relevant. Fixed both: the planner prompt now
   defaults `needs_docs=false` when a URL is the query's clear subject (see
   5.2), and `MIN_RAG_RELEVANCE_SCORE` filters out low-scoring chunks (see
   section 6).
7. **Product prices missing from scraped pages**: asking about pricing on
   an Apple Store page returned "no prices found," even though the prices
   were visibly present in a real browser — pointing to either JS-rendered
   content or the server serving scrapers a different, simpler page than
   real browsers get (both are extremely common on large e-commerce sites).
   Fixed in two steps: (1) replaced the scraper's bot-like custom User-Agent
   with realistic browser headers, and (2) added a Playwright headless-
   browser fallback that actually renders the page when a plain HTTP fetch
   comes back thin — see section 4's "Scraping, three layers deep."

---

## 11. Running it

See [README.md](README.md) for the actual commands. In short:
`pip install -r requirements.txt` → `uvicorn backend.main:app --reload --port 8000`
→ `streamlit run frontend/app.py` (separate terminal) → open the Streamlit
URL.
