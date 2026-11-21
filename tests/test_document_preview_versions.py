from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from app.documents import preview
from app.main import app
from app.documents.preview import PagePreviewError, render_page_png, resolve_document_pdf


def test_render_page_png_with_version_and_quote():
    # Render with version specified
    png_v = render_page_png("C4", 1, version="2025", quote="Estados Financieros")
    assert png_v.startswith(b"\x89PNG")
    assert len(png_v) > 1000


def test_document_page_endpoint_cache_headers():
    client = TestClient(app, base_url="http://localhost")

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
    client = TestClient(app, base_url="http://localhost")
    # Asking for a historical version that does not exist must return 404, not fallback silently to another version
    resp = client.get("/api/documents/C4/pages/1?version=1978_no_existe")
    assert resp.status_code == 404
    detail = resp.json().get("detail", "")
    assert "1978_no_existe" in detail
    assert "no está disponible" in detail.lower()


def test_r08_quote_without_match_distinguishes_none_status():
    client = TestClient(app, base_url="http://localhost")
    # Quote that doesn't exist on page 1 of C4
    resp = client.get("/api/documents/C4/pages/1?quote=frase_absolutamente_inexistente_xyz999")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers.get("X-Highlight-Status") == "none"
    assert len(resp.content) > 1000


@pytest.mark.parametrize(("quote", "highlight", "boxes_count"), [(None, "plain", 0), ("Leche entera", "exact", 1)])
def test_product_sheet_renders_with_and_without_a_quote(monkeypatch, tmp_path, quote, highlight, boxes_count):
    connect = MagicMock()
    cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {
        "id": "ALP-001", "name": "Producto de prueba", "brand": "Alpina", "presentation": "200 g",
        "price": 4000, "protein_g": 4, "claims": ["Fuente de calcio"], "ean": None,
        "metadata": {}, "ingredients": "Leche entera", "allergens": "Contiene leche",
    }
    monkeypatch.setattr(preview, "connect", connect)
    monkeypatch.setattr(preview, "CACHE_DIR", tmp_path)

    png, metadata = render_page_png("PRODUCT-ALP-001", 1, quote=quote, return_meta=True)

    assert png.startswith(b"\x89PNG")
    assert metadata == {"highlight_status": highlight, "boxes_count": boxes_count}
    assert render_page_png("PRODUCT-ALP-001", 1, quote=quote, return_meta=True) == (png, metadata)
    assert render_page_png("PRODUCT-ALP-001", 1, quote=quote) == png
    connect.assert_called_once()


def test_cached_page_preserves_highlight_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(preview, "CACHE_DIR", tmp_path)
    options = {"version": "2025", "quote": "Estados Financieros"}
    png = render_page_png("C4", 1, **options)
    pdfium = MagicMock(side_effect=AssertionError("La página ya está en caché"))
    monkeypatch.setattr(preview.pdfium, "PdfDocument", pdfium)

    cached, meta = render_page_png("C4", 1, return_meta=True, **options)

    assert cached == png
    assert meta["highlight_status"] in {"exact", "partial"}
    assert meta["boxes_count"] > 0
    pdfium.assert_not_called()


@pytest.mark.parametrize("version", ["", "2025/03", "2025:03", "a" * 81])
def test_pdf_version_is_validated_before_filesystem_access(monkeypatch, version):
    directory = MagicMock()
    monkeypatch.setattr(preview, "DOCUMENT_CACHE_DIR", directory)
    for resolve in (preview.resolve_document_pdf, preview._r2_pdf_path):
        with pytest.raises(PagePreviewError, match="Versión no válida"):
            resolve("C4", version)
    assert directory.mock_calls == []

