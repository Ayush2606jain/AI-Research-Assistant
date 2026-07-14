# Code Explained — File by File, Block by Block

This is the most detailed of the three docs. For each file: **why it
exists** first, then **what each block of code actually does**, explained
in plain language (no assuming you already know Python deeply). Read
[HOW_IT_WORKS.md](HOW_IT_WORKS.md) first if you haven't — it gives you the
big picture and vocabulary this document builds on.

---

## `backend/config.py`

**Why it exists:** every other file needs settings like "what's my Gemini
API key" or "how big can an uploaded file be." Instead of scattering
`os.environ["..."]` calls everywhere, this file reads `.env` once into a
single, typed object that the rest of the app imports.

**Code walkthrough:**

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )
```
This declares a `Settings` "form" — `BaseSettings` (from the `pydantic-settings`
library) knows how to automatically fill in each field below from your
`.env` file, matching by name (e.g. `GEMINI_API_KEY` in `.env` → `gemini_api_key`
here).

```python
    gemini_api_key: str
    llm_model: str = "gemini-2.5-flash-lite"
    report_llm_model: str = "gemini-2.5-flash-lite"
    embedding_model: str = "gemini-embedding-001"
    tavily_api_key: str = ""
    chroma_db_path: str = "./storage/chroma_db"
    ...
    min_rag_relevance_score: float = 0.5
```
Each line is one setting: a name, its type, and (if given) a default value
used when `.env` doesn't set it. `gemini_api_key` has no default — the app
refuses to start without one, which is intentional (there's no sensible
fallback for "no API key").

```python
    def resolved_path(self, relative: str) -> Path:
        path = Path(relative)
        if not path.is_absolute():
            path = BASE_DIR / path
        path.mkdir(parents=True, exist_ok=True)
        return path
```
A little helper: given something like `"./storage/reports"`, turn it into a
real, absolute folder path *and create that folder if it doesn't exist yet*
— so nothing else in the codebase has to remember to do that.

```python
@lru_cache
def get_settings() -> Settings:
    return Settings()
```
`@lru_cache` means "only build this once, then reuse it" — every file that
calls `get_settings()` gets the exact same already-loaded settings object
instead of re-reading `.env` every time.

---

## `backend/database.py`

**Why it exists:** sets up the vector database (ChromaDB) — the place where
every document chunk's "meaning as numbers" (its embedding) gets stored so
it can be searched later.

**Code walkthrough:**

```python
@lru_cache
def get_chroma_client() -> chromadb.ClientAPI:
    settings = get_settings()
    path = settings.resolved_path(settings.chroma_db_path)
    return chromadb.PersistentClient(path=str(path))
```
Creates one connection to a ChromaDB database that lives as files on disk
(under `storage/chroma_db/`) — "persistent" means it survives you restarting
the app, unlike an in-memory database that would forget everything.

```python
@lru_cache
def get_vector_store() -> Chroma:
    return Chroma(
        client=get_chroma_client(),
        collection_name=DOCUMENTS_COLLECTION,
        embedding_function=get_embeddings(),
    )
