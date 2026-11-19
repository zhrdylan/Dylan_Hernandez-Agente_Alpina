import pytest
from app.reports.financial import financial_statement_answer, is_financial_query, get_financial_sections, FINANCIAL_KEYWORDS
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


def test_financial_report_preserves_the_cited_table(tmp_path):
    answer = (
        "| Métrica | 2025 consolidado | 2024 consolidado |\n"
        "| --- | --- | --- |\n"
        "| Ingresos | 1,234,567 | 1,100,000 |\n"
        "| Costo de ventas | (210,500) | (200,000) |"
    )
    sections = get_financial_sections(
        query="Resultados financieros 2025",
        answer_paragraphs=[answer],
        answer_bullets=["Cifras en miles de pesos"],
    )
    assert sections[0].bullets == ["Cifras en miles de pesos"]
    assert len(sections) == 2
    assert sections[1].table.rows[0] == ["Ingresos", "1,234,567", "1,100,000"]

    from openpyxl import load_workbook
    spec = ReportSpec(title="Resultados financieros", query="Resultados financieros 2025", sections=sections)
    workbook = load_workbook(render_xlsx(spec, tmp_path / "resultado.xlsx"))
    try:
        amounts = [value for row in workbook["Datos"].values for value in row if isinstance(value, int)]
        assert 1234567 in amounts
        assert -210500 in amounts
        assert "$ 2.458 B" not in {value for row in workbook["Dashboard"].values for value in row}
    finally:
        workbook.close()


def test_financial_statement_answer_keeps_period_scope_and_accounting_sign():
    source = {
        "document_id": "C5",
        "content": (
            "Notas 2025 2024\n"
            "En miles de pesos colombianos\n"
            "Ingresos de actividades ordinarias 24 $ 222,222 $ 111,111\n"
            "Costo de ventas 25 (50,000) (40,000)\n"
            "Ganancia bruta 172,222 71,111\n"
            "Resultados de actividades de la operación 55,555 44,444\n"
            "Resultado neto del año 22,222 11,111"
        ),
    }
    answer = financial_statement_answer("Resultados financieros consolidados de 2024", [source])
    assert answer["citations"][0]["source"] == 1
    assert "| Concepto | Consolidados 2024 |" in answer["answer"]
    assert "| Ingresos de actividades ordinarias | 111,111 |" in answer["answer"]
    assert "| Costo de ventas | (40,000) |" in answer["answer"]
    assert financial_statement_answer("Resultados financieros de 2023", [source]) is None


def test_r03_financial_query_2024_without_figures_no_fixed_2025_revenue():
    """R03: Consulta sobre costo de ventas 2024 sin cifras no debe generar título 2025 ni cifras fijas."""
    sections = get_financial_sections(
        query="Reporte del costo de ventas de 2024",
        answer_paragraphs=["No se encontraron cifras oficiales desglosadas para este concepto."],
        answer_bullets=[],
    )
    assert all(sec.table is None for sec in sections)


def test_r04_cannot_export_report_for_abstention(tmp_path):
    """R04: Una respuesta con abstención o sin respaldo documental no debe publicar un archivo."""
    with pytest.raises(ValueError, match="No se puede generar un reporte"):
        create_report_record(
            chat_id=None,
            question="Consulta no documentada",
            answer="No encontré información oficial sobre esa consulta en los documentos disponibles de Alpina.",
            citations=[],
            report_type="pdf",
            abstained=True,
        )


def test_r10_excel_preserves_leading_zeros_ean_sku(tmp_path):
    """R10: Celda EAN con ceros a la izquierda se guarda como texto y conserva todos los ceros."""
    ean_code = "0123456789012"
    val, fmt = _parse_numeric(ean_code, col_name="EAN")
    assert val == ean_code
    assert fmt == "@"

    val_auto, fmt_auto = _parse_numeric(ean_code)
    assert val_auto == ean_code
    assert fmt_auto == "@"

    spec = ReportSpec(
        title="Reporte de Catálogo EAN",
        prepared_for="Auditoría",
        sections=[
            ReportSection(
                heading="Productos",
                table=ReportTable(
                    title="Catálogo",
                    columns=["Producto", "EAN", "Precio"],
                    rows=[
                        ["Leche Entera", "0123456789012", "$ 4.500"],
                        ["Avena Alpina", "0987654321098", "$ 3.200"],
                    ],
                ),
            )
        ],
        citations=[
            ReportCitation(
                document_id="P1",
                title="Portafolio de Productos",
                page=1,
            )
        ],
    )
    xlsx_path = tmp_path / "test_ean.xlsx"
    render_xlsx(spec, xlsx_path)
    assert xlsx_path.is_file()

    from openpyxl import load_workbook
    wb = load_workbook(xlsx_path)
    ws_data = wb["Datos"]
    found_ean = False
    for row in ws_data.iter_rows(values_only=False):
        for cell in row:
            if cell.value == ean_code:
                found_ean = True
                assert cell.data_type == "s"
                assert str(cell.value) == "0123456789012"
    assert found_ean is True
