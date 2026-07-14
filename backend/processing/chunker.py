from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.config import get_settings


def _splitter() -> RecursiveCharacterTextSplitter:
    settings = get_settings()
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def chunk_pages(pages: list, base_metadata: dict) -> list[Document]:
    """Split a list of LoadedPage objects into LangChain Documents.

    Each output chunk carries base_metadata plus `page` (if the source page
    has one) and a `chunk_index` unique within the parent document.
    """
    splitter = _splitter()
    chunks: list[Document] = []
    chunk_index = 0
    for page in pages:
        for piece in splitter.split_text(page.text):
            if not piece.strip():
                continue
            metadata = {**base_metadata, "page": page.page, "chunk_index": chunk_index}
            chunks.append(Document(page_content=piece, metadata=metadata))
            chunk_index += 1
    return chunks


def chunk_text(text: str, base_metadata: dict) -> list[Document]:
    splitter = _splitter()
    return [
        Document(page_content=piece, metadata={**base_metadata, "chunk_index": i})
        for i, piece in enumerate(splitter.split_text(text))
        if piece.strip()
    ]