```
Wraps the raw ChromaDB connection in LangChain's `Chroma` helper class,
telling it *which* embedding function to use whenever it needs to convert
text into numbers (see `embedder.py`). Everything is stored in one single
"collection" (think: one big table) named `"documents"` — there's no
separate database per user or project.

---

## `backend/workspace_store.py`

**Why it exists:** the vector database is great for *searching* text, but
bad for simple questions like "what documents do I have, and when did I add
them?" This file keeps that simple bookkeeping in a tiny SQLite database (a
single file on disk, no server needed).

**Code walkthrough:**

```python
@contextmanager
def _connection():
    conn = sqlite3.connect(get_settings().workspace_db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
```
A reusable "open the database, do something, then always close it
properly" wrapper — used by every function below via `with _connection() as conn:`,
so nobody has to remember to open/close/commit by hand each time.

```python
def init_db() -> None:
    ...
    conn.execute(
        """CREATE TABLE IF NOT EXISTS documents (
            doc_id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            doc_type TEXT NOT NULL,
            num_chunks INTEGER NOT NULL,
            uploaded_at TEXT NOT NULL
        )"""
    )
```
Creates one table, `documents`, if it doesn't already exist — one row per
uploaded file or ingested URL, storing its id, name, type, how many chunks
it was split into, and when it was added. Runs once when the backend starts.

```python
def create_document(doc_id, filename, doc_type, num_chunks) -> dict:
    ...
def list_documents() -> list[dict]:
    ...
def delete_document_record(doc_id) -> bool:
    ...
```
The three operations the rest of the app needs: add a row, list all rows
(newest first), and remove a row by id. Nothing fancier than basic
insert/select/delete SQL.

---

## `backend/rate_limit.py`

**Why it exists:** a one-line safety net so nobody (accidentally or on
purpose) can hammer the API with requests fast enough to run up your Gemini
bill or overload the server.

```python
limiter = Limiter(key_func=get_remote_address, default_limits=[f"{get_settings().rate_limit_per_minute}/minute"])
```
Creates one shared `Limiter` object (from the `slowapi` library) that caps
each visitor (identified by their IP address, via `get_remote_address`) to a
certain number of requests per minute (30 by default, from `.env`). This
object gets attached to the FastAPI app in `main.py` and used as a decorator
on individual endpoints in `chat.py`.

---

## `backend/models/schemas.py`

**Why it exists:** defines the *exact shape* of every piece of data flowing
in and out of the API — like a contract. FastAPI uses these to auto-validate
incoming requests (rejecting malformed ones automatically) and to generate
the `/docs` page.

**Code walkthrough:** each `class ... (BaseModel):` block is one data shape.
For example:

```python
class ChatRequest(BaseModel):
    query: str
    thread_id: str = Field(default="default", description="Conversation/session id for memory")
    doc_ids: Optional[list[str]] = None
```
This says: "a chat request must have a `query` (text), may include a
`thread_id` (defaults to `"default"` if not given), and may optionally
restrict the search to specific `doc_ids`." If a request is missing `query`
or sends the wrong type, FastAPI rejects it before your code even runs.

```python
class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = []
    used_rag: bool = False
    used_web_search: bool = False
    markdown_path: Optional[str] = None
    docx_path: Optional[str] = None
    pdf_path: Optional[str] = None
    pptx_path: Optional[str] = None
```
The shape of what comes back from a chat turn — always has an `answer` and
a list of `citations`; the four `*_path` fields are only filled in when that
turn produced a report or presentation file.

The other classes (`DocumentMeta`, `UploadResponse`, `UrlIngestRequest`,
`DeleteResponse`, `Citation`) follow the same pattern for their respective
endpoints.

---

## `backend/processing/document_loader.py`

**Why it exists:** PDFs, Word docs, text files, and PowerPoint files are all
completely different binary formats. This file is the single place that
knows how to open each one and pull out its plain text.

**Code walkthrough:**

```python
@dataclass
class LoadedPage:
    text: str
    page: int | None = None
```
A tiny container: "here's some text, and optionally which page number it
came from" (page numbers only make sense for PDFs/slides, hence `| None`).

```python
def load_document(file_path: str) -> list[LoadedPage]:
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return _load_pdf(file_path)
    if ext == ".docx":
        return _load_docx(file_path)
    ...
    raise ValueError(...)
```
The single entry point — looks at the file extension and hands off to the
matching private helper below. Unsupported extensions raise an error
immediately (caught upstream in `api/documents.py` and turned into a clean
error message).

```python
def _load_pdf(file_path: str) -> list[LoadedPage]:
    pages_md = pymupdf4llm.to_markdown(file_path, page_chunks=True)
    pages = [LoadedPage(text=page["text"], page=...) for i, page in enumerate(pages_md) if page.get("text", "").strip()]
    for table in extract_tables_as_markdown(file_path):
        pages.append(LoadedPage(text=table["markdown"], page=table["page"]))
    return pages
```
Uses the `pymupdf4llm` library to convert each PDF page into clean Markdown
text (it's specifically built for feeding PDFs to AI models). Then
separately runs `table_extractor.py` to pull out any tables and appends them
as extra "pages," so a table's data isn't lost inside a wall of paragraph
text.

```python
def _load_docx(file_path: str) -> list[LoadedPage]:
    doc = DocxDocument(file_path)
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    for table in doc.tables:
        rows = [...]
        text += "\n\n" + "\n".join(rows)
    return [LoadedPage(text=text, page=None)] if text.strip() else []
```
Word documents don't have a clean concept of "pages" in their file format,
so this joins every paragraph into one block of text (plus any tables,
converted into simple `| cell | cell |` rows), returned as a single page
with no page number.

```python
def _load_txt(file_path: str) -> list[LoadedPage]:
    text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
    return [LoadedPage(text=text, page=None)] if text.strip() else []
```
The simplest case — just read the whole text file as-is.

```python
def _load_pptx(file_path: str) -> list[LoadedPage]:
    prs = Presentation(file_path)
    ...
    for i, slide in enumerate(prs.slides, start=1):
        texts = [shape.text_frame.text for shape in slide.shapes if shape.has_text_frame and ...]
        if texts:
            pages.append(LoadedPage(text="\n".join(texts), page=i))
    return pages
```
Loops through every slide, collects the text out of every text box on it,
and treats each slide as one "page" (so citations can say "Slide 4," not
just the file name).

---

## `backend/processing/table_extractor.py`

**Why it exists:** a helper used only by the PDF loader above — specifically
finds tables (rows/columns of data) inside a PDF and turns them into
Markdown, since plain paragraph-style extraction would otherwise mangle
tabular data into an unreadable jumble.

```python
def extract_tables_as_markdown(pdf_path: str) -> list[dict]:
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue
                markdown = _table_to_markdown(table)
                if markdown:
                    tables.append({"page": page_number, "markdown": markdown})
    return tables
```
Uses the `pdfplumber` library (which is specifically good at detecting
table structure) to find every table on every page. Skips anything with
fewer than 2 rows (a "table" with just a header and no data isn't useful).

```python
def _table_to_markdown(rows) -> str:
    cleaned = [[cell.strip() if cell else "" for cell in row] for row in rows]
    header, *body = cleaned
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * len(header)) + " |"]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)
```
Converts a raw grid of cells into a Markdown table — the first row becomes
the header, the second line is the `|---|---|` divider Markdown tables
require, and every remaining row becomes a data row. This is exactly the
same table format an AI model reads comfortably.

---

## `backend/processing/chunker.py`

**Why it exists:** a whole document is too big to search efficiently or feed
entirely to the AI every time. This file cuts text into smaller overlapping
pieces ("chunks") — the actual unit that gets embedded, stored, and
retrieved.

```python
def _splitter() -> RecursiveCharacterTextSplitter:
    settings = get_settings()
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
```
Builds LangChain's standard text splitter. It tries to cut at paragraph
breaks first, then line breaks, then sentence ends, then spaces — only
cutting mid-word as an absolute last resort. `chunk_overlap` means
consecutive chunks share a little text at the boundary, so a sentence that
would otherwise get split in half still has full context somewhere.

```python
def chunk_pages(pages: list, base_metadata: dict) -> list[Document]:
    splitter = _splitter()
    chunks = []
    chunk_index = 0
    for page in pages:
        for piece in splitter.split_text(page.text):
            if not piece.strip():
                continue
            metadata = {**base_metadata, "page": page.page, "chunk_index": chunk_index}
            chunks.append(Document(page_content=piece, metadata=metadata))
            chunk_index += 1
    return chunks
