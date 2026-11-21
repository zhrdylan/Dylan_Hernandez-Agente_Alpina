from uuid import uuid4

import pytest
from docx import Document
from openpyxl import load_workbook
from pypdfium2 import PdfDocument

from app.reports.financial import financial_statement_answer, is_financial_query, FINANCIAL_KEYWORDS
from app.reports.generator import generate_report
from app.reports.service import _report_spec, create_report_record
from app.reports.spec import ReportCitation, ReportSpec, ReportSection, ReportTable
from app.reports.word import render_docx
from app.reports.excel import render_xlsx, _parse_numeric
from app.db.connection import connect


def test_financial_keywords_no_naked_years():
    # 2024 and 2025 by themselves should NOT trigger financial classification
    assert "2024" not in FINANCIAL_KEYWORDS
    assert "2025" not in FINANCIAL_KEYWORDS

    # Sustainability query mentioning 2025 should NOT be classified as financial
    assert is_financial_query("Estrategia de sostenibilidad y metas ambientales 2025") is False

    # Actual financial query must be recognized
    assert is_financial_query("Detalla los ingresos operacionales, ebitda y utilidad neta") is True
    assert is_financial_query("Un envase costoso y resistente") is False
    assert is_financial_query("Revisión del P&L") is True


@pytest.mark.parametrize("category", ["regulatory", "product"])
def test_quality_report_has_the_n11_title(category):
    citation = ReportCitation(document_id="N11", title="Política de Calidad de Alpina", page=1)
    spec = _report_spec("Política de calidad", "Texto de la política.", [citation], category, "Citas OK", False)
    assert spec.title == "Informe de calidad e inocuidad"


def test_deleting_chat_during_report_render_releases_transaction_and_discards_file(monkeypatch, tmp_path):
    from app.reports import service

    owner = f"owner_{uuid4().hex}"
    with connect(session_id=owner) as conn:
        chat_id = conn.execute("insert into public.chats (session_id) values (%s) returning id", (owner,)).fetchone()[0]
    paths = []

    def render_after_chat_is_deleted(spec, report_type):
        with connect(session_id=owner) as conn:
            conn.execute("set local lock_timeout = '1s'")
            assert conn.execute("delete from public.chats where id = %s", (chat_id,)).rowcount == 1
        artifact = generate_report(spec, report_type, output_root=tmp_path)
        paths.append(artifact.path)
        return artifact

    monkeypatch.setattr(service, "generate_report", render_after_chat_is_deleted)
    try:
        with pytest.raises(ValueError, match="chat del reporte no está disponible"):
            create_report_record(str(chat_id), "Tema de prueba", "Datos de prueba.", [], session_id=owner, user_provided=True)
        assert paths and not paths[0].exists()
    finally:
        with connect(session_id=owner) as conn:
            conn.execute("delete from public.chats where id = %s", (chat_id,))


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


def test_word_report_keeps_citation_metadata_out_of_the_document(tmp_path):
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
    document = Document(doc_path)
    text = " ".join([p.text for p in document.paragraphs] + [
        cell.text for table in document.tables for row in table.rows for cell in row.cells
    ])
    assert "Texto de prueba" in text
    assert all(value not in text for value in ("Estados Financieros Separados 2025", "2025.1", "Ingresos operacionales"))


