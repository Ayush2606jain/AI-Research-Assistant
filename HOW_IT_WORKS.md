# How It Works — A Simple Guide

This is a plain-language companion to [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)
(which is the detailed, technical version). Read this one first if you just
want to understand what's going on without wading through code-level detail.

---

## 1. What is this project, in one paragraph?

It's a chatbot with one input box. You type a question, paste a link, or ask
it to write a report or build a slideshow — and behind the scenes, it
figures out on its own what kind of help you need and which "specialist" to
send your request to. It can read your uploaded files, read a link you
paste, search the internet, or write documents for you — all from the same
box, in the same conversation.

---

## 2. The big idea: think of it like a helpdesk

Imagine you walk into an office with one question. There's a **receptionist**
at the front desk who listens to what you need and sends you to the right
person:

- Need info from a document? → sent to the **filing clerk**
- Need something looked up online? → sent to the **researcher**
- Gave them a web link? → sent to the **link reader**
- Want a written report? → sent to the **report writer**
- Want a slideshow? → sent to the **presentation designer**

That receptionist is what we call the **planner**. Each specialist is what
we call an **agent**. You never have to know who to ask — you just say what
you want, and the planner routes it.

This whole system — the receptionist plus all the specialists working
together — is called a **multi-agent workflow**.

---

## 3. Concepts explained simply

You'll see these words throughout the codebase and this document. Here's
what each one actually means, without jargon:

- **Agent** — a small, focused worker that knows how to do ONE job well
  (search documents, search the web, read a URL, write a report). It's just
  a function in code, but it "acts" somewhat independently based on
  instructions.

- **Planner** — the "receptionist" agent. It reads your message once and
  decides: *what do they actually want, and who should handle it?*

- **Workflow / Graph** — the flowchart connecting the planner to all the
  agents. "Graph" is just the technical name for a flowchart with boxes
  (steps) and arrows (what happens next). We use a toolkit called
  **LangGraph** to build this flowchart in code.

- **RAG (Retrieval-Augmented Generation)** — a fancy name for a simple idea:
  *before* the AI answers, go find the relevant pieces of text (from your
  documents, the web, or a link) and hand them to the AI as reference
  material, so it answers from real information instead of guessing.

- **Embeddings / Vector database** — to "search" your documents, we
  convert every chunk of text into a list of numbers (an *embedding*) that
  captures its meaning. Similar meanings end up as similar numbers. All
  these number-lists are stored in a **vector database** (we use one called
  ChromaDB) so we can quickly find "which chunks of text are most similar
  in meaning to this question?"

- **Chunk** — documents are cut into small pieces (a paragraph or so) before
  being stored, because it's more useful to retrieve "the one relevant
  paragraph" than "the entire 50-page PDF."

- **Citation** — every fact the AI uses gets tagged with exactly where it
  came from (which document, which page, which website), so you can verify
  it yourself instead of just trusting the AI blindly.

- **Streaming** — instead of waiting for the whole answer to be ready, the
  words appear on screen one-by-one as the AI generates them — like
  watching someone type instead of waiting for them to hand you a finished
  letter.

- **Memory** — the AI remembers what you said earlier in the *same*
  conversation, so a follow-up like "make that shorter" makes sense. Each
  conversation has its own separate memory (see the sidebar in the app).

- **Scraping** — automatically visiting a web page and pulling out its
  readable text, so a pasted link can be used the same way an uploaded
  document is used.

---

## 4. Meet the agents

| Agent | What it does, in plain terms |
|---|---|
| 🧭 **Planner** | Reads your message and decides: is this a question, a report request, or a presentation request? Does it need to check your documents? The web? Is there a link in the message? |
| 📄 **Document (PDF) agent** | Searches everything you've uploaded (PDFs, Word docs, text files, slide decks) for the parts relevant to your question. |
| 🌐 **Web agent** | Searches the internet for current information, using a search service called Tavily. |
| 🔗 **URL agent** | When you paste a link, this agent visits that page, reads it, saves it permanently (so you can ask about it again later), and hands its content straight to the answer step. |
| ✍️ **Report agent** | When you ask for a report ("write a literature review on X"), this plans an outline, gathers supporting information, writes each section, and produces a downloadable Word/PDF/Markdown file. |
| 📊 **Presentation agent** | Same idea as the report agent, but produces a downloadable PowerPoint slide deck instead. |
| 💬 **Answer writer** | The final step for a normal question — takes whatever the document/web/URL agents found and writes one clear answer, citing sources. If nothing was found (or nothing was needed, like a simple "hello"), it just answers normally from its own knowledge instead of refusing. |

**Important:** not every agent runs every time. If you just say "hello,"
none of them run — the planner sees there's no research question and skips
straight to the answer writer. If you paste a link, only the URL agent
(usually) runs. The planner only wakes up the agents that are actually
needed for your specific message.

---

## 5. The workflow, step by step

Here's what happens every time you press enter:

```
 1. You type a message
          │
 2. The Planner reads it and decides:
    - Is this a question, a report request, or a presentation request?
    - Does it need to look at your documents?
    - Does it need to search the web?
    - Is there a link in the message?
          │
 3. Only the needed agents wake up and gather information
    (documents / web search / reading a pasted link)
          │
 4. Everything they found gets combined into one bundle of "context"
          │
 5a. If it was a question → the Answer Writer replies, citing sources,
     and the words stream onto your screen live
 5b. If it was a report/presentation request → the Report or Presentation
     agent plans an outline, writes it section-by-section, saves the file,
     and posts a short "here's your report, download below" message
          │
 6. The whole exchange is remembered for the rest of that conversation
```

