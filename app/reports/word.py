from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor

from app.reports.spec import ReportCitation, ReportSection, ReportSpec, ReportTable

# Paleta corporativa Alpina
COLOR_PRIMARY_BLUE = RGBColor(1, 82, 209)     # #0152D1
COLOR_NAVY = RGBColor(11, 31, 58)             # #0B1F3A
COLOR_INK = RGBColor(15, 34, 61)              # #0F223D
COLOR_MUTED = RGBColor(100, 116, 139)         # #64748B
COLOR_SUCCESS = RGBColor(5, 150, 105)         # #059669

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


def _strip_markdown(text: str) -> str:
    """Limpia asteriscos y marcas de markdown para títulos."""
    if not text:
        return ""
    cleaned = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", str(text))
    cleaned = re.sub(r"_{1,3}(.*?)_{1,3}", r"\1", cleaned)
    cleaned = cleaned.replace("**", "").replace("*", "")
    return cleaned.strip()


def _add_formatted_run(paragraph, text: str, font_name="Segoe UI", font_size=10.5, color=COLOR_INK, bold=False, italic=False):
    """Parsea texto con formato **negrita** o *cursiva* básico y agrega runs con estilo."""
    pattern = re.compile(r"(\*\*.*?\*\*|\*.*?\*|`.*?`)")
    tokens = pattern.split(text)

    for token in tokens:
        if not token:
            continue
        run = paragraph.add_run()
        run.font.name = font_name
        run.font.size = Pt(font_size)
        run.font.color.rgb = color

        if token.startswith("**") and token.endswith("**") and len(token) > 4:
            run.text = token[2:-2]
            run.bold = True
            run.italic = italic
        elif token.startswith("*") and token.endswith("*") and len(token) > 2:
            run.text = token[1:-1]
            run.bold = bold
            run.italic = True
        elif token.startswith("`") and token.endswith("`") and len(token) > 2:
            run.text = token[1:-1]
            run.font.name = "Consolas"
            run.font.size = Pt(font_size - 0.5)
        else:
            run.text = token
            run.bold = bold
            run.italic = italic


