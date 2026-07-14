import json
import os
from typing import Iterator

import httpx

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
TIMEOUT = httpx.Timeout(120.0)


def _client() -> httpx.Client:
    return httpx.Client(base_url=BACKEND_URL, timeout=TIMEOUT)


# ── Documents ────────────────────────────────────────────────────
def upload_document(file_bytes: bytes, filename: str) -> dict:
    with _client() as client:
        response = client.post("/upload", files={"file": (filename, file_bytes)})
        response.raise_for_status()
        return response.json()


def list_documents() -> list[dict]:
    with _client() as client:
        response = client.get("/documents")
        response.raise_for_status()
        return response.json()


def delete_document(doc_id: str) -> dict:
    with _client() as client:
        response = client.delete(f"/documents/{doc_id}")
        response.raise_for_status()
        return response.json()


# ── Chat (SSE streaming) — the single entry point for Q&A, reports, and
# presentations. The planner inside the graph decides which agents to run. ──
def chat_stream(query: str, thread_id: str = "default", doc_ids: list[str] | None = None) -> Iterator[dict]:
    """Yields {"type": "token", "content": str} while streaming, then a final
    {"type": "done", "answer", "citations", "used_rag", "used_web_search",
     "markdown_path", "docx_path", "pdf_path", "pptx_path"}."""
    payload = {"query": query, "thread_id": thread_id, "doc_ids": doc_ids}
    with httpx.Client(base_url=BACKEND_URL, timeout=TIMEOUT) as client:
        with client.stream("POST", "/chat", json=payload) as response:
            response.raise_for_status()
            event_name = None
            for line in response.iter_lines():
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data = line.split(":", 1)[1].strip()
                    if event_name == "token":
                        yield {"type": "token", "content": data}
                    elif event_name in ("done", "error"):
                        yield {"type": event_name, **json.loads(data)}
