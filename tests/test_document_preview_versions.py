import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.documents.preview import render_page_png, resolve_document_pdf


def test_render_page_png_with_version_and_quote():
    # Render with version specified
    png_v = render_page_png("C4", 1, version="2025", quote="Estados Financieros")
    assert png_v.startswith(b"\x89PNG")
    assert len(png_v) > 1000


def test_document_page_endpoint_cache_headers():
    client = TestClient(app)

    # 1. Page with quote must have private cache header (F18)
    resp_quote = client.get("/api/documents/C4/pages/1?quote=Estados%20Financieros&version=2025")
    assert resp_quote.status_code == 200
    assert resp_quote.headers["content-type"] == "image/png"
    assert "private" in resp_quote.headers.get("cache-control", "").lower()

    # 2. Plain page can be public cached
    resp_plain = client.get("/api/documents/C4/pages/1")
    assert resp_plain.status_code == 200
    assert "public" in resp_plain.headers.get("cache-control", "").lower()