def render_docx(spec: ReportSpec, path: Path | io.BytesIO | str) -> Path | io.BytesIO:
    """Genera un documento Word (.docx) formal, ejecutivo y corporativo para Alpina."""
    if isinstance(path, (str, Path)):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()

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
        h_run = header_p.add_run("ALPINA S.A.S. BIC  ·  INFORME EJECUTIVO OFICIAL")
        h_run.font.name = "Segoe UI"
        h_run.font.size = Pt(8.0)
        h_run.font.bold = True
        h_run.font.color.rgb = COLOR_MUTED

        # Pie de página con numeración y fecha
        footer_p = section.footer.paragraphs[0]
        f_run1 = footer_p.add_run(f"Informe confidencial  ·  {spec.report_date.strftime('%d/%m/%Y')}  ·  Alta Dirección")
        f_run1.font.name = "Segoe UI"
        f_run1.font.size = Pt(8.0)
        f_run1.font.color.rgb = COLOR_MUTED

    # Membrete y Título Principal
    p_pre = doc.add_paragraph()
    p_pre.paragraph_format.space_before = Pt(0)
    p_pre.paragraph_format.space_after = Pt(4)
    run_pre = p_pre.add_run("DOCUMENTO DE ALTA DIRECCIÓN  ·  SISTEMA CORPORATIVO ALPINA")
    run_pre.font.name = "Segoe UI"
    run_pre.font.size = Pt(9.0)
    run_pre.font.bold = True
    run_pre.font.color.rgb = COLOR_PRIMARY_BLUE

    p_title = doc.add_paragraph()
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
    meta_table = doc.add_table(rows=1, cols=4)
    meta_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    meta_table.autofit = False
    _set_table_borders(meta_table)

    kpis = [
        ("DESTINATARIO", spec.prepared_for or "Alta Dirección"),
        ("FECHA DE EMISIÓN", spec.report_date.strftime("%d/%m/%Y")),
        ("FUENTES CITADAS", f"{len(spec.citations)} Citas Oficiales"),
        ("TRAZABILIDAD", spec.verification_status or ("Abstención" if spec.abstained else "Verificado")),
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
        h_sum = doc.add_paragraph()
        h_sum.paragraph_format.space_before = Pt(14)
        h_sum.paragraph_format.space_after = Pt(6)
        r_sum = h_sum.add_run("1. Resumen Ejecutivo")
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

    # Secciones analíticas y tablas
    sec_num = 2
    for section in spec.sections:
        # Filtrar secciones burocráticas antiguas si existen
        clean_heading = section.heading.strip()
        if clean_heading in {"Consulta Solicitada", "Trazabilidad y Fundamentación Oficial"}:
            continue

        h_sec = doc.add_paragraph()
        h_sec.paragraph_format.space_before = Pt(16)
        h_sec.paragraph_format.space_after = Pt(6)
        r_sec = h_sec.add_run(f"{sec_num}. {clean_heading}")
        r_sec.font.name = "Segoe UI"
        r_sec.font.size = Pt(13.0)
        r_sec.font.bold = True
        r_sec.font.color.rgb = COLOR_PRIMARY_BLUE
        sec_num += 1

        for body_p in section.body:
            p_el = doc.add_paragraph()
            p_el.paragraph_format.space_before = Pt(0)
            p_el.paragraph_format.space_after = Pt(6)
            p_el.paragraph_format.line_spacing = 1.15
            _add_formatted_run(p_el, body_p, font_size=10.5, color=COLOR_INK)

        for bullet in section.bullets:
            b_el = doc.add_paragraph(style="List Bullet")
            b_el.paragraph_format.space_before = Pt(0)
            b_el.paragraph_format.space_after = Pt(3)
            b_el.paragraph_format.line_spacing = 1.15
            _add_formatted_run(b_el, bullet, font_size=10.0, color=COLOR_INK)

        # Tablas de datos si la sección las incluye
        if section.table and section.table.rows:
            tbl = section.table
            p_tbl_title = doc.add_paragraph()
            p_tbl_title.paragraph_format.space_before = Pt(8)
            p_tbl_title.paragraph_format.space_after = Pt(4)
            r_tt = p_tbl_title.add_run(tbl.title or "Datos Tabulados Oficiales")
            r_tt.font.name = "Segoe UI"
            r_tt.font.size = Pt(10.5)
            r_tt.font.bold = True
            r_tt.font.color.rgb = COLOR_NAVY

            t_elem = doc.add_table(rows=len(tbl.rows) + 1, cols=len(tbl.columns))
            t_elem.alignment = WD_TABLE_ALIGNMENT.CENTER
            _set_table_borders(t_elem)

            # Fila de encabezado
            for col_idx, col_name in enumerate(tbl.columns):
                h_cell = t_elem.cell(0, col_idx)
                _set_cell_background(h_cell, HEX_PRIMARY_BLUE)
                _set_cell_margins(h_cell, top=100, bottom=100, left=120, right=120)
                hp = h_cell.paragraphs[0]
                hp.paragraph_format.space_before = Pt(0)
                hp.paragraph_format.space_after = Pt(0)
                hr = hp.add_run(_strip_markdown(str(col_name)))
                hr.font.name = "Segoe UI"
                hr.font.size = Pt(9.0)
                hr.font.bold = True
                hr.font.color.rgb = RGBColor(255, 255, 255)

            # Filas de datos
            for row_idx, row_data in enumerate(tbl.rows):
                bg_color = HEX_ZEBRA if row_idx % 2 == 1 else HEX_WHITE
                for col_idx, cell_value in enumerate(row_data):
                    d_cell = t_elem.cell(row_idx + 1, col_idx)
                    _set_cell_background(d_cell, bg_color)
                    _set_cell_margins(d_cell, top=80, bottom=80, left=120, right=120)
                    dp = d_cell.paragraphs[0]
                    dp.paragraph_format.space_before = Pt(0)
                    dp.paragraph_format.space_after = Pt(0)
                    dr = dp.add_run(_strip_markdown(str(cell_value or "")))
                    dr.font.name = "Segoe UI"
                    dr.font.size = Pt(9.0)
                    dr.font.color.rgb = COLOR_INK

            if tbl.notes:
                p_note = doc.add_paragraph()
                p_note.paragraph_format.space_before = Pt(2)
                p_note.paragraph_format.space_after = Pt(8)
                rn = p_note.add_run(f"Nota: {tbl.notes}")
                rn.font.name = "Segoe UI"
                rn.font.size = Pt(8.0)
                rn.font.italic = True
                rn.font.color.rgb = COLOR_MUTED

    # Sección de Evidencias Documentales y Citas Oficiales
    if spec.citations:
        h_cit = doc.add_paragraph()
        h_cit.paragraph_format.space_before = Pt(18)
        h_cit.paragraph_format.space_after = Pt(6)
        r_cit = h_cit.add_run(f"{sec_num}. Fuentes Oficiales y Trazabilidad")
        r_cit.font.name = "Segoe UI"
        r_cit.font.size = Pt(13.0)
        r_cit.font.bold = True
        r_cit.font.color.rgb = COLOR_PRIMARY_BLUE

        cit_table = doc.add_table(rows=len(spec.citations) + 1, cols=5)
        cit_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        _set_table_borders(cit_table)

        # Encabezado de citas
        cit_headers = ["Doc ID", "Título del Documento Oficial", "Pág.", "Versión", "Evidencia Textual Auditada"]
        for c_idx, ch_text in enumerate(cit_headers):
            ch_cell = cit_table.cell(0, c_idx)
            _set_cell_background(ch_cell, HEX_PRIMARY_BLUE)
            _set_cell_margins(ch_cell, top=80, bottom=80, left=100, right=100)
            p = ch_cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(ch_text)
            r.font.name = "Segoe UI"
            r.font.size = Pt(8.5)
            r.font.bold = True
            r.font.color.rgb = RGBColor(255, 255, 255)

        for r_idx, citation in enumerate(spec.citations):
            bg_col = HEX_ZEBRA if r_idx % 2 == 1 else HEX_WHITE
            row_cells = [
                str(citation.document_id),
                str(citation.title or citation.document_id),
                str(citation.page or "1"),
                str(citation.version or "vigente"),
                f'"{citation.quote}"' if citation.quote else "Referencia oficial",
            ]
            for c_idx, val in enumerate(row_cells):
                cell = cit_table.cell(r_idx + 1, c_idx)
                _set_cell_background(cell, bg_col)
                _set_cell_margins(cell, top=70, bottom=70, left=100, right=100)
                p = cell.paragraphs[0]
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(0)
                r = p.add_run(val)
                r.font.name = "Segoe UI"
                r.font.size = Pt(8.5)
                r.font.color.rgb = COLOR_INK
                if c_idx == 0:
                    r.font.bold = True

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
                    notes=dt.get("notes"),
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
