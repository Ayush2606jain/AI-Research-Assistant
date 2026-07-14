from backend.rag.prompt_templates import format_context
from backend.rag.retriever import RetrievedChunk


def test_retrieved_chunk_citation_label_with_page():
    chunk = RetrievedChunk(text="content", source="paper.pdf", doc_id="d1", page=3, score=0.9)
    assert chunk.citation_label() == "paper.pdf | Page 3"


def test_retrieved_chunk_citation_label_without_page():
    chunk = RetrievedChunk(text="content", source="notes.txt", doc_id="d1", page=None, score=0.9)
    assert chunk.citation_label() == "notes.txt"


def test_format_context_merges_chunks_and_web_results():
    chunks = [RetrievedChunk(text="doc excerpt", source="paper.pdf", doc_id="d1", page=1, score=0.8)]
    web_results = [{"title": "Some Article", "url": "https://example.com", "content": "web excerpt"}]
    context = format_context(chunks, web_results)
    assert "[paper.pdf | Page 1]" in context
    assert "doc excerpt" in context
    assert "[Web: Some Article]" in context
    assert "web excerpt" in context


def test_format_context_empty():
    assert format_context([], []) == "(no context retrieved)"