```
Takes the `LoadedPage` list from `document_loader.py`, splits each page's
text into pieces, and wraps each piece in a LangChain `Document` object —
which is just "some text" plus a dictionary of `metadata` tags (which
document it came from, which page, its position). This metadata is what
later lets a citation say exactly where a fact came from.

```python
def chunk_text(text: str, base_metadata: dict) -> list[Document]:
    ...
```
The same idea, but for a single block of text with no page structure —
used for scraped web pages, where there's no concept of "pages."

---

## `backend/processing/embedder.py`

**Why it exists:** the one place that knows how to turn text into
"embeddings" (lists of numbers representing meaning), using Google's Gemini
embedding model.

```python
@lru_cache
def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    settings = get_settings()
    return GoogleGenerativeAIEmbeddings(
        model=settings.embedding_model,
        google_api_key=settings.gemini_api_key,
    )
```
Creates one shared embeddings client. Deliberately doesn't specify a
"task_type" — the library automatically uses a slightly different embedding
style for storing documents (`RETRIEVAL_DOCUMENT`) versus for searching with
a question (`RETRIEVAL_QUERY`), which measurably improves search quality
over treating both the same way.

---

## `backend/processing/web_scraper.py`

**Why it exists:** turns a raw URL into clean, readable text — the one place
the `url_agent` (and the direct `/documents/ingest-url` endpoint) goes to
"read" a web page.

```python
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,...",
    "Accept-Language": "en-US,en;q=0.9",
}
```
A set of request headers that make our scraper *look like* a real Chrome
browser instead of an obvious script — some websites serve a different,
simpler page to visitors that don't look like a real browser.

```python
def scrape_url(url: str) -> dict:
    text, title = "", url
    try:
        response = httpx.get(url, headers=REQUEST_HEADERS, timeout=20.0, follow_redirects=True)
        response.raise_for_status()
        text, title = _extract(response.text, url)
    except httpx.HTTPError:
        pass

    if len(text.strip()) < MIN_USEFUL_CHARS:
        try:
            rendered_html = _render_with_browser(url)
            rendered_text, rendered_title = _extract(rendered_html, url)
            if len(rendered_text.strip()) > len(text.strip()):
                text, title = rendered_text, rendered_title
        except Exception:
            pass

    if not text.strip():
        raise WebScrapeError(f"No extractable text content found at {url}")
    return {"title": title, "text": text}
```
The main function, in three steps:
1. Try a fast, plain HTTP request first (no real browser needed).
2. If that came back thin (less than `MIN_USEFUL_CHARS` = 500 characters of
   useful text), it's a sign the page needs a real browser to render
   properly — so open one with Playwright and try again, keeping whichever
   result is actually longer/better.
3. If we still have nothing useful after both attempts, give up with a
   clear error rather than silently returning garbage.

```python
def _extract(html: str, url: str) -> tuple[str, str]:
    text = trafilatura.extract(html, include_tables=True, include_links=False) or ""
    title = _extract_title(html) or url
    if len(text.strip()) < MIN_USEFUL_CHARS:
        fallback_text = _full_text(html)
        if len(fallback_text.strip()) > len(text.strip()):
            text = fallback_text
    return text, title
```
Given raw HTML, first tries `trafilatura` — a library specifically built to
pull out "the main article" from a page and throw away ads/navigation/
clutter. If that comes back too short (common on pages that aren't shaped
like an article, e.g. a product grid), falls back to a much simpler "grab
literally all the visible text" approach instead.

```python
def _render_with_browser(url: str) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=REQUEST_HEADERS["User-Agent"])
            page.goto(url, wait_until="networkidle", timeout=20000)
            html = page.content()
        finally:
            browser.close()
    return html
