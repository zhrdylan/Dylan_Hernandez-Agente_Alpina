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


def test_r01_contradicted_number_rejected_and_abstained():
    """R01: Fuente dice 12 unidades y modelo responde 999 unidades -> NO debe publicar 999 verificado."""
    results = [
        {
            "document_id": "C1",
            "document_title": "Informe de Gestión 2026",
            "page_start": 4,
            "page_end": 4,
            "content": "En la planta Sopó se produjeron 12 unidades durante la prueba piloto.",
            "version": "2026",
            "source_url": "https://example.com/c1.pdf",
        }
    ]

    # Modelo devuelve 999 unidades pero adjunta la frase válida de la fuente
    payload_999 = {
        "answer": "En la planta Sopó se produjeron 999 unidades durante la prueba piloto.",
        "citations": [
            {
                "document_id": "C1",
                "page": 4,
                "quote": "se produjeron 12 unidades",
            }
        ],
    }

    validated_999 = validate_answer_payload(payload_999, results)
    # Debe rechazar la afirmación numérica contradictoria/no sustentada y abstenerse
    assert validated_999["abstained"] is True
    assert validated_999["answer"] == ABSTENTION
    assert len(validated_999["citations"]) == 0

    # Comprobar en verify_node
    state = {
        "answer": validated_999["answer"],
        "citations": validated_999["citations"],
        "abstained": validated_999["abstained"],
        "needs_documents": True,
        "category": "general",
    }
    v_out = verify_node(state)
    assert v_out["verified"] is False
    assert v_out["abstained"] is True


def test_r01_supported_number_verified():
    """R01: Fuente dice 12 unidades y respuesta dice 12 unidades -> Aprobado y verificado."""
    results = [
        {
            "document_id": "C1",
            "document_title": "Informe de Gestión 2026",
            "page_start": 4,
            "page_end": 4,
            "content": "En la planta Sopó se produjeron 12 unidades durante la prueba piloto.",
            "version": "2026",
            "source_url": "https://example.com/c1.pdf",
        }
    ]

    payload_12 = {
        "answer": "En la planta Sopó se produjeron 12 unidades durante la prueba piloto.",
        "citations": [
            {
                "document_id": "C1",
                "page": 4,
                "quote": "se produjeron 12 unidades",
            }
        ],
    }

    validated_12 = validate_answer_payload(payload_12, results)
    assert validated_12["abstained"] is False
    assert "12 unidades" in validated_12["answer"]
    assert len(validated_12["citations"]) == 1

    state = {
        "answer": validated_12["answer"],
        "citations": validated_12["citations"],
        "abstained": validated_12["abstained"],
        "needs_documents": True,
        "category": "general",
    }
    v_out = verify_node(state)
    assert v_out["verified"] is True
    assert v_out["abstained"] is False
    assert len(v_out["citations"]) == 1


def test_r02_general_category_retains_citations_when_needs_documents():
    """R02: category='general' con needs_documents=True conserva citas y estado verificado."""
    state = {
        "answer": "Las ventas de 2025 alcanzaron $2.458 B según los estados financieros oficiales.",
        "citations": [
            {
                "document_id": "C4",
                "title": "Estados Financieros Separados 2025",
                "page": 2,
                "quote": "ingresos ordinarios sumaron $2.458 B",
            }
        ],
        "abstained": False,
        "needs_documents": True,
        "category": "general",
    }
    v_out = verify_node(state)
    assert v_out["verified"] is True
    assert v_out["abstained"] is False
    assert len(v_out["citations"]) == 1
    assert v_out["citations"][0]["document_id"] == "C4"


def test_r02_general_category_abstains_correctly_when_no_citations():
    """R02: category='general' con needs_documents=True y cero citas devuelve abstención correcta."""
    state = {
        "answer": "No consta en los documentos.",
        "citations": [],
        "abstained": False,
        "needs_documents": True,
        "category": "general",
    }
    v_out = verify_node(state)
    assert v_out["verified"] is False
    assert v_out["abstained"] is True
    assert v_out["answer"] == ABSTENTION
    assert len(v_out["citations"]) == 0
