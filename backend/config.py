from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # LLM / embeddings
    gemini_api_key: str
    llm_model: str = "gemini-2.5-flash-lite"
    report_llm_model: str = "gemini-2.5-flash-lite"
    embedding_model: str = "gemini-embedding-001"

    # Web search
    tavily_api_key: str = ""

    # Storage
    chroma_db_path: str = "./storage/chroma_db"
    upload_dir: str = "./storage/uploads"
    reports_dir: str = "./storage/reports"
    presentations_dir: str = "./storage/presentations"
    workspace_db_path: str = "./storage/workspace.db"

    # App config
    backend_url: str = "http://localhost:8000"
    max_file_size_mb: int = 50
    chunk_size: int = 1000
    chunk_overlap: int = 200
    rate_limit_per_minute: int = 30
    min_rag_relevance_score: float = 0.5

    def resolved_path(self, relative: str) -> Path:
        path = Path(relative)
        if not path.is_absolute():
            path = BASE_DIR / path
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()
