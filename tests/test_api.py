from fastapi.testclient import TestClient

from backend.main import app


def test_health_check():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_upload_rejects_unsupported_extension():
    with TestClient(app) as client:
        response = client.post(
            "/upload",
            files={"file": ("sample.xyz", b"some bytes", "application/octet-stream")},
        )
        assert response.status_code == 400


def test_list_documents_returns_a_list():
    with TestClient(app) as client:
        response = client.get("/documents")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
