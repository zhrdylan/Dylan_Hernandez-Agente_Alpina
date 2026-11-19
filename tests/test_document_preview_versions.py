import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.documents.preview import PagePreviewError, render_page_png, resolve_document_pdf


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
    assert resp_quote.headers.get("X-Highlight-Status") in ("exact", "partial")

    # 2. Plain page can be public cached
    resp_plain = client.get("/api/documents/C4/pages/1")
    assert resp_plain.status_code == 200
    assert "public" in resp_plain.headers.get("cache-control", "").lower()
    assert resp_plain.headers.get("X-Highlight-Status") == "plain"


def test_r08_missing_historical_version_communicates_unavailability():
    client = TestClient(app)
    # Asking for a historical version that does not exist must return 404, not fallback silently to another version
    resp = client.get("/api/documents/C4/pages/1?version=1978_no_existe")
    assert resp.status_code == 404
    detail = resp.json().get("detail", "")
    assert "1978_no_existe" in detail
    assert "no está disponible" in detail.lower()


def test_r08_quote_without_match_distinguishes_none_status():
    client = TestClient(app)
    # Quote that doesn't exist on page 1 of C4
    resp = client.get("/api/documents/C4/pages/1?quote=frase_absolutamente_inexistente_xyz999")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers.get("X-Highlight-Status") == "none"
    assert len(resp.content) > 1000

