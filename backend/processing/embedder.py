from functools import lru_cache

from langchain_google_genai import GoogleGenerativeAIEmbeddings

from backend.config import get_settings


@lru_cache
def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    """Singleton Gemini embeddings client.

    Left without an explicit `task_type` so the langchain-google-genai
    integration applies its own defaults: RETRIEVAL_DOCUMENT for
    `embed_documents()` and RETRIEVAL_QUERY for `embed_query()`, which is
    what we want for asymmetric retrieval (docs vs. queries).
    """
    settings = get_settings()
    return GoogleGenerativeAIEmbeddings(
        model=settings.embedding_model,
        google_api_key=settings.gemini_api_key,
    )