---

## 6. A real walkthrough: pasting a URL and asking a question

Say you paste `https://example.com/article` and ask *"What does this say
about pricing?"*

1. The app spots the link in your message automatically (no need to click
   "upload" or anything).
2. The Planner reads your message and decides: *this is a question
   ("qa"), and since there's a link, the answer probably comes from that
   link rather than the web or your other documents.*
3. The **URL agent** wakes up: it visits the page, pulls out its readable
   text, saves it to your document library (so you could ask about it again
   in a future conversation too), and also hands that text directly to the
   next step.
4. The **Answer Writer** reads that text and answers your question, with a
   citation pointing back to that page.
5. The answer streams onto your screen word by word, with a "📎 citations"
   box you can expand to see exactly what was used.

If the page didn't actually contain pricing information (common on pages
where prices are loaded by JavaScript after the page opens, or sites that
show a simplified page to automated visitors), the app now also tries
opening the page in a real, invisible browser (see `web_scraper.py` below)
before giving up — the same trick a human would use if the simple version
of the page didn't show what they needed.

---

## 7. File-by-file guide

### Backend (`backend/`) — the "brain," runs as a server

| File | What it does |
|---|---|
| `main.py` | Starts the whole backend server, connects all the pieces together. |
| `config.py` | Reads your settings from `.env` (API keys, file size limits, etc.). |
| `database.py` | Sets up the vector database (ChromaDB) where document chunks are stored and searched. |
| `workspace_store.py` | Keeps a simple list of your uploaded documents (name, type, when added) in a small local database file. |
| `rate_limit.py` | Stops the app from being hit with too many requests too quickly. |

**`backend/models/`** — the shapes of data going in and out
| File | What it does |
|---|---|
| `schemas.py` | Defines exactly what a "chat request," "uploaded document," etc. look like — like a form template. |

**`backend/processing/`** — turning raw files/pages into usable text
| File | What it does |
|---|---|
| `document_loader.py` | Opens a PDF/Word/text/PowerPoint file and pulls out its raw text, page by page. |
| `table_extractor.py` | Specifically pulls tables out of PDFs and turns them into readable text. |
| `chunker.py` | Cuts long text into smaller, bite-sized pieces so they're easier to search later. |
| `embedder.py` | Turns text into the "numbers that represent meaning" (embeddings) using Google's AI. |
| `web_scraper.py` | Visits a web page and extracts its readable text — tries a fast simple method first, then a real invisible browser if the simple method doesn't find much. |

**`backend/rag/`** — the search-and-retrieve logic
| File | What it does |
|---|---|
| `retriever.py` | Actually saves text chunks into the vector database, and searches it later ("find the 5 most relevant chunks to this question"). Also filters out results that aren't actually relevant enough. |
| `prompt_templates.py` | The exact instructions given to the AI for each task (answering, planning a report outline, writing a slide, etc.) — basically the "scripts" the AI follows. |

**`backend/agent/`** — the planner and all the specialist agents
| File | What it does |
|---|---|
| `state.py` | Defines what information gets passed around between agents during one conversation turn (the question, what was found, the answer so far, etc.). |
| `tools.py` | Shared helpers: connecting to Google's AI, connecting to the web-search service, and finding links inside a message. |
| `nodes.py` | The actual code for every agent — the planner, document agent, web agent, URL agent, answer writer, and the report/presentation writers. |
| `graphs/supervisor_graph.py` | Wires all the agents together into the flowchart described in section 5 — who can hand off to whom. |

**`backend/generators/`** — turning an agent's work into downloadable files
| File | What it does |
|---|---|
| `report_generator.py` | Takes the report agent's written sections and saves them as a Word document, PDF, and Markdown file. |
| `pptx_generator.py` | Takes the presentation agent's slide content and saves it as an actual PowerPoint file. |

**`backend/api/`** — the "front door" other programs (like our own frontend) talk to
| File | What it does |
|---|---|
| `documents.py` | Handles uploading a file, listing your documents, and deleting one. |
| `chat.py` | The single endpoint everything goes through — receives your message, runs it through the whole agent workflow, and streams back the answer. |

### Frontend (`frontend/`) — the web page you actually see and click on

| File | What it does |
|---|---|
| `app.py` | The entire visible app: the sidebar (past conversations), the file upload box, the chat window, and the input box at the bottom. |
| `utils/api_client.py` | Handles all the behind-the-scenes internet requests to the backend (uploading files, sending chat messages, etc.). |
| `utils/ui_helpers.py` | Small reusable pieces of the interface — showing citations neatly, showing download buttons for generated files. |

### Everything else

| File/folder | What it does |
|---|---|
| `.env` | Your actual secret keys and settings (kept private, never shared). |
| `.env.example` | A blank template showing what settings exist, safe to share. |
| `requirements.txt` | The list of external tools/libraries the project depends on. |
| `storage/` | Where uploaded files, the vector database, and generated reports/presentations actually live on disk. |
| `tests/` | Automated checks that verify pieces of the code still work correctly. |

---

## 8. Where to go next

- Want the full technical detail (exact function names, how the flowchart's
  code is wired, every bug we hit and how it was fixed)? Read
  [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md).
- Want to just run the thing? Read [README.md](README.md).
