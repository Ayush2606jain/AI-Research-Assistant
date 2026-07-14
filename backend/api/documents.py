import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.config import get_settings
from backend.models.schemas import DeleteResponse, DocumentMeta, UploadResponse, UrlIngestRequest
from backend.processing.chunker import chunk_pages, chunk_text
from backend.processing.document_loader import SUPPORTED_EXTENSIONS, load_document
from backend.processing.web_scraper import WebScrapeError, scrape_url
from backend.rag.retriever import delete_document as delete_from_vector_store
from backend.rag.retriever import ingest_chunks
from backend import workspace_store

router = APIRouter(tags=["documents"])


@router.post("/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    settings = get_settings()
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}")

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.max_file_size_mb:
        raise HTTPException(400, f"File too large ({size_mb:.1f}MB). Limit is {settings.max_file_size_mb}MB.")

    doc_id = uuid.uuid4().hex[:12]
    upload_dir = settings.resolved_path(settings.upload_dir)
    saved_path = upload_dir / f"{doc_id}{ext}"
    saved_path.write_bytes(content)

    try:
        pages = load_document(str(saved_path))
    except Exception as exc:
        raise HTTPException(422, f"Failed to parse document: {exc}") from exc

    base_metadata = {"doc_id": doc_id, "source": file.filename}
    chunks = chunk_pages(pages, base_metadata)
    if not chunks:
        raise HTTPException(422, "No extractable text found in this document.")

    ingest_chunks(chunks)
    workspace_store.create_document(doc_id, file.filename, ext.lstrip("."), len(chunks))

    return UploadResponse(doc_id=doc_id, filename=file.filename, num_chunks=len(chunks))


@router.post("/documents/ingest-url", response_model=UploadResponse)
async def ingest_url(request: UrlIngestRequest):
    try:
        scraped = scrape_url(request.url)
    except WebScrapeError as exc:
        raise HTTPException(422, str(exc)) from exc

    doc_id = uuid.uuid4().hex[:12]
    base_metadata = {"doc_id": doc_id, "source": scraped["title"]}
    chunks = chunk_text(scraped["text"], base_metadata)
    if not chunks:
        raise HTTPException(422, "No extractable text found at that URL.")

    ingest_chunks(chunks)
    workspace_store.create_document(doc_id, scraped["title"], "url", len(chunks))

    return UploadResponse(doc_id=doc_id, filename=scraped["title"], num_chunks=len(chunks))


@router.get("/documents", response_model=list[DocumentMeta])
async def list_documents():
    return [DocumentMeta(**doc) for doc in workspace_store.list_documents()]


@router.delete("/documents/{doc_id}", response_model=DeleteResponse)
async def delete_document(doc_id: str):
    delete_from_vector_store(doc_id)
    deleted = workspace_store.delete_document_record(doc_id)
    return DeleteResponse(doc_id=doc_id, deleted=deleted)
