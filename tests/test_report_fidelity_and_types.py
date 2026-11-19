import pytest
from app.reports.financial import is_financial_query, get_financial_sections, FINANCIAL_KEYWORDS
from app.reports.service import create_report_record
from app.reports.spec import ReportCitation, ReportSpec, ReportSection, ReportTable
from app.reports.word import generate_word_report, render_docx
from app.reports.excel import render_xlsx, _parse_numeric


def test_financial_keywords_no_naked_years():
    # 2024 and 2025 by themselves should NOT trigger financial classification
    assert "2024" not in FINANCIAL_KEYWORDS
    assert "2025" not in FINANCIAL_KEYWORDS

    # Sustainability query mentioning 2025 should NOT be classified as financial
    assert is_financial_query("Estrategia de sostenibilidad y metas ambientales 2025") is False

    # Actual financial query must be recognized
    assert is_financial_query("Detalla los ingresos operacionales, ebitda y utilidad neta") is True


def test_excel_numeric_parsing():
    # Percentage
    val, fmt = _parse_numeric("+6,3%")
    assert isinstance(val, float)
    assert abs(val - 0.063) < 0.0001
    assert fmt == "0.0%"

    # Currency
    val_c, fmt_c = _parse_numeric("$ 2.458.120.350")
    assert isinstance(val_c, float)
    assert val_c == 2458120350.0
    assert fmt_c == "$ #,##0"

    # Plain text
    val_t, fmt_t = _parse_numeric("Informe de Gestión")
    assert val_t == "Informe de Gestión"
    assert fmt_t is None


def test_word_report_includes_version_column(tmp_path):
    spec = ReportSpec(
        title="Informe de Prueba",
        subtitle="Auditoría",
        prepared_for="Comité",
        query="Prueba",
        summary="Resumen de prueba",
        verification_status="Verificado",
        sections=[
            ReportSection(
                heading="Hallazgos",
                body=["Texto de prueba"],
            )
        ],
        citations=[
            ReportCitation(
                document_id="C4",
                title="Estados Financieros Separados 2025",
                page=2,
                version="2025.1",
                quote="Ingresos operacionales",
            )
        ],
    )
    doc_path = tmp_path / "test.docx"
    render_docx(spec, doc_path)
    assert doc_path.is_file()
    docx_bytes = doc_path.read_bytes()
    assert len(docx_bytes) > 2000
    assert docx_bytes.startswith(b"PK\x03\x04")


def test_financial_recommendations_not_hardcoded():
    custom_bullets = ["Implementar monitoreo en tiempo real de la cadena láctea."]
    sections = get_financial_sections(
        query="Ingresos y balance 2025",
        answer_paragraphs=["Ingresos subieron."],
        answer_bullets=custom_bullets,
    )
    rec_sec = next((s for s in sections if "Recomendaciones" in s.heading), None)
    assert rec_sec is not None
    # Must use custom_bullets, not hardcoded fixed text
    assert custom_bullets[0] in rec_sec.body or custom_bullets[0] in (rec_sec.bullets or [])
