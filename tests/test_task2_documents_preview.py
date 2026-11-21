import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.documents.preview import (
    resolve_document_title,
    render_page_png,
    get_document_page_count,
    resolve_document_pdf,
)


def test_official_document_titles():
    expected = {
        "C1": "Informe de Gestión 2026 · Alpina",
        "C2": "Informe de Sostenibilidad 2025 · Alpina",
        "C4": "Estados Financieros Separados 2025 · Alpina S.A.S. BIC",
        "C5": "Estados Financieros Consolidados 2025 · Alpina",
        "N1": "Ley 2120 de 2021 (Ley de Comida Chatarra)",
        "N2": "Resolución 810 de 2021 (Etiquetado Nutricional y Frontal)",
        "N3": "Resolución 2492 de 2022 (Sellos Frontales de Advertencia)",
    }
    for doc_id, expected_title in expected.items():
        assert resolve_document_title(doc_id) == expected_title


def test_list_documents_api():
    client = TestClient(app, base_url="http://localhost")
    resp = client.get("/api/documents")
    assert resp.status_code == 200
    docs = resp.json()
    assert len(docs) > 0
    c4 = next((d for d in docs if d["id"] == "C4"), None)
    assert c4 is not None
    assert c4["title"] == "Estados Financieros Separados 2025 · Alpina S.A.S. BIC"
    assert c4["page_count"] > 0


def test_download_document_pdf_api():
    client = TestClient(app, base_url="http://localhost")
    resp = client.get("/api/documents/C4/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert len(resp.content) > 1000


def test_render_page_png_with_highlight():
    # Test rendering page 1 of C4 with and without quote
    png_plain = render_page_png("C4", 1)
    assert png_plain.startswith(b"\x89PNG")

    png_highlight = render_page_png("C4", 1, quote="Estados Financieros")
    assert png_highlight.startswith(b"\x89PNG")
    assert len(png_highlight) > 0
