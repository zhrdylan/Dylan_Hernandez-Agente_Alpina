import pytest
from app.agent.validation import validate_citations, validate_answer_payload
from app.agent.prompts import ABSTENTION
from app.agent.graph import answer_node, verify_node


def test_no_partial_document_id_matching():
    # Evidence contains C4
    results = [
        {
            "document_id": "C4",
            "document_title": "Estados Financieros Separados 2025",
            "page_start": 2,
            "page_end": 2,
            "content": "Los ingresos ordinarios sumaron $2.458 B en 2025.",
            "version": "2025",
            "source_url": "https://example.com/c4.pdf",
        }
    ]

    # Citation with partial ID "C" or "C40" must NOT match "C4"
    invalid_citations = [
        {"document_id": "C", "page": 2, "quote": ""},
        {"document_id": "C40", "page": 2, "quote": ""},
    ]
    valid, issues = validate_citations(invalid_citations, results)
    assert len(valid) == 0


def test_quote_page_binding():
    # Fragment on page 9
    results = [
        {
            "document_id": "C4",
            "document_title": "Estados Financieros Separados 2025",
            "page_start": 9,
            "page_end": 9,
            "content": "La utilidad neta consolidada alcanzó $114.367 millones.",
            "version": "2025",
            "source_url": "https://example.com/c4.pdf",
        }
    ]

    # Citation erroneously claims page 2, but provides quote from page 9
    citations = [
        {
            "document_id": "C4",
            "page": 2,
            "quote": "utilidad neta consolidada",
        }
    ]
    valid, issues = validate_citations(citations, results)
    assert len(valid) == 1
    # Must correctly bind to the actual page of the evidence (page 9), not page 2
    assert valid[0]["page"] == 9


def test_quote_mismatch_rejected():
    results = [
        {
            "document_id": "C4",
            "document_title": "Estados Financieros Separados 2025",
            "page_start": 2,
            "page_end": 2,
            "content": "Los ingresos ordinarios sumaron $2.458 B en 2025.",
            "version": "2025",
            "source_url": "https://example.com/c4.pdf",
        }
    ]
    # Quote does not exist in evidence
    citations = [
        {
            "document_id": "C4",
            "page": 2,
            "quote": "Ventas de queso alcanzaron 500 millones",
        }
    ]
    valid, issues = validate_citations(citations, results)
    # Must reject fabricated quote
    assert len(valid) == 0


def test_validate_answer_payload_no_auto_assignment():
    results = [
        {
            "document_id": "C4",
            "document_title": "Estados Financieros Separados 2025",
            "page_start": 2,
            "page_end": 2,
            "content": "Los ingresos ordinarios sumaron $2.458 B en 2025.",
            "version": "2025",
            "source_url": "https://example.com/c4.pdf",
        }
    ]
    # LLM gave an answer but provided zero citations
    payload = {
        "answer": "Las ventas fueron positivas este año.",
        "citations": [],
    }
    validated = validate_answer_payload(payload, results)
    # Must abstain! Never auto-assign results[0] as citation
    assert validated["abstained"] is True
    assert validated["answer"] == ABSTENTION
    assert len(validated["citations"]) == 0


def test_verify_node_unverified_on_abstention_and_guardrail():
    # Abstention
    state_abst = {
        "answer": ABSTENTION,
        "abstained": True,
        "citations": [],
        "needs_documents": True,
    }
    v_abst = verify_node(state_abst)
    assert v_abst["verified"] is False
    assert v_abst["abstained"] is True

    # Guardrail
    state_guard = {
        "answer": "Solicitud fuera del alcance oficial de Alpina.",
        "category": "guardrail",
        "needs_documents": False,
    }
    v_guard = verify_node(state_guard)
    assert v_guard["verified"] is False