```
Opens an actual, invisible ("headless") Chrome browser, navigates to the
URL, waits until the page's network activity settles down (meaning it's
probably done loading its dynamic content), then grabs the fully-rendered
HTML — the same HTML a human would see if they opened dev tools. The
`import` is placed *inside* the function on purpose: if you haven't run
`playwright install chromium` yet, this specific fallback just fails
quietly (caught by the `except Exception: pass` in `scrape_url`) instead of
crashing the whole app on startup.

```python
def _full_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)
```
A blunt-instrument fallback: parse the HTML, delete script/style/nav/footer/
header tags (clutter that isn't real content), and return whatever text is
left.

```python
def _extract_title(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return None
```
Just reads the page's `<title>` tag — used as the citation label for that
URL.

---

## `backend/rag/retriever.py`

**Why it exists:** the actual "save this to the vector database" and "find
the closest matches to this question" logic — the core of the RAG system.

```python
@dataclass
class RetrievedChunk:
    text: str
    source: str
    doc_id: str | None
    page: int | None
    score: float

    def citation_label(self) -> str:
        return f"{self.source}" + (f" | Page {self.page}" if self.page else "")
```
A container for one search result: its text, which document it's from, an
optional page number, and a relevance `score`. `citation_label()` builds the
human-readable tag (e.g. `"paper.pdf | Page 3"`) used in prompts and the UI.

```python
def ingest_chunks(chunks: list[Document]) -> int:
    if not chunks:
        return 0
    ids = [f"{chunk.metadata.get('doc_id', 'doc')}_{chunk.metadata.get('chunk_index', i)}_{uuid.uuid4().hex[:8]}" for i, chunk in enumerate(chunks)]
    get_vector_store().add_documents(chunks, ids=ids)
    return len(chunks)
```
Saves a batch of chunks into ChromaDB. Each chunk gets a unique id built
from its document id + position + a random suffix (guaranteeing no two
chunks ever accidentally overwrite each other).

```python
def retrieve(query: str, k: int = 5, doc_ids: list[str] | None = None) -> list[RetrievedChunk]:
    where = {"doc_id": {"$in": doc_ids}} if doc_ids else None
    results = get_vector_store().similarity_search_with_relevance_scores(query, k=k, filter=where)
    min_score = get_settings().min_rag_relevance_score
    return [
        RetrievedChunk(...)
        for doc, score in results
        if score >= min_score
    ]
```
The actual search: turns `query` into an embedding behind the scenes, finds
the `k` closest-matching stored chunks, optionally restricted to specific
`doc_ids`, and — importantly — **throws away anything below
`min_rag_relevance_score`** (default 0.5). Without that last filter, a
similarity search always returns its *closest* results even when nothing in
the store is genuinely relevant, which is exactly the bug that caused
unrelated documents to show up as citations for an unrelated question (now
fixed by this line).

```python
def delete_document(doc_id: str) -> None:
    get_vector_store().delete(where={"doc_id": doc_id})
```
Removes every chunk belonging to one document from the vector database —
used when you click delete on a document in the UI.

---

## `backend/rag/prompt_templates.py`

**Why it exists:** every instruction given to the AI lives here, in one
place, instead of scattered as string literals throughout the agent code.
Think of these as the exact "scripts" each agent reads from.

- **`PLANNER_SYSTEM`** — instructions for the planner: decide `intent`
  (question/report/presentation), `needs_docs`, `needs_web`, plus
  `report_type`/`num_slides` when relevant. Includes explicit guidance for
  the URL case: *"if there's a URL and the question is clearly about it,
  don't also search unrelated documents or the web."*
- **`RAG_ANSWER_SYSTEM`** — used when we *do* have retrieved context: "answer
  only from what's given below, cite everything, admit when it's not
  enough."
- **`GENERAL_ANSWER_SYSTEM`** — used when there's *no* context at all (a
  greeting, or a question nothing needed retrieval for): "just answer
  normally from your own knowledge, don't refuse just because there's no
  context." (This is the fix for the "Hello" → "I cannot answer" bug.)
- **`REPORT_OUTLINE_SYSTEM`** / **`REPORT_SECTION_SYSTEM`** — planning a
  report's section list, then writing one section at a time.
- **`SLIDE_OUTLINE_SYSTEM`** / **`SLIDE_CONTENT_SYSTEM`** — same idea, for a
  slide deck's titles, then each slide's bullet points.

```python
def format_context(chunks: list, web_results: list, url_context: list[dict] | None = None) -> str:
    parts = []
    for chunk in chunks:
        label = f"[{chunk.citation_label()}]"
        parts.append(f"{label}\n{chunk.text}")
    for result in web_results:
        label = f"[Web: {result.get('title', ...)}]"
        parts.append(f"{label}\n{result.get('content', '')}")
    for entry in url_context or []:
        label = f"[{entry.get('title', ...)}]"
        parts.append(f"{label}\n{entry.get('text', '')}")
    return "\n\n---\n\n".join(parts) if parts else "(no context retrieved)"
```
Takes whatever the document/web/URL agents found and stitches it into one
big text blob to hand the AI — each piece labeled with a bracketed tag
(`[paper.pdf | Page 3]`, `[Web: Article Title]`, `[Page Title]`) that the AI
is instructed to reuse exactly when citing that fact.

---

## `backend/agent/state.py`

**Why it exists:** defines exactly what information is available to pass
between agents during one conversation turn — think of it as a shared
clipboard everyone can read from and write to.

```python
class AgentState(TypedDict, total=False):
    query: str
    thread_id: str
    doc_ids: Optional[list[str]]
    messages: Annotated[list, add_messages]
    detected_urls: list[str]
    intent: str
    needs_web: bool
    needs_docs: bool
    retrieved_chunks: list[Any]
    web_results: list[dict]
    url_context: list[dict]
    answer: str
    citations: list[dict]
    report_type: str
    title: str
    outline: list[str]
    sections: dict[str, str]
    ...
```
One single "shape" covering every field any agent might need, across all
three kinds of requests (question/report/presentation) — since they all run
through the same graph now. `total=False` means no field is mandatory (each
agent only fills in the ones relevant to its job). The one special field is
`messages: Annotated[list, add_messages]` — that `add_messages` tag tells
LangGraph "when an agent returns a new message, *append* it to the existing
list instead of replacing it," which is exactly what gives the conversation
its memory across turns.

---

## `backend/agent/tools.py`

**Why it exists:** small, shared building blocks that multiple agents need —
connecting to Gemini, connecting to Tavily, and finding URLs in text.

```python
_URL_PATTERN = re.compile(r"https?://[^\s<>\"')\]]+")

def extract_urls(text: str) -> list[str]:
    seen = []
    for match in _URL_PATTERN.findall(text):
        url = match.rstrip(".,;:!?")
        if url not in seen:
            seen.append(url)
    return seen
```
A regular expression ("pattern matcher") that scans text for anything
starting with `http://` or `https://`. Strips trailing punctuation (so
"visit https://x.com." doesn't accidentally capture the period), and skips
duplicates. This runs with **no AI call at all** — pure, fast, free pattern
matching.

```python
@lru_cache
def get_chat_llm() -> ChatGoogleGenerativeAI:
    ...
@lru_cache
def get_report_llm() -> ChatGoogleGenerativeAI:
    ...
```
Two cached connections to Gemini: one for fast, everyday chat/planning
(`gemini-2.5-flash`), one for longer report/slide writing (configurable
separately, though it defaults to the same model since Gemini's free tier
doesn't allow the Pro models).

```python
def with_retry(runnable):
    return runnable.with_retry(stop_after_attempt=3)
```
Wraps any AI call so that if it fails (network blip, temporary rate limit),
it automatically retries up to 3 times before giving up — applied at the
point each agent actually uses the model, not baked into the cached
connections above (a technical reason explained in the comment right above
this function in the actual file).

```python
@lru_cache
def _get_tavily_client() -> TavilyClient | None:
    settings = get_settings()
    if not settings.tavily_api_key or settings.tavily_api_key.startswith("tvly-REPLACE"):
        return None
    return TavilyClient(api_key=settings.tavily_api_key)

def web_search_tool(query: str, max_results: int = 5) -> list[dict]:
    client = _get_tavily_client()
    if client is None:
        return []
    try:
        response = client.search(query=query, max_results=max_results)
    except Exception:
        return []
    return [...]
```
Connects to the Tavily web search service — but only if a real API key is
set (the placeholder value is explicitly checked for). Both the "no key"
case and "search failed for some other reason" case return an empty list
rather than crashing, which is exactly what lets the app degrade gracefully
to "just use documents" instead of breaking the whole request.

---

## `backend/agent/nodes.py` — every agent's actual code

**Why it exists:** this is the heart of the app — one function per agent.
Every function follows the same pattern: read what it needs from `state`
(the shared clipboard), do its job, and return a small dictionary of updates
to merge back into `state`.

### The planner

```python
def route_urls(state: AgentState) -> dict:
    return {"detected_urls": extract_urls(state["query"])}
```
The very first step — just runs the free URL-finder from `tools.py` on your
message.

```python
def planner(state: AgentState) -> dict:
    has_documents = bool(workspace_store.list_documents())
    urls = state.get("detected_urls", [])
    url_note = ("The message includes a URL, so needs_web should usually be false..." if urls else "")
    llm = with_retry(get_chat_llm().with_structured_output(_PlannerOutput))
    prompt = f"{PLANNER_SYSTEM.format(...)}\n\nUser message: {state['query']}"
    result: _PlannerOutput = llm.invoke(prompt)
    return {
        "intent": result.intent,
        "needs_docs": result.needs_docs,
        "needs_web": result.needs_web,
        "report_type": result.report_type,
        "num_slides": max(3, min(20, result.num_slides)),
    }
```
Builds a prompt telling Gemini whether you have any documents at all and
whether a URL was found, then asks it (via `.with_structured_output(_PlannerOutput)`,
which forces the reply into a strict `{intent, needs_docs, needs_web,
report_type, num_slides}` shape instead of free-form text) to make the
routing decision. `num_slides` gets clamped between 3 and 20 no matter what
the AI said, as a safety net.

### The three question-answering agents

```python
def pdf_agent(state: AgentState) -> dict:
    if not state.get("needs_docs", True):
        return {"retrieved_chunks": []}
    k = REPORT_RETRIEVAL_K if state.get("intent") in {"report", "presentation"} else CHAT_RETRIEVAL_K
    chunks = retrieve(state["query"], k=k, doc_ids=state.get("doc_ids"))
    return {"retrieved_chunks": chunks}
```
If the planner said documents aren't needed, does nothing. Otherwise calls
`retriever.retrieve()` — fetching 5 chunks for a normal question, or 10 for
a report/presentation (since those need broader context to write something
longer).

```python
def web_agent(state: AgentState) -> dict:
    if not state.get("needs_web", False):
        return {"web_results": []}
    return {"web_results": web_search_tool(state["query"])}
```
Same idea — only actually searches the web if the planner said to.

```python
def url_agent(state: AgentState) -> dict:
    urls = state.get("detected_urls", [])
    if not urls:
        return {"url_context": []}
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
```
For every URL found in your message: scrape it, generate a fresh `doc_id`
for it, chunk and save it into the vector database exactly like an uploaded
file (so it's searchable again later), *and* keep up to 4000 characters of
its raw text directly in `url_context` — guaranteeing this turn's answer can
use it immediately, without waiting on a similarity search to rank it highly
enough.

```python
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
    citations = _build_citations(...)
    return {
        "answer": response.content,
        "citations": citations,
        "messages": [HumanMessage(state["query"]), AIMessage(response.content)],
    }
```
The final answer-writing step for a normal question. Picks which system
prompt to use based on whether anything was actually found (see the
`GENERAL_ANSWER_SYSTEM` fix above), sends the conversation history plus your
new message to Gemini, then returns the answer, a citations list, and the
new turn appended to `messages` (so the next question in this conversation
has context).

### The report agent (three steps, chained)

```python
def report_plan_outline(state: AgentState) -> dict:
    llm = with_retry(get_report_llm().with_structured_output(_Outline))
    ...
    return {"title": result.title, "outline": result.sections}
```
Asks Gemini for a report title and a list of section headings, adapted to
the requested `report_type`.

```python
def report_generate_sections(state: AgentState) -> dict:
    ...
    for section_title in state.get("outline", []):
        ...
        response = llm.invoke([system, HumanMessage(f"Write the '{section_title}' section.")])
        sections[section_title] = response.content
    ...
    return {"sections": sections, "citations": citations}
```
Loops over every section title from the outline and asks Gemini to write
it — one AI call per section, all sharing the same gathered context.

```python
def report_export(state: AgentState) -> dict:
    from backend.generators.report_generator import generate_report
    paths = generate_report(title=..., sections=..., citations=...)
    answer = f"I've generated your {state.get('report_type', 'summary')} report on \"{paths['title']}\". Download it below."
    return {**paths, "answer": answer, "messages": [...]}
```
No AI call here — just hands everything to `report_generator.py` to
actually write the files, then composes a short confirmation message (so
the chat has something to show, and the next turn has context that a report
was just made).

### The presentation agent

`presentation_plan_slides`, `presentation_generate_slides`, and
`presentation_build` are the exact same three-step pattern as the report
agent, just producing slide titles → slide bullet points → an actual
`.pptx` file instead.

### `_build_citations` — the shared citation builder

```python
def _build_citations(chunks, web_results, url_context=None) -> list[dict]:
    ...
```
Used by every terminal step (`synthesize_answer`, `report_generate_sections`,
`presentation_generate_slides`) to turn whatever was retrieved into the
structured citation list the frontend displays — independent of whether the
AI's actual written answer remembered to cite everything correctly.

---

## `backend/agent/graphs/supervisor_graph.py`

**Why it exists:** this is the flowchart itself — it doesn't contain any of
the agents' actual logic (that's all in `nodes.py`), just the wiring that
says "after this step, go to that step."

```python
_checkpointer = MemorySaver()
```
The thing that actually remembers conversation history between turns,
keyed by conversation id (`thread_id`).

```python
def _wanted_context_agents(state: AgentState) -> list[str]:
    agents = []
    if state.get("needs_docs", True):
        agents.append("pdf_agent")
    if state.get("needs_web", False):
        agents.append("web_agent")
    return agents
```
A shared helper: "given what the planner decided, which of the document/web
agents should actually run?" Reused by three different routing decisions
below (for questions, for reports, and for presentations).

```python
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
```
The main routing decision, right after the planner runs. Returns a **list**
of node names to run next — this is the actual mechanism that makes "only
the needed agents wake up" work: if the list is `["pdf_agent", "web_agent"]`,
LangGraph runs exactly those two (at the same time) and nothing else. If the
list ends up empty (a plain greeting, nothing needed), it routes straight to
`synthesize_answer` instead, skipping every agent.

```python
def _route_after_agents(state: AgentState) -> str:
    intent = state.get("intent", "qa")
    if intent == "report":
        return "report_generate_sections"
    if intent == "presentation":
        return "presentation_generate_slides"
    return "synthesize_answer"
```
After `pdf_agent`/`web_agent`/`url_agent` finish, this decides *where their
results should go next* — back to answering a question, or into the
report/presentation writing steps (since those two agents are shared and
reused by all three intents, not just questions).

```python
def _build() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("route_urls", route_urls)
    graph.add_node("planner", planner)
    ...
    graph.set_entry_point("route_urls")
    graph.add_edge("route_urls", "planner")
    graph.add_conditional_edges("planner", _route_after_planning, [...])
    graph.add_conditional_edges("pdf_agent", _route_after_agents, _AGENT_DESTINATIONS)
    ...
    graph.add_edge("synthesize_answer", END)
    graph.add_edge("report_generate_sections", "report_export")
    graph.add_edge("report_export", END)
    ...
    return graph.compile(checkpointer=_checkpointer)
```
Registers every agent function as a named "node," then connects them:
`add_edge` is a fixed, always-happens connection (like "route_urls always
leads to planner"); `add_conditional_edges` is a connection where *code*
decides where to go next each time, using the routing functions above. This
whole function runs once (see below) and produces the compiled, ready-to-run
graph.

```python
def get_supervisor_graph():
    global _graph
    if _graph is None:
        _graph = _build()
    return _graph
```
Builds the graph once and reuses it for every request afterward — building
it fresh on every single chat message would be wasteful.

---

## `backend/generators/report_generator.py`

**Why it exists:** turns a report's title + written sections into three
actual downloadable files — no AI involved here, just document assembly.

```python
def generate_report(title, sections, citations) -> dict:
    ...
    _write_markdown(markdown_path, title, sections, references)
    _write_docx(docx_path, title, sections, references)
    _write_pdf(pdf_path, title, sections, references)
    return {"title": title, "markdown_path": ..., "docx_path": ..., "pdf_path": ...}
```
The entry point — computes a safe filename (`_slugify`), builds the
"References" list from citations (`_references_lines`, de-duplicated), then
calls all three writer functions and returns their file paths.

```python
def _write_docx(path, title, sections, references) -> None:
    doc = DocxDocument()
    doc.add_heading(title, level=0)
    for section_title, content in sections.items():
        doc.add_heading(section_title, level=1)
        for paragraph in content.split("\n\n"):
            if paragraph.strip():
                doc.add_paragraph(paragraph.strip())
    ...
    doc.save(str(path))
```
Uses the `python-docx` library to build an actual Word document
programmatically: a title, then one heading + paragraphs per section, then
a References heading with bullet points, saved to disk.

`_write_markdown` does the same thing but just as plain `.md` text (much
simpler — Markdown headings are just `#`/`##` symbols). `_write_pdf` does
the same thing using the `reportlab` library, which builds PDFs out of a
list of "flowable" elements (`Paragraph`, `Spacer`) rather than Word's
paragraph/heading model.

---

## `backend/generators/pptx_generator.py`

**Why it exists:** same idea as the report generator, but produces an actual
`.pptx` PowerPoint file using the `python-pptx` library.

```python
def _add_bullet_slide(prs, title, bullets) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[CONTENT_SLIDE_LAYOUT])
    slide.shapes.title.text = title
    body = slide.placeholders[1].text_frame
    body.clear()
    body.text = bullets[0]
    for bullet in bullets[1:]:
        p = body.add_paragraph()
        p.text = bullet
    ...
```
Adds one slide using PowerPoint's built-in "Title and Content" layout, sets
its title, then writes the first bullet as the placeholder's main text and
adds every remaining bullet as an additional paragraph underneath.

```python
def generate_presentation(title, slide_titles, slide_content, citations) -> str:
    ...
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    title_slide = prs.slides.add_slide(prs.slide_layouts[TITLE_SLIDE_LAYOUT])
    title_slide.shapes.title.text = title
    ...
    if any(t.lower() == "agenda" for t in slide_titles):
        _add_bullet_slide(prs, "Agenda", content_titles)
    for slide_title in content_titles:
        _add_bullet_slide(prs, slide_title, slide_content.get(slide_title, []))
    if any(t.lower() == "references" for t in slide_titles):
        _add_bullet_slide(prs, "References", _reference_bullets(citations))
    prs.save(str(path))
    return str(path)
```
Sets up a 16:9 widescreen deck, adds a title slide, then (if the planner
included them) an Agenda slide listing every content slide's title, one
bullet slide per actual content topic, and a References slide built from
the citations — saved to disk, path returned.

---

## `backend/api/documents.py`

**Why it exists:** the HTTP "front door" for uploading/listing/deleting
documents — this is what the frontend's upload box actually talks to.

```python
@router.post("/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, ...)
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.max_file_size_mb:
        raise HTTPException(400, ...)
    ...
    saved_path.write_bytes(content)
    pages = load_document(str(saved_path))
    chunks = chunk_pages(pages, base_metadata)
    ingest_chunks(chunks)
    workspace_store.create_document(...)
    return UploadResponse(...)
```
The full upload pipeline in order: check the extension is supported, check
the file isn't too big, save the raw bytes to `storage/uploads/`, load its
text (`document_loader.py`), cut it into chunks (`chunker.py`), save those
chunks into the vector database (`retriever.py`), record it in the
documents table (`workspace_store.py`), then tell the caller how many
chunks it became.

```python
@router.post("/documents/ingest-url", response_model=UploadResponse)
async def ingest_url(request: UrlIngestRequest):
    ...
```
The same pipeline, but starting from `scrape_url()` instead of a file — used
directly by API clients (the chat UI instead triggers this same underlying
logic automatically via `url_agent`).

```python
@router.get("/documents", response_model=list[DocumentMeta])
async def list_documents():
    ...

@router.delete("/documents/{doc_id}", response_model=DeleteResponse)
async def delete_document(doc_id: str):
    delete_from_vector_store(doc_id)
    deleted = workspace_store.delete_document_record(doc_id)
    return DeleteResponse(doc_id=doc_id, deleted=deleted)
```
Simple list/delete endpoints — delete removes the document from *both*
places it's stored (the vector database's chunks, and the bookkeeping
table's row).

---

## `backend/api/chat.py`

**Why it exists:** the single endpoint everything (questions, reports,
presentations) goes through — the most important file in the API layer.

```python
@router.post("/chat")
@limiter.limit("30/minute")
async def chat(request: Request, body: ChatRequest):
    graph = get_supervisor_graph()
    config = {"configurable": {"thread_id": body.thread_id}}
    inputs = {"query": body.query, "doc_ids": body.doc_ids}
```
Grabs the one shared graph, builds a `config` telling LangGraph *which*
conversation's memory to use (`thread_id`), and packages your message as
`inputs`.

```python
    async def event_generator():
        result = {}
        used_rag = False
        used_web = False
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
            ...
```
Runs the graph and listens to its internal event stream as it executes,
picking out two kinds of events:
- Live text chunks coming specifically from the `synthesize_answer` step's
  AI call — forwarded immediately as `token` events, which is what makes the
  answer appear to "type" on screen.
- Each terminal step's final result (whichever one of `synthesize_answer`
  / `report_export` / `presentation_build` actually ran that turn) — merged
  into `result`, which becomes the final answer/citations/file-paths sent
  back. The `isinstance(output, dict)` check exists because a node's
  *internal* AI call also fires an event with the same node name, but a
  different, non-dict payload — a real bug that was hit and fixed during
  development.

```python
        yield {"event": "done", "data": json.dumps({"answer": ..., "citations": ..., ...})}
    return EventSourceResponse(event_generator())
```
Once the whole graph run finishes, sends one final `done` event bundling
everything the frontend needs, wrapped in Server-Sent Events (`EventSourceResponse`)
— a simple, standard way to stream a sequence of events over one HTTP
connection.

---

## `backend/main.py`

**Why it exists:** the file that actually assembles and starts the backend
— every other backend file gets pulled together here.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    workspace_store.init_db()
    yield
```
Runs once when the server starts: makes sure the SQLite `documents` table
exists before anything else happens.

```python
app = FastAPI(title="AI Research Assistant", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)
```
Creates the actual FastAPI application, wires in the rate limiter from
`rate_limit.py`, and adds CORS middleware (which allows the Streamlit
frontend, running on a different port, to talk to this backend at all —
browsers block cross-origin requests by default unless explicitly allowed).

```python
app.include_router(documents.router)
app.include_router(chat.router)

@app.get("/health")
async def health():
    return {"status": "ok"}
```
Registers the two route files' endpoints onto the app, plus a trivial
`/health` endpoint used to check the server is up and responding.

---

## `frontend/app.py`

**Why it exists:** the entire visible application — everything you actually
see and click runs from this one file.

```python
sys.path.insert(0, str(Path(__file__).resolve().parent))
```
A small technical necessity: makes the `utils/` folder importable as
`utils.api_client` regardless of which directory you launched Streamlit
from.

```python
def _new_conversation() -> str:
    thread_id = uuid.uuid4().hex
    st.session_state.conversations[thread_id] = {"title": "New conversation", "messages": []}
    return thread_id

if "conversations" not in st.session_state:
    st.session_state.conversations = {}
if st.session_state.get("active_thread_id") not in st.session_state.conversations:
    st.session_state.active_thread_id = _new_conversation()
```
Sets up the conversation-history system: `st.session_state` is Streamlit's
way of remembering data between interactions in the same browser tab.
`conversations` is a dictionary of every conversation you've started this
session; the second `if` makes sure there's always a valid "active"
conversation, even the very first time the page loads.

```python
with st.sidebar:
    st.header("💬 Conversations")
    if st.button("➕ New conversation", ...):
        st.session_state.active_thread_id = _new_conversation()
        st.rerun()
    st.divider()
    for thread_id, convo in reversed(list(st.session_state.conversations.items())):
        ...
        if st.button(label, key=f"convo-{thread_id}", ...):
            st.session_state.active_thread_id = thread_id
            st.rerun()
```
Builds the sidebar: a button to start fresh, then one button per existing
conversation (newest first), labeled by its title, with a 🟢 marker on
whichever one is currently active. Clicking any of them switches
`active_thread_id` and forces Streamlit to redraw the page (`st.rerun()`)
so the switch takes effect immediately.

```python
with st.expander("📎 Upload a document (PDF, DOCX, TXT, PPTX)"):
    ...
    uploaded = col1.file_uploader(...)
    if col2.button("Ingest", ...):
        with st.spinner(...):
            result = upload_document(uploaded.getvalue(), uploaded.name)
            st.success(...)
    docs = list_documents()
    for doc in docs:
        ...
        if cols[3].button("🗑️", ...):
            delete_document(doc["doc_id"])
            st.rerun()
```
A collapsible section: pick a file, click "Ingest" to send it to the
backend's `/upload`, and see the current document list with a delete button
per row.

```python
for message in active["messages"]:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        render_citations(message.get("citations", []))
        render_downloads(message.get("files") or {}, key_prefix=message["id"])
```
Replays the *current* conversation's full history every time the page
redraws — each past message shown with its citations and any download
buttons it had.

```python
query = st.chat_input(...)
if query:
    if not active["messages"]:
        active["title"] = query[:TITLE_MAX_LEN] + (...)
    active["messages"].append({"id": ..., "role": "user", "content": query})
    ...
```
When you actually submit a message: if this is the conversation's very
first message, use it (truncated) as the conversation's sidebar title, then
record it as a "user" message in the history.

```python
    def _stream():
        for event in chat_stream(query, st.session_state.active_thread_id):
            if event["type"] == "token":
                yield event["content"]
            else:
                result_holder.update(event)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            streamed_answer = st.write_stream(_stream())
        answer = streamed_answer or result_holder.get("answer", "")
        if not streamed_answer and answer:
            st.markdown(answer)
        render_citations(result_holder.get("citations", []))
        files = {...}
        render_downloads(files, key_prefix=message_id)
```
The actual live-answering part: `_stream()` calls the backend and yields
just the text chunks (saving everything else into `result_holder`).
`st.write_stream()` displays those chunks as they arrive, wrapped in a
spinner so there's visible feedback the instant you hit enter. If nothing
streamed (a report/presentation turn, which doesn't stream token-by-token),
it falls back to showing the final `answer` text directly. Then citations
and any download buttons render underneath.

```python
    active["messages"].append({"id": message_id, "role": "assistant", "content": answer, "citations": ..., "files": files})
    st.rerun()
```
Saves the finished assistant turn into history, then forces a redraw — this
matters because the sidebar (rendered earlier in the script, at the top)
needs to reflect a possibly-updated conversation title from this same turn.

---

## `frontend/utils/api_client.py`

**Why it exists:** every network call to the backend lives here — the rest
of the frontend never touches `httpx` directly, it just calls plain Python
functions like `upload_document(...)`.

```python
def upload_document(file_bytes: bytes, filename: str) -> dict:
    with _client() as client:
        response = client.post("/upload", files={"file": (filename, file_bytes)})
        response.raise_for_status()
        return response.json()
```
A simple, ordinary HTTP POST wrapped in a friendly function name — the
pattern repeats for `list_documents()` and `delete_document()`.

```python
def chat_stream(query, thread_id="default", doc_ids=None) -> Iterator[dict]:
    payload = {"query": query, "thread_id": thread_id, "doc_ids": doc_ids}
    with httpx.Client(...).stream("POST", "/chat", json=payload) as response:
        event_name = None
        for line in response.iter_lines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = line.split(":", 1)[1].strip()
                if event_name == "token":
                    yield {"type": "token", "content": data}
                elif event_name == "done":
                    yield {"type": "done", **json.loads(data)}
```
The trickiest function here — Streamlit has no built-in way to consume a
live SSE (Server-Sent Events) stream, so this reads the raw response
line-by-line and manually reconstructs each event: an `event: token` line
followed by a `data: ...` line becomes one `{"type": "token", ...}` dict
yielded back to `app.py`; `event: done` similarly becomes the final summary
dict.

---

## `frontend/utils/ui_helpers.py`

**Why it exists:** small, reusable pieces of interface used in more than one
place, kept out of `app.py` to keep that file focused on the page's overall
structure.

```python
def render_citations(citations: list[dict]) -> None:
    if not citations:
        return
    with st.expander(f"📎 {len(citations)} citation(s)"):
        for c in citations:
            if c.get("url"):
                st.markdown(f"- [{c.get('source', c['url'])}]({c['url']})")
            else:
                page = f" (p. {c['page']})" if c.get("page") else ""
                st.markdown(f"- **{c.get('source', 'Unknown')}**{page}: _{c.get('snippet', '')}_")
```
Draws a collapsible "📎 N citation(s)" box — a clickable link for web/URL
sources, or a bolded document name + page number + text snippet for
document sources. Does nothing at all if there are no citations to show.

```python
def download_file_button(label: str, path: str, mime: str, key: str) -> None:
    try:
        with open(path, "rb") as f:
            st.download_button(label, f.read(), file_name=..., mime=mime, key=key)
    except FileNotFoundError:
        st.error(f"File not found on server: {path}")
```
Reads a generated file straight off disk and turns it into a clickable
download button — works because the frontend and backend run on the same
machine, sharing the same filesystem.

```python
_FILE_KINDS = [("markdown_path", "⬇️ .md", "text/markdown"), ...]

def render_downloads(files: dict, key_prefix: str) -> None:
    present = [(field, label, mime) for field, label, mime in _FILE_KINDS if files.get(field)]
    if not present:
        return
    columns = st.columns(len(present))
    for column, (field, label, mime) in zip(columns, present):
        with column:
            download_file_button(label, files[field], mime, f"{key_prefix}-{field}")
```
Given a turn's file paths (some or all of which might be empty), figures
out which ones actually exist, lays out that many equal-width columns, and
puts one download button in each — so a report turn shows 3 buttons
(.md/.docx/.pdf) and a presentation turn shows 1 (.pptx), automatically.

---

## Wrapping up

That's every line of meaningful logic in the app, explained block by block.
For the bigger-picture view (the flowchart shape, the concepts, and a
plain-English walkthrough), see [HOW_IT_WORKS.md](HOW_IT_WORKS.md). For the
dense technical reference (exact behavior, edge cases, and the running list
of bugs hit and fixed), see [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md).
