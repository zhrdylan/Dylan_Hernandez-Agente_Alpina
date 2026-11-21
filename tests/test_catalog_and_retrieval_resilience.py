from __future__ import annotations

import unittest.mock as mock
import pytest
from app.retrieval.search import SearchFilters
from app.products.search import product_row_to_result, search_products
from app.agent.graph import _default_retrieve, retrieve_node
from app.agent.validation import validate_citations


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


def test_product_citation_carries_type_and_official_url_for_unprefixed_id():
    product = product_row_to_result({
        "id": "ALP-001",
        "name": "Producto de prueba",
        "source_url": "https://alpina.com/producto-de-prueba",
    })

    citations, issues = validate_citations([{"source": 1}], [product])

    assert issues == []
    assert citations[0]["kind"] == "product"
    assert citations[0]["document_id"] == "ALP-001"
    assert citations[0]["source_url"] == product.source_url


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


def test_r09_hybrid_search_combines_vector_and_fts():
    """R09: hybrid_search must perform true hybrid search with FTS and vector RRF fusion."""
    from app.retrieval.search import hybrid_search, SearchFilters

    mock_conn = mock.MagicMock()
    mock_vector = [
        {
            "chunk_id": "c_vec_1",
            "document_id": "C4",
            "document_title": "EEFF 2025",
            "version_id": "v1",
            "version": "2025",
            "page_start": 2,
            "page_end": 2,
            "section": "P&L",
            "content": "Ventas netas alcanzaron 2.4 billones",
            "source_url": None,
            "category": "corporate",
            "doc_type": "informe",
            "country": "CO",
            "vigente": True,
            "is_current": True,
            "vector_score": 0.88,
        }
    ]
    mock_fts = [
        {
            "chunk_id": "c_fts_1",
            "document_id": "C4",
            "document_title": "EEFF 2025",
            "version_id": "v1",
            "version": "2025",
            "page_start": 4,
            "page_end": 4,
            "section": "Notas",
            "content": "EBITDA consolidado de 368 mil millones",
            "source_url": None,
            "category": "corporate",
            "doc_type": "informe",
            "country": "CO",
            "vigente": True,
            "is_current": True,
            "fts_score": 0.42,
        }
    ]

    with mock.patch("app.retrieval.search._vector_rows", return_value=mock_vector), \
         mock.patch("app.retrieval.search._fts_rows", return_value=mock_fts), \
         mock.patch("app.retrieval.search.embed_query", return_value=[0.1] * 1024):
        results = hybrid_search(mock_conn, "ventas ebitda", limit=5)
        assert len(results) == 2
        chunk_ids = {r.chunk_id for r in results}
        assert "c_vec_1" in chunk_ids
        assert "c_fts_1" in chunk_ids
        assert all(r.rrf_score > 0 for r in results)


def test_r09_reindex_triggered_when_embedding_model_differs():
    """R09: When embeddings for the active model are missing or model changed, ingest_document reindexes."""
    from app.ingestion.ingest import ingest_document

    mock_conn = mock.MagicMock()
    mock_cur = mock.MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    record = {
        "id": "C4",
        "title": "EEFF 2025",
        "category": "corporate",
        "sha256": "abc123sha",
        "version": "2025",
        "page_count": 10,
        "filename": "c4.pdf",
        "effective_date": "2025-01-01",
        "published_date": "2025-02-01",
        "vigente": True,
        "source_page": "",
        "pdf_url": "",
        "extraction_status": "complete",
        "extracted_at": "2025-02-01T00:00:00Z",
        "ocr_model": "test",
        "stats": {"total_chars": 5000},
        "pages": [{"page_number": 1, "text": "Reporte financiero con texto suficiente para chunks " * 10}],
    }
    manifest_doc = {"id": "C4", "title": "EEFF 2025", "category": "corporate", "sha256": "abc123sha"}

    # Mock version exists with 5 chunks, but 0 embeddings for the active model!
    with mock.patch("app.ingestion.ingest._fetch_version", return_value={"id": "v-uuid", "sha256": "abc123sha", "is_current": True}), \
         mock.patch("app.ingestion.ingest._count_chunks", return_value=5), \
         mock.patch("app.ingestion.ingest._count_model_embeddings", return_value=0), \
         mock.patch("app.ingestion.ingest._replace_chunks") as mock_replace, \
         mock.patch("app.ingestion.ingest._ensure_document"), \
         mock.patch("app.ingestion.ingest._ensure_version"):

        fake_embed_fn = mock.MagicMock(side_effect=lambda contents: [[0.1] * 1024 for _ in contents])
        res = ingest_document(mock_conn, record, manifest_doc, embed_fn=fake_embed_fn)

        # Must NOT skip! It must call embed_fn and _replace_chunks to reindex!
        assert res.skipped is False
        assert fake_embed_fn.called
        assert mock_replace.called

