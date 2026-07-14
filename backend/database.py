from functools import lru_cache

import chromadb
from langchain_chroma import Chroma

from backend.config import get_settings
from backend.processing.embedder import get_embeddings

DOCUMENTS_COLLECTION = "documents"


@lru_cache
def get_chroma_client() -> chromadb.ClientAPI:
    settings = get_settings()
    path = settings.resolved_path(settings.chroma_db_path)
    return chromadb.PersistentClient(path=str(path))


@lru_cache
def get_vector_store() -> Chroma:
    """Singleton LangChain Chroma vector store wrapping the persistent client.

    A single collection is used for all documents; per-document / per-project
    scoping is done via metadata filters at query time (see backend/rag/retriever.py),
    which keeps deletion and cross-document retrieval simple.
    """
    return Chroma(
        client=get_chroma_client(),
        collection_name=DOCUMENTS_COLLECTION,
        embedding_function=get_embeddings(),
    )
