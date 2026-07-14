from typing import Optional

from pydantic import BaseModel, Field


# ── Shared ─────────────────────────────────────────────────────────
class Citation(BaseModel):
    source: str
    doc_id: Optional[str] = None
    page: Optional[int] = None
    url: Optional[str] = None
    snippet: str = ""


# ── Documents ──────────────────────────────────────────────────────
class DocumentMeta(BaseModel):
    doc_id: str
    filename: str
    doc_type: str
    num_chunks: int
    uploaded_at: str


class UploadResponse(BaseModel):
    doc_id: str
    filename: str
    num_chunks: int
    message: str = "Document ingested successfully."


class UrlIngestRequest(BaseModel):
    url: str


class DeleteResponse(BaseModel):
    doc_id: str
    deleted: bool


# ── Chat (single entry point for everything: Q&A, reports, presentations) ──
class ChatRequest(BaseModel):
    query: str
    thread_id: str = Field(default="default", description="Conversation/session id for memory")
    doc_ids: Optional[list[str]] = None


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = []
    used_rag: bool = False
    used_web_search: bool = False
    markdown_path: Optional[str] = None
    docx_path: Optional[str] = None
    pdf_path: Optional[str] = None
    pptx_path: Optional[str] = None
