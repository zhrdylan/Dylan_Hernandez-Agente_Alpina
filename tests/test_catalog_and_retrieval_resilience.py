from __future__ import annotations

import unittest.mock as mock
import pytest
from app.retrieval.search import SearchFilters
from app.products.search import product_row_to_result, search_products
from app.agent.graph import _default_retrieve, retrieve_node


def test_product_row_explicit_undeclared_fields():
    """F12: Missing ingredients and allergens must be explicitly marked as undeclared."""
    row = {
        "id": "ALP-001",
        "ean": "7702001000001",
        "name": "Alpinito Fresa",
        "brand": "Alpina",
        "presentation": "45 g",
        "price": 2500,
        "currency": "COP",
        "protein_g": 3.2,
        "claims": [],
        "ingredients": None,
        "allergens": None,
        "availability": "Disponible",
        "source_url": "https://alpina.com/alpinito",
        "source_page": 1,
        "metadata": {},
    }
    result = product_row_to_result(row)
    assert "No consta en la fuente oficial (no declarado)" in result.content
    assert "Claims: No consta en la fuente oficial" in result.content


def test_search_products_exact_sku_priority():
    """F12: Exact SKU or EAN query should be resolved via exact match first."""
    mock_conn = mock.MagicMock()
    mock_cur = mock.MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    
    # Return mock row on exact query
    mock_cur.fetchall.return_value = [
        {
            "id": "ALP-TEST-01",
            "ean": "7701234567890",
            "name": "Producto Prueba",
            "brand": "Alpina",
            "presentation": "100 g",
            "price": 3000,
            "currency": "COP",
            "protein_g": 5.0,
            "claims": ["Alto en calcio"],
            "ingredients": "Leche entera",
            "allergens": "Contiene leche",
            "availability": "Disponible",
            "source_url": "https://alpina.com",
            "source_page": 1,
            "metadata": {},
            "score": 1.0,
        }
    ]
    
    results = search_products(mock_conn, "ALP-TEST-01")
    assert len(results) == 1
    assert results[0].document_id == "ALP-TEST-01"
    # Verify exact SQL was executed with upper(id) or ean
    executed_sql = mock_cur.execute.call_args[0][0]
    assert "upper(id) = upper(%s)" in executed_sql or "id = %s" in executed_sql


def test_default_retrieve_resilience_when_embeddings_fail():
    """F11, F12: If coverage/vector search fails (Cohere down), product search must still return results."""
    mock_filters = SearchFilters(categories=["nutrition"])
    
    with mock.patch("app.agent.graph.connect") as mock_connect, \
         mock.patch("app.agent.graph.coverage_search", side_effect=RuntimeError("Cohere API down / Connection error")), \
         mock.patch("app.agent.graph.search_products") as mock_search_products:
        
        # Product search succeeds
        mock_product = mock.MagicMock()
        mock_product.document_id = "ALP-001"
        mock_product.chunk_id = "product-ALP-001"
        mock_product.content = "Alpinito Fresa"
        # Mock dataclasses.asdict
        with mock.patch("app.agent.graph.dataclasses.asdict", return_value={"document_id": "ALP-001", "chunk_id": "product-ALP-001"}):
            mock_search_products.return_value = [mock_product]
            results = _default_retrieve("Alpinito fresa", mock_filters)
            
            assert len(results) == 1
            assert results[0]["document_id"] == "ALP-001"


def test_retrieve_node_broadening_preserves_document_ids():
    """F11: Broadening search when empty must NOT discard explicitly requested document_ids."""
    state = {
        "search_query": "Requisitos de rotulado",
        "needs_documents": True,
        "filters": {
            "categories": ["normative"],
            "document_ids": ["RES-810-2021"],
        },
        "issues": [],
    }
    
    called_filters = []
    def mock_retrieve_fn(query, filters):
        called_filters.append(filters)
        if len(called_filters) == 1:
            return []  # Initial search empty
        return [{"document_id": "RES-810-2021", "chunk_id": "c1", "content": "Rotulado"}]
    
    result = retrieve_node(state, mock_retrieve_fn)
    assert len(called_filters) == 2
    # The broadened filter must keep document_ids!
    assert called_filters[1].document_ids == ["RES-810-2021"]
    assert called_filters[1].categories is None
    assert len(result["results"]) == 1


def test_empty_extraction_marked_as_failed():
    """F13: Empty extraction with 0 characters must be marked as 'failed', not 'complete'."""
    from app.ingestion.parser import PageText
    # Simulate page with empty text
    empty_page = PageText(page_number=1, text="", method="ocr_empty")
    
    pages = [empty_page]
    errors = [{"page": 1, "error": "El OCR devolvió texto vacío.", "kind": "empty"}]
    stats = {
        "text_pages": 0,
        "ocr_pages": 0,
        "ocr_skipped": 0,
        "ocr_failed": 0,
        "empty_pages": 1,
        "total_chars": 0,
    }
    
    if stats["total_chars"] == 0 or (pages and stats["empty_pages"] == len(pages)):
        status = "failed"
    elif errors or stats["ocr_skipped"] > 0 or stats["ocr_failed"] > 0:
        status = "partial"
    else:
        status = "complete"
        
    assert status == "failed"
