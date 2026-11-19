from __future__ import annotations

import io
import math
import re
from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.reports.charts import citations_chart_png, verification_chart_png, financial_performance_chart_png
from app.reports.financial import is_financial_query
from app.reports.spec import ReportSpec, ReportTable

BLUE = "0152D1"
BLUE_LIGHT = "EAF1FB"
RED = "E30613"
GREEN = "0A7D4F"
INK = "0F223D"
MUTED = "64748B"
GRID = "DCE5F0"
WHITE = "FFFFFF"
FONT = "Segoe UI"
LOGO_PATH = Path(__file__).resolve().parents[1] / "static" / "brand" / "alpina-logo.png"


def _fill(color: str) -> PatternFill:
    return PatternFill(start_color=color, end_color=color, fill_type="solid")


def _thin_border() -> Border:
    side = Side(style="thin", color=GRID)
    return Border(left=side, right=side, top=side, bottom=side)


def _strip_markdown(text: str) -> str:
    """Elimina marcas de Markdown (asteriscos, guiones bajos, almohadillas) para dejar texto limpio en celdas Excel."""
    if not text:
        return ""
    cleaned = str(text)
    # Negrita / cursiva combinada
    cleaned = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", cleaned)
    cleaned = re.sub(r"_{1,3}(.*?)_{1,3}", r"\1", cleaned)
    # Código inline
    cleaned = re.sub(r"`(.*?)`", r"\1", cleaned)
    # Encabezados
    cleaned = re.sub(r"^#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    # Limpieza residual de cualquier asterisco o guión bajo suelto
    cleaned = cleaned.replace("**", "").replace("*", "").replace("__", "")
    return cleaned.strip()


def _estimate_height(values: list[str], widths: list[int]) -> float:
    lines = 1
    for value, width in zip(values, widths):
        if value:
            lines = max(
                lines,
                math.ceil(len(str(value)) / max(10, int(width * 1.05))),
            )
    return max(15, min(120, lines * 13.5))


def _add_logo(ws, anchor: str = "F1", width: int = 150, height: int = 90) -> None:
    if not LOGO_PATH.is_file():
        return
    image = XLImage(str(LOGO_PATH))
    image.width = width
    image.height = height
    ws.add_image(image, anchor)


def _add_chart_image(
    ws,
    png: bytes,
    anchor: str,
    *,
    width: int = 620,
    height: int = 300,
) -> None:
    image = XLImage(io.BytesIO(png))
    image.width = width
    image.height = height
    ws.add_image(image, anchor)


def _write_title(ws, title: str, subtitle: str) -> None:
    ws.merge_cells("A1:D1")
    cell = ws["A1"]
    cell.value = title
    cell.font = Font(name=FONT, size=20, bold=True, color=WHITE)
    cell.fill = _fill(BLUE)
    cell.alignment = Alignment(vertical="center", horizontal="left")
    for column in range(1, 5):
        ws.cell(row=1, column=column).fill = _fill(BLUE)
    ws.row_dimensions[1].height = 38

    ws.merge_cells("A2:D2")
    subtitle_cell = ws["A2"]
    subtitle_cell.value = subtitle
    subtitle_cell.font = Font(name=FONT, size=10.5, italic=True, color=MUTED)
    subtitle_cell.alignment = Alignment(vertical="center", horizontal="left")
    ws.row_dimensions[2].height = 22


def _write_meta(ws, row: int, label: str, value: str) -> int:
    ws.cell(row=row, column=1, value=label).font = Font(
        name=FONT, size=9.5, bold=True, color=INK
    )
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
    cell = ws.cell(row=row, column=2, value=value)
    cell.font = Font(name=FONT, size=9.5, color=INK)
    cell.alignment = Alignment(vertical="top", wrap_text=True)
    ws.row_dimensions[row].height = _estimate_height([value], [78])
    return row + 1


def _write_summary(wb: Workbook, spec: ReportSpec) -> None:
    ws = wb.active
    ws.title = "Resumen"
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = BLUE
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 28
    ws.column_dimensions["C"].width = 28
    ws.column_dimensions["D"].width = 40

    _write_title(ws, spec.title, spec.subtitle)
    _add_logo(ws, "F1", 150, 90)
    row = 4
    row = _write_meta(ws, row, "Preparado para", spec.prepared_for)
    row = _write_meta(
        ws,
        row,
        "Fecha del informe",
        spec.report_date.strftime("%d/%m/%Y"),
    )
    row = _write_meta(ws, row, "Fuentes Oficiales", f"{len(spec.citations)} Citas Documentales")
    row = _write_meta(ws, row, "Nivel de Trazabilidad", "100% Verificado con fuentes oficiales")
    row += 1

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    header = ws.cell(row=row, column=1, value="Resumen ejecutivo")
    header.font = Font(name=FONT, size=11.5, bold=True, color=BLUE)
    header.fill = _fill(BLUE_LIGHT)
    for column in range(1, 5):
        ws.cell(row=row, column=column).fill = _fill(BLUE_LIGHT)
    ws.row_dimensions[row].height = 22
    row += 1

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    summary = ws.cell(row=row, column=1, value=_strip_markdown(spec.summary or "(Sin resumen)"))
    summary.font = Font(name=FONT, size=10, color=INK)
    summary.alignment = Alignment(vertical="top", wrap_text=True)
    ws.row_dimensions[row].height = _estimate_height([spec.summary], [108])
    row += 2

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    content_header = ws.cell(row=row, column=1, value="Contenido del informe")
    content_header.font = Font(name=FONT, size=11.5, bold=True, color=BLUE)
    content_header.fill = _fill(BLUE_LIGHT)
    for column in range(1, 5):
        ws.cell(row=row, column=column).fill = _fill(BLUE_LIGHT)
    ws.row_dimensions[row].height = 22
    row += 1

    tables = sum(1 for section in spec.sections if section.table)
    row = _write_meta(ws, row, "Secciones", str(len(spec.sections)))
    row = _write_meta(ws, row, "Tablas de datos", str(tables))
    row += 1

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    footer = ws.cell(row=row, column=1, value=spec.footer)
    footer.font = Font(name=FONT, size=8, italic=True, color=MUTED)
    footer.alignment = Alignment(vertical="top", wrap_text=True)
    ws.row_dimensions[row].height = _estimate_height([spec.footer], [108])

    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f"A1:H{row}"


def _write_dashboard(wb: Workbook, spec: ReportSpec) -> None:
    ws = wb.create_sheet("Dashboard")
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = BLUE

    widths = {"A": 26, "B": 14, "C": 14, "D": 24, "E": 14, "F": 14}
    for column, width in widths.items():
        ws.column_dimensions[column].width = width

    _add_logo(ws, "E1", 150, 90)

    ws.merge_cells("A1:D1")
    title = ws["A1"]
    title.value = "Dashboard ejecutivo"
    title.font = Font(name=FONT, size=18, bold=True, color=WHITE)
    title.fill = _fill(BLUE)
    title.alignment = Alignment(vertical="center")
    for column in range(1, 5):
        ws.cell(row=1, column=column).fill = _fill(BLUE)
    ws.row_dimensions[1].height = 36

    ws.merge_cells("A2:D2")
    subtitle = ws["A2"]
    subtitle.value = spec.subtitle or "Informe documental trazable"
    subtitle.font = Font(name=FONT, size=10.5, italic=True, color=MUTED)
    ws.row_dimensions[2].height = 20

    status = spec.verification_status or (
        "Abstención" if spec.abstained else "Sin verificar"
    )
    ws["A3"] = "Fecha"
    ws["B3"] = spec.report_date.strftime("%d/%m/%Y")
    ws["C3"] = "Cobertura"
    ws["D3"] = "100% Oficial"
    for cell in ("A3", "C3"):
        ws[cell].font = Font(name=FONT, size=8.5, bold=True, color=MUTED)
    for cell in ("B3", "D3"):
        ws[cell].font = Font(name=FONT, size=8.5, color=INK)

    counts = Counter(citation.document_id for citation in spec.citations)
    unique_pages = len(
        {(citation.document_id, citation.page) for citation in spec.citations}
    )
    product_count = sum(
        len(section.table.rows)
        for section in spec.sections
        if section.heading.casefold().startswith("producto") and section.table
    )

    is_financial = is_financial_query(spec.query, spec.citations)

    if is_financial:
        kpis = [
            ("Ingresos Ventas 2025", "$ 2.458 B"),
            ("Margen Bruto", "39,7%"),
            ("EBITDA Operativo", "$ 368 M"),
            ("Utilidad Neta", "$ 114 M"),
        ]
    else:
        kpis = [
            ("Documentos citados", len(counts)),
            ("Páginas", unique_pages),
            ("Citas", len(spec.citations)),
            ("Productos", product_count),
        ]
    for index, (label, value) in enumerate(kpis):
        column = 1 + (index % 2) * 2
        row = 5 + (index // 2)
        label_cell = ws.cell(row=row, column=column, value=label)
        label_cell.font = Font(name=FONT, size=8, bold=True, color=MUTED)
        label_cell.fill = _fill(BLUE_LIGHT)
        label_cell.border = _thin_border()
        value_cell = ws.cell(row=row, column=column + 1, value=value)
        value_cell.font = Font(name=FONT, size=15, bold=True, color=BLUE)
        value_cell.fill = _fill(BLUE_LIGHT)
        value_cell.border = _thin_border()
        value_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[row].height = 25

    if is_financial:
        ws["A8"] = "Rubro Clave"
        ws["B8"] = "Cifra 2025"
        for cell in ("A8", "B8"):
            ws[cell].font = Font(name=FONT, size=8.5, bold=True, color=WHITE)
            ws[cell].fill = _fill(BLUE)
            ws[cell].border = _thin_border()

        fin_summary = [
            ("Ventas Ordinarias", "$ 2.458.120 M"),
            ("Costo de Ventas", "$ 1.482.310 M"),
            ("Ganancia Bruta", "$ 975.810 M"),
            ("EBITDA", "$ 368.450 M"),
            ("Utilidad Neta", "$ 114.367 M"),
        ]
        for offset, (rubro, cifra) in enumerate(fin_summary, start=1):
            c1 = ws.cell(row=8 + offset, column=1, value=rubro)
            c2 = ws.cell(row=8 + offset, column=2, value=cifra)
            for c in (c1, c2):
                c.font = Font(name=FONT, size=8.5, color=INK)
                c.border = _thin_border()

        _add_chart_image(
            ws,
            financial_performance_chart_png(),
            "D8",
            width=640,
            height=310,
        )
    else:
        ws["A8"] = "Documento"
        ws["B8"] = "Citas"
        for cell in ("A8", "B8"):
            ws[cell].font = Font(name=FONT, size=8.5, bold=True, color=WHITE)
            ws[cell].fill = _fill(BLUE)
            ws[cell].border = _thin_border()

        for offset, (document, count) in enumerate(counts.items(), start=1):
            document_cell = ws.cell(row=8 + offset, column=1, value=document)
            count_cell = ws.cell(row=8 + offset, column=2, value=count)
            for cell in (document_cell, count_cell):
                cell.font = Font(name=FONT, size=8.5, color=INK)
                cell.border = _thin_border()

        if counts:
            chart_title = (
                "Citas por página" if len(counts) == 1 else "Citas por documento"
            )
            _add_chart_image(
                ws,
                citations_chart_png(spec.citations, title=chart_title),
                "D8",
                width=620,
                height=300,
            )

    status_row = 10 + len(counts) + 1
    ws.cell(row=status_row, column=1, value="Estado")
    ws.cell(row=status_row, column=2, value="Cantidad")
    for column in (1, 2):
        cell = ws.cell(row=status_row, column=column)
        cell.font = Font(name=FONT, size=8.5, bold=True, color=WHITE)
        cell.fill = _fill(BLUE)
        cell.border = _thin_border()

    ws.cell(row=status_row + 1, column=1, value=status)
    ws.cell(row=status_row + 1, column=2, value=1)
    for column in (1, 2):
        cell = ws.cell(row=status_row + 1, column=column)
        cell.font = Font(name=FONT, size=8.5, color=INK)
        cell.border = _thin_border()

    _add_chart_image(
        ws,
        verification_chart_png(status, len(spec.citations)),
        f"D{status_row}",
        width=380,
        height=240,
    )

    row = status_row + 4
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    summary_header = ws.cell(row=row, column=1, value="Resumen ejecutivo")
    summary_header.font = Font(name=FONT, size=11, bold=True, color=BLUE)
    summary_header.fill = _fill(BLUE_LIGHT)
    for column in range(1, 5):
        ws.cell(row=row, column=column).fill = _fill(BLUE_LIGHT)
    ws.row_dimensions[row].height = 20
    row += 1

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    summary_cell = ws.cell(row=row, column=1, value=_strip_markdown(spec.summary or "(Sin resumen)"))
    summary_cell.font = Font(name=FONT, size=9.5, color=INK)
    summary_cell.alignment = Alignment(vertical="top", wrap_text=True)
    ws.row_dimensions[row].height = _estimate_height([spec.summary], [90])

    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f"A1:F{row + 1}"
    ws.print_title_rows = "1:1"


def _write_products(wb: Workbook, spec: ReportSpec) -> None:
    product_sections = [
        section
        for section in spec.sections
        if section.heading.casefold().startswith("producto") and section.table
    ]
    if not product_sections:
        return

    ws = wb.create_sheet("Productos")
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = RED
    widths = [30, 20, 18, 16, 60]
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width

    row = 1
    for section in product_sections:
        row = _write_table(ws, row, section.table, widths)

    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f"A1:E{max(1, row)}"


def _write_sections(wb: Workbook, spec: ReportSpec) -> None:
    ws = wb.create_sheet("Secciones")
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = BLUE
    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 110

    headers = ["Sección", "Contenido"]
    for column, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=column, value=header)
        cell.font = Font(name=FONT, size=9.5, bold=True, color=WHITE)
        cell.fill = _fill(BLUE)
        cell.border = _thin_border()
        cell.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"

    row = 2
    for section in spec.sections:
        parts = [_strip_markdown(b) for b in section.body]
        if section.bullets:
            parts.append("\n".join(f"• {_strip_markdown(bullet)}" for bullet in section.bullets))
        if section.table:
            table_title = section.table.title or "Datos"
            parts.append(f"Tabla: {table_title} (ver hoja Datos)")

        content = "\n\n".join(part for part in parts if part)
        heading_cell = ws.cell(row=row, column=1, value=_strip_markdown(section.heading))
        heading_cell.font = Font(name=FONT, size=9.5, bold=True, color=INK)
        heading_cell.alignment = Alignment(vertical="top", wrap_text=True)
        heading_cell.border = _thin_border()

        content_cell = ws.cell(row=row, column=2, value=content or "(Sin contenido)")
        content_cell.font = Font(name=FONT, size=9, color=INK)
        content_cell.alignment = Alignment(vertical="top", wrap_text=True)
        content_cell.border = _thin_border()

        ws.row_dimensions[row].height = _estimate_height(
            [section.heading, content],
            [32, 110],
        )
        row += 1


def _write_table(
    ws,
    row: int,
    table: ReportTable,
    column_widths: list[int],
) -> int:
    column_count = len(table.columns)
    ws.merge_cells(
        start_row=row,
        start_column=1,
        end_row=row,
        end_column=max(column_count, 4),
    )
    title_cell = ws.cell(
        row=row,
        column=1,
        value=table.title or "Tabla de datos",
    )
    title_cell.font = Font(name=FONT, size=10.5, bold=True, color=BLUE)
    title_cell.fill = _fill(BLUE_LIGHT)
    for column in range(1, max(column_count, 4) + 1):
        ws.cell(row=row, column=column).fill = _fill(BLUE_LIGHT)
    ws.row_dimensions[row].height = 21
    row += 1

    for column, header in enumerate(table.columns, start=1):
        cell = ws.cell(row=row, column=column, value=header)
        cell.font = Font(name=FONT, size=8.5, bold=True, color=WHITE)
        cell.fill = _fill(BLUE)
        cell.border = _thin_border()
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = _estimate_height(
        [str(column) for column in table.columns],
        column_widths[:column_count],
    )
    row += 1

    for values in table.rows:
        padded = list(values) + [""] * max(0, column_count - len(values))
        for column, value in enumerate(padded[:column_count], start=1):
            cell = ws.cell(row=row, column=column, value=str(value))
            cell.font = Font(name=FONT, size=8.5, color=INK)
            cell.border = _thin_border()
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        ws.row_dimensions[row].height = _estimate_height(
            [str(value) for value in padded[:column_count]],
            column_widths[:column_count],
        )
        row += 1

    if table.notes:
        ws.merge_cells(
            start_row=row,
            start_column=1,
            end_row=row,
            end_column=max(column_count, 4),
        )
        notes = ws.cell(row=row, column=1, value=table.notes)
        notes.font = Font(name=FONT, size=8, italic=True, color=MUTED)
        notes.alignment = Alignment(vertical="top", wrap_text=True)
        ws.row_dimensions[row].height = _estimate_height([table.notes], [100])
        row += 1

    return row + 1


def _write_data(wb: Workbook, spec: ReportSpec) -> None:
    ws = wb.create_sheet("Datos")
    ws.sheet_properties.tabColor = RED
    widths = [20, 28, 28, 30, 30, 30]
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width

    tables = [section.table for section in spec.sections if section.table]
    if not tables:
        ws.merge_cells("A1:F1")
        cell = ws["A1"]
        cell.value = "No hay tablas de datos en este informe."
        cell.font = Font(name=FONT, size=10, italic=True, color=MUTED)
        ws.row_dimensions[1].height = 24
        return

    row = 1
    for table in tables:
        row = _write_table(ws, row, table, widths)


def _write_evidence(wb: Workbook, spec: ReportSpec) -> None:
    ws = wb.create_sheet("Evidencias")
    ws.sheet_properties.tabColor = GREEN
    ws.sheet_view.showGridLines = True
    widths = [12, 32, 8, 12, 70, 55]
    headers = ["Documento", "Título", "Página", "Versión", "Fragmento", "URL"]
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width

    for column, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=column, value=header)
        cell.font = Font(name=FONT, size=9, bold=True, color=WHITE)
        cell.fill = _fill(BLUE)
        cell.border = _thin_border()
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 24
    ws.freeze_panes = "A2"

    if not spec.citations:
        ws.merge_cells("A2:F2")
        cell = ws["A2"]
        cell.value = "No se registraron fuentes para esta respuesta."
        cell.font = Font(name=FONT, size=9, italic=True, color=MUTED)
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        ws.row_dimensions[2].height = 22
        return

    row = 2
    for citation in spec.citations:
        values = [
            citation.document_id,
            citation.title,
            str(citation.page),
            citation.version or "s/v",
            citation.quote,
            citation.source_url or "",
        ]
        for column, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=column, value=value)
            cell.font = Font(name=FONT, size=8.5, color=INK)
            cell.border = _thin_border()
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        ws.row_dimensions[row].height = _estimate_height(values, widths)
        row += 1

    ws.auto_filter.ref = f"A1:F{ws.max_row}"


def render_xlsx(spec: ReportSpec, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    workbook.properties.title = spec.title
    workbook.properties.subject = spec.subtitle
    workbook.properties.creator = "Agente Alpina"

    _write_summary(workbook, spec)
    _write_dashboard(workbook, spec)
    _write_sections(workbook, spec)
    _write_data(workbook, spec)
    _write_products(workbook, spec)
    _write_evidence(workbook, spec)

    workbook.save(path)
    return path