def test_financial_report_preserves_the_cited_table(tmp_path):
    answer = (
        "- Cifras en miles de pesos\n\n"
        "| Métrica | 2025 consolidado | 2024 consolidado |\n"
        "| --- | --- | --- |\n"
        "| Ingresos | 1,234,567 | 1,100,000 |\n"
        "| Costo de ventas | (210,500) | (200,000) |"
    )
    spec = _report_spec(
        "Resultados financieros 2025",
        answer,
        [ReportCitation(document_id="C5", title="Estados financieros consolidados", page=1)],
        "corporate", "Citas OK", False,
    )
    assert spec.sections[0].bullets == ["Cifras en miles de pesos"]
    assert spec.sections[0].table.rows[0] == ["Ingresos", "1,234,567", "1,100,000"]

    workbook = load_workbook(render_xlsx(spec, tmp_path / "resultado.xlsx"))
    try:
        amounts = [value for row in workbook["Datos"].values for value in row if isinstance(value, int)]
        assert 1234567 in amounts
        assert -210500 in amounts
        assert "$ 2.458 B" not in {
            value for sheet in workbook for row in sheet.values for value in row
        }
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
    spec = _report_spec(
        "Reporte del costo de ventas de 2024",
        "No se encontraron cifras oficiales desglosadas para este concepto.",
        [ReportCitation(document_id="C4", title="Estados financieros separados", page=1, version="2025")],
        "corporate", "Citas OK", False,
    )
    assert "2024" in spec.title and "2025" not in spec.title
    assert all(sec.table is None for sec in spec.sections)


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


def test_report_preserves_cells_from_a_pasted_spreadsheet(tmp_path):
    spec = _report_spec("Inventario", "Producto\tUnidades\tObservaciones\nAvena\t12\t", [], "general", "", True)
    workbook = load_workbook(render_xlsx(spec, tmp_path / "pegado.xlsx"))
    try:
        assert tuple(cell.value for cell in workbook["Datos"][3]) == ("Avena", 12, None, None)
    finally:
        workbook.close()


@pytest.mark.parametrize("report_type", ["pdf", "docx", "xlsx"])
def test_exports_render_nonnumeric_and_numeric_markdown_table_without_sources(tmp_path, report_type):
    citation = ReportCitation(
        document_id="N11",
        title="Matriz reservada de planta",
        page=7,
        version="Version reservada",
        source_url="https://example.invalid/evidencia-privada.pdf",
    )
    answer = (
        "## Seguimiento de producción\n"
        "Según la Matriz reservada de planta, el control es mensual. [FUENTE 1]\n\n"
        "Producto | EAN | Cantidad (g) | Rendimiento | Etiqueta\n"
        "--- | --- | ---: | ---: | ---\n"
        "**Avena** \\| Alpina | 0123456789012 | 12,50 | +6,30% | =1+2\n\n"
        "- Registrar la medición.\n\n"
        "### Fuentes oficiales citadas\n"
        "- [Abrir archivo](https://example.invalid/evidencia-privada.pdf) (N11, pág. 7)\n\n"
        "## Cierre de producción\n"
        "Conservar los registros."
    )
    spec = _report_spec("Producción", answer, [citation], "general", "Citas OK", False)
    artifact = generate_report(spec, report_type, output_root=tmp_path)

    if report_type == "pdf":
        with PdfDocument(artifact.path) as pdf:
            text = " ".join(page.get_textpage().get_text_range() for page in pdf)
        assert "12,50" in text
    elif report_type == "docx":
        document = Document(artifact.path)
        text = " ".join([p.text for p in document.paragraphs] + [
            cell.text for table in document.tables for row in table.rows for cell in row.cells
        ])
        assert document.tables[1].cell(1, 0).text == "Avena | Alpina"
        assert document.tables[1].cell(1, 2).text == "12,50"
    else:
        workbook = load_workbook(artifact.path)
        try:
            assert workbook.sheetnames == ["Resumen", "Datos"]
            row = workbook["Datos"][3]
            assert [cell.value for cell in row] == ["Avena | Alpina", "0123456789012", 12.5, 0.063, "=1+2"]
            assert row[4].data_type == "s"
            text = " ".join(str(value) for sheet in workbook for values in sheet.values for value in values)
        finally:
            workbook.close()
    assert "Avena | Alpina" in text
    assert "control es mensual" in text
    assert "Conservar los registros" in text
    assert all(value not in text for value in (
        citation.title, citation.source_url, citation.document_id, "FUENTE 1", "Fuentes oficiales"
    ))
