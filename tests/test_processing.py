import pytest

from backend.processing.chunker import chunk_pages, chunk_text
from backend.processing.document_loader import LoadedPage, load_document


def test_chunk_text_splits_on_size():
    text = "word " * 500
    chunks = chunk_text(text, {"doc_id": "abc", "source": "test"})
    assert len(chunks) > 1
    assert all(c.metadata["doc_id"] == "abc" for c in chunks)
    assert all(c.metadata["chunk_index"] == i for i, c in enumerate(chunks))


def test_chunk_pages_carries_page_metadata():
    pages = [LoadedPage(text="Hello world. " * 50, page=1), LoadedPage(text="Second page. " * 50, page=2)]
    chunks = chunk_pages(pages, {"doc_id": "doc1", "source": "file.pdf"})
    assert chunks
    pages_seen = {c.metadata["page"] for c in chunks}
    assert pages_seen == {1, 2}


def test_load_txt_document(tmp_path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("Some plain text content.")
    pages = load_document(str(file_path))
    assert len(pages) == 1
    assert "plain text" in pages[0].text


def test_load_document_rejects_unsupported_extension(tmp_path):
    file_path = tmp_path / "sample.xyz"
    file_path.write_text("data")
    with pytest.raises(ValueError):
        load_document(str(file_path))
