import uuid
from dataclasses import dataclass

from langchain_core.documents import Document

from backend.config import get_settings
from backend.database import get_vector_store


@dataclass
class RetrievedChunk:
    text: str
    source: str
    doc_id: str | None
    page: int | None
    score: float

    def citation_label(self) -> str:
        return f"{self.source}" + (f" | Page {self.page}" if self.page else "")


def ingest_chunks(chunks: list[Document]) -> int:
    if not chunks:
        return 0
    ids = [f"{chunk.metadata.get('doc_id', 'doc')}_{chunk.metadata.get('chunk_index', i)}_{uuid.uuid4().hex[:8]}" for i, chunk in enumerate(chunks)]
    get_vector_store().add_documents(chunks, ids=ids)
    return len(chunks)


def retrieve(
    query: str,
    k: int = 5,
    doc_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    where = {"doc_id": {"$in": doc_ids}} if doc_ids else None
    results = get_vector_store().similarity_search_with_relevance_scores(query, k=k, filter=where)
    min_score = get_settings().min_rag_relevance_score
    return [
        RetrievedChunk(
            text=doc.page_content,
            source=doc.metadata.get("source", "unknown"),
            doc_id=doc.metadata.get("doc_id"),
            page=doc.metadata.get("page"),
            score=score,
        )
        for doc, score in results
        if score >= min_score
    ]


def delete_document(doc_id: str) -> None:
    get_vector_store().delete(where={"doc_id": doc_id})
