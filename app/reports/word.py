from __future__ import annotations

import io
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor

from app.core.markdown import inline_runs, plain_markdown
from app.reports.spec import ReportSection, ReportSpec, ReportTable

# Paleta corporativa Alpina
COLOR_PRIMARY_BLUE = RGBColor(1, 82, 209)     # #0152D1
COLOR_NAVY = RGBColor(11, 31, 58)             # #0B1F3A
COLOR_INK = RGBColor(15, 34, 61)              # #0F223D
COLOR_MUTED = RGBColor(100, 116, 139)         # #64748B

HEX_PRIMARY_BLUE = "0152D1"
HEX_LIGHT_BLUE = "EAF1FB"
HEX_ZEBRA = "F8FAFC"
HEX_GRID = "DCE5F0"
HEX_WHITE = "FFFFFF"


def _set_cell_background(cell, hex_color: str) -> None:
    """Aplica color de fondo sólido a una celda de tabla."""
    shading_elm = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>')
    cell._tc.get_or_add_tcPr().append(shading_elm)


def _set_cell_margins(cell, top=100, bottom=100, left=150, right=150) -> None:
    """Configura los márgenes internos (padding) de una celda."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement("w:tcMar")
    for m, val in [("w:top", top), ("w:bottom", bottom), ("w:left", left), ("w:right", right)]:
        node = OxmlElement(m)
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        tcMar.append(node)
    tcPr.append(tcMar)


def _set_table_borders(table) -> None:
    """Aplica bordes sutiles y limpios a toda la tabla."""
    tblPr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        f'  <w:top w:val="single" w:sz="4" w:space="0" w:color="{HEX_GRID}"/>'
        f'  <w:bottom w:val="single" w:sz="6" w:space="0" w:color="{HEX_PRIMARY_BLUE}"/>'
        f'  <w:left w:val="none"/>'
        f'  <w:right w:val="none"/>'
        f'  <w:insideH w:val="single" w:sz="4" w:space="0" w:color="{HEX_GRID}"/>'
        f'  <w:insideV w:val="none"/>'
        f"</w:tblBorders>"
    )
    tblPr.append(borders)


def _add_formatted_run(paragraph, text: str, font_size=10.5, color=COLOR_INK):
    for value, styles in inline_runs(text):
        run = paragraph.add_run(value)
        run.font.name = "Consolas" if "code" in styles else "Segoe UI"
        run.font.size = Pt(font_size)
        run.font.color.rgb = color
        run.bold = "strong" in styles
        run.italic = "em" in styles
        run.font.strike = "s" in styles


def _add_table(doc, tbl: ReportTable) -> None:
    if tbl.title:
        doc.add_heading(plain_markdown(tbl.title), level=2)
    table = doc.add_table(rows=1, cols=len(tbl.columns))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _set_table_borders(table)
    table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))

    for index, header in enumerate(tbl.columns):
        cell = table.rows[0].cells[index]
        _set_cell_background(cell, HEX_PRIMARY_BLUE)
        _set_cell_margins(cell, top=100, bottom=100, left=120, right=120)
        run = cell.paragraphs[0].add_run(plain_markdown(header))
        run.font.name = "Segoe UI"
        run.font.size = Pt(9.0)
        run.font.bold = True
        run.font.color.rgb = RGBColor(255, 255, 255)

    for index, values in enumerate(tbl.iter_rows()):
        for cell, text in zip(table.add_row().cells, values, strict=True):
            _set_cell_background(cell, HEX_ZEBRA if index % 2 else HEX_WHITE)
            _set_cell_margins(cell, top=80, bottom=80, left=120, right=120)
            _add_formatted_run(cell.paragraphs[0], text, font_size=9.0)

    if tbl.notes:
        note = doc.add_paragraph(style="Caption")
        _add_formatted_run(note, tbl.notes, font_size=8.0, color=COLOR_MUTED)


def render_docx(spec: ReportSpec, path: Path | io.BytesIO | str) -> Path | io.BytesIO:
    """Genera un documento Word (.docx) formal, ejecutivo y corporativo para Alpina."""
    if isinstance(path, (str, Path)):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    doc.core_properties.title = spec.title
    doc.core_properties.subject = spec.subtitle
    doc.core_properties.author = "Agente Alpina"

    # Configuración de página: A4 con márgenes ejecutivos de 2.54 cm
    for section in doc.sections:
        section.page_width = Inches(8.27)
        section.page_height = Inches(11.69)
        section.top_margin = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

        # Encabezado institucional
        header_p = section.header.paragraphs[0]
        header_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        h_run = header_p.add_run("ALPINA S.A.S. BIC  ·  INFORME")
        h_run.font.name = "Segoe UI"
        h_run.font.size = Pt(8.0)
        h_run.font.bold = True
        h_run.font.color.rgb = COLOR_MUTED

        # Pie de página
        footer_p = section.footer.paragraphs[0]
        f_run1 = footer_p.add_run(spec.footer)
        f_run1.font.name = "Segoe UI"
        f_run1.font.size = Pt(8.0)
        f_run1.font.color.rgb = COLOR_MUTED

    # Membrete y Título Principal
    p_pre = doc.add_paragraph()
    p_pre.paragraph_format.space_before = Pt(0)
    p_pre.paragraph_format.space_after = Pt(4)
    run_pre = p_pre.add_run("ALPINA")
    run_pre.font.name = "Segoe UI"
    run_pre.font.size = Pt(9.0)
    run_pre.font.bold = True
    run_pre.font.color.rgb = COLOR_PRIMARY_BLUE

    p_title = doc.add_paragraph(style="Title")
    p_title.paragraph_format.space_before = Pt(2)
    p_title.paragraph_format.space_after = Pt(4)
    run_title = p_title.add_run(spec.title)
    run_title.font.name = "Segoe UI"
    run_title.font.size = Pt(21.0)
    run_title.font.bold = True
    run_title.font.color.rgb = COLOR_NAVY

    if spec.subtitle:
        p_sub = doc.add_paragraph()
        p_sub.paragraph_format.space_before = Pt(0)
        p_sub.paragraph_format.space_after = Pt(14)
        run_sub = p_sub.add_run(spec.subtitle)
        run_sub.font.name = "Segoe UI"
        run_sub.font.size = Pt(11.0)
        run_sub.font.italic = True
        run_sub.font.color.rgb = COLOR_MUTED

    # Tarjeta de Metadatos Ejecutivos
    meta_table = doc.add_table(rows=1, cols=2)
    meta_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    meta_table.autofit = False
    _set_table_borders(meta_table)

    kpis = [
        ("DESTINATARIO", spec.prepared_for or "Alta Dirección"),
        ("FECHA DE EMISIÓN", spec.report_date.strftime("%d/%m/%Y")),
    ]

    for idx, (lbl, val) in enumerate(kpis):
        cell = meta_table.cell(0, idx)
        _set_cell_background(cell, HEX_LIGHT_BLUE)
        _set_cell_margins(cell, top=80, bottom=80, left=100, right=100)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(2)
        r_lbl = p.add_run(f"{lbl}\n")
        r_lbl.font.name = "Segoe UI"
        r_lbl.font.size = Pt(7.5)
        r_lbl.font.bold = True
        r_lbl.font.color.rgb = COLOR_MUTED

        r_val = p.add_run(val)
        r_val.font.name = "Segoe UI"
        r_val.font.size = Pt(9.5)
        r_val.font.bold = True
        r_val.font.color.rgb = COLOR_NAVY

    p_spacer = doc.add_paragraph()
    p_spacer.paragraph_format.space_before = Pt(12)
    p_spacer.paragraph_format.space_after = Pt(0)

    # Resumen Ejecutivo
    if spec.summary:
        h_sum = doc.add_paragraph(style="Heading 1")
        h_sum.paragraph_format.space_before = Pt(14)
        h_sum.paragraph_format.space_after = Pt(6)
        r_sum = h_sum.add_run("Resumen ejecutivo")
        r_sum.font.name = "Segoe UI"
        r_sum.font.size = Pt(13.0)
        r_sum.font.bold = True
        r_sum.font.color.rgb = COLOR_PRIMARY_BLUE

        # Recuadro sombreado para el resumen
        sum_table = doc.add_table(rows=1, cols=1)
        sum_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        sum_cell = sum_table.cell(0, 0)
        _set_cell_background(sum_cell, HEX_LIGHT_BLUE)
        _set_cell_margins(sum_cell, top=140, bottom=140, left=200, right=200)

        # Borde izquierdo grueso azul
        tcPr = sum_cell._tc.get_or_add_tcPr()
        borders = parse_xml(
            f'<w:tcBorders {nsdecls("w")}>'
            f'  <w:left w:val="single" w:sz="24" w:space="0" w:color="{HEX_PRIMARY_BLUE}"/>'
            f'  <w:top w:val="none"/>'
            f'  <w:right w:val="none"/>'
            f'  <w:bottom w:val="none"/>'
            f"</w:tcBorders>"
        )
        tcPr.append(borders)

        sum_p = sum_cell.paragraphs[0]
        sum_p.paragraph_format.line_spacing = 1.15
        sum_p.paragraph_format.space_after = Pt(0)
        _add_formatted_run(sum_p, spec.summary, font_size=10.0, color=COLOR_INK)

    for section in spec.sections:
        if section.heading:
            heading = doc.add_heading(level=1)
            _add_formatted_run(heading, section.heading, font_size=13, color=COLOR_PRIMARY_BLUE)
            for run in heading.runs:
                run.bold = True

        for text in section.body:
            paragraph = doc.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(6)
            paragraph.paragraph_format.line_spacing = 1.15
            _add_formatted_run(paragraph, text)

        for text in section.bullets:
            paragraph = doc.add_paragraph(style="List Bullet")
            paragraph.paragraph_format.space_after = Pt(3)
            _add_formatted_run(paragraph, text, font_size=10.0)

        if section.table:
            for table in section.table.printable_parts():
                _add_table(doc, table)

    if isinstance(path, (str, Path)):
        doc.save(str(path))
        return Path(path)
    else:
        doc.save(path)
        return path


def generate_word_report(
    title: str,
    topic: str,
    sections: list[dict | ReportSection],
    data_tables: list[dict | ReportTable] = None,
    recommendations: list[str] = None,
    prepared_for: str = "Alta Dirección Alpina",
    report_date: date = None,
) -> bytes:
    """Genera directamente un informe ejecutivo Word (.docx) y devuelve los bytes resultantes."""
    r_date = report_date or date.today()
    parsed_sections: list[ReportSection] = []

    for s in sections:
        if isinstance(s, ReportSection):
            parsed_sections.append(s)
        elif isinstance(s, dict):
            parsed_sections.append(
                ReportSection(
                    heading=s.get("heading") or "Sección Ejecutiva",
                    body=s.get("body") if isinstance(s.get("body"), list) else ([s.get("body")] if s.get("body") else []),
                    bullets=s.get("bullets") or [],
                )
            )

    if recommendations:
        parsed_sections.append(
            ReportSection(
                heading="Recomendaciones Estratégicas para la Toma de Decisiones",
                body=["A continuación se detallan las directrices clave fundamentadas en la información oficial analizada:"],
                bullets=recommendations,
            )
        )

    if data_tables:
        for idx, dt in enumerate(data_tables):
            if isinstance(dt, ReportTable):
                parsed_sections.append(
                    ReportSection(heading=dt.title or f"Tabla de Datos {idx + 1}", table=dt)
                )
            elif isinstance(dt, dict):
                tbl = ReportTable(
                    title=dt.get("title") or "Datos Tabulados",
                    columns=dt.get("columns") or [],
                    rows=dt.get("rows") or [],
                    notes=dt.get("notes") or "",
                )
                parsed_sections.append(
                    ReportSection(heading=tbl.title, table=tbl)
                )

    spec = ReportSpec(
        title=title or "Informe Ejecutivo Alpina",
        subtitle=f"Análisis estratégico sobre: {topic[:80]}" if topic else "Documento Corporativo Oficial",
        prepared_for=prepared_for,
        report_date=r_date,
        query=topic,
        summary="",
        sections=parsed_sections,
        citations=[],
    )

    buffer = io.BytesIO()
    render_docx(spec, buffer)
    return buffer.getvalue()
