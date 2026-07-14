import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from backend.config import get_settings


@contextmanager
def _connection():
    conn = sqlite3.connect(get_settings().workspace_db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    Path(get_settings().workspace_db_path).parent.mkdir(parents=True, exist_ok=True)
    with _connection() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                doc_type TEXT NOT NULL,
                num_chunks INTEGER NOT NULL,
                uploaded_at TEXT NOT NULL
            )"""
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_document(doc_id: str, filename: str, doc_type: str, num_chunks: int) -> dict:
    document = {
        "doc_id": doc_id,
        "filename": filename,
        "doc_type": doc_type,
        "num_chunks": num_chunks,
        "uploaded_at": _now(),
    }
    with _connection() as conn:
        conn.execute(
            """INSERT INTO documents (doc_id, filename, doc_type, num_chunks, uploaded_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                document["doc_id"],
                document["filename"],
                document["doc_type"],
                document["num_chunks"],
                document["uploaded_at"],
            ),
        )
    return document


def list_documents() -> list[dict]:
    with _connection() as conn:
        rows = conn.execute("SELECT * FROM documents ORDER BY uploaded_at DESC").fetchall()
    return [dict(row) for row in rows]


def delete_document_record(doc_id: str) -> bool:
    with _connection() as conn:
        cursor = conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    return cursor.rowcount > 0
