from __future__ import annotations

import math
import re
import textwrap
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.core.markdown import plain_markdown
from app.reports.spec import ReportSpec, ReportTable

BLUE = "0152D1"
BLUE_LIGHT = "EAF1FB"
RED = "E30613"
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


def _parse_numeric(val: Any, col_name: str = "") -> tuple[Any, str | None]:
    """Detecta y convierte cadenas con números, porcentajes o moneda a valores numéricos nativos de Excel.

    Conserva EAN, SKU e identificadores con ceros iniciales como texto literal (R10).
    """
    if isinstance(val, (int, float, Decimal)):
        return val, None
    if not isinstance(val, str):
        return val, None
    s = val.strip()
    if not s:
        return s, None

    col_clean = str(col_name or "").strip().lower()
    # Si la columna es identificador (EAN, SKU, Código) o tiene ceros a la izquierda seguidos de dígitos
    if re.search(r"\b(?:ean|sku|c[oó]digo|identificador|id)\b", col_clean):
        return s, "@"
    if re.match(r"^0\d+$", s):
        # EAN o código con ceros a la izquierda (ej. 0123456789012)
        return s, "@"

    match = re.fullmatch(r"(\()?\s*([+-]?)\s*(\$?)\s*([\d.,]+)\s*(%?)\s*(\))?", s)
    if not match:
        return val, None
    opening, sign, currency, amount, percentage, closing = match.groups()
    if bool(opening) != bool(closing) or (opening and sign) or (currency and percentage):
        return val, None

    grouped = False
    if "," in amount and "." in amount:
        grouping, decimal = (",", ".") if amount.rfind(",") < amount.rfind(".") else (".", ",")
        if not re.fullmatch(rf"[1-9]\d{{0,2}}(?:{re.escape(grouping)}\d{{3}})+{re.escape(decimal)}\d+", amount):
            return val, None
        amount = amount.replace(grouping, "").replace(decimal, ".")
        grouped = True
    elif not percentage and re.fullmatch(r"[1-9]\d{0,2}([.,])\d{3}(?:\1\d{3})*", amount):
        amount = amount.replace(".", "").replace(",", "")
        grouped = True
    else:
        amount = amount.replace(",", ".")

    if not re.fullmatch(r"\d+(?:\.\d+)?", amount):
        return val, None
    if len(amount.replace(".", "").lstrip("0")) > 15:
        return s, "@"
    amount = ("-" if opening or sign == "-" else "") + amount
    decimals = len(amount.partition(".")[2])
    if percentage:
        return float(Decimal(amount) / 100), "0." + "0" * max(decimals, 1) + "%"
    number = float(amount) if decimals or currency else int(amount)
    number_format = "$ #,##0" if currency else ("#,##0" if grouped else "0")
    if decimals:
        number_format += "." + "0" * decimals
    return number, number_format


def _literal_cell(ws, row: int, column: int, value):
    cell = ws.cell(row=row, column=column, value=value)
    if isinstance(value, str):
        cell.data_type = "s"
    return cell


def _estimate_height(values: list[str], widths: list[int]) -> float:
    lines = 1
    for value, width in zip(values, widths):
        if value:
            lines = max(
                lines,
                sum(max(1, math.ceil(len(line) / max(10, width))) for line in str(value).split("\n")),
            )
    return max(15, min(400, lines * 14))


def _add_logo(ws, anchor: str = "F1", width: int = 150, height: int = 90) -> None:
    if not LOGO_PATH.is_file():
        return
    image = XLImage(str(LOGO_PATH))
    image.width = width
    image.height = height
    ws.add_image(image, anchor)


def _write_title(ws, title: str, subtitle: str) -> None:
    ws.merge_cells("A1:D1")
    cell = _literal_cell(ws, 1, 1, title)
    cell.font = Font(name=FONT, size=20, bold=True, color=WHITE)
    cell.fill = _fill(BLUE)
    cell.alignment = Alignment(vertical="center", horizontal="left", wrap_text=True)
    for column in range(1, 5):
        ws.cell(row=1, column=column).fill = _fill(BLUE)
    ws.row_dimensions[1].height = max(38, _estimate_height([title], [72]) * 1.5)

    if subtitle:
        ws.merge_cells("A2:D2")
        subtitle_cell = _literal_cell(ws, 2, 1, subtitle)
        subtitle_cell.font = Font(name=FONT, size=10.5, italic=True, color=MUTED)
        subtitle_cell.alignment = Alignment(vertical="center", horizontal="left", wrap_text=True)
        ws.row_dimensions[2].height = max(22, _estimate_height([subtitle], [108]))


def _write_meta(ws, row: int, label: str, value: str) -> int:
    ws.cell(row=row, column=1, value=label).font = Font(
        name=FONT, size=9.5, bold=True, color=INK
    )
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
    cell = _literal_cell(ws, row, 2, value)
    cell.font = Font(name=FONT, size=9.5, color=INK)
    cell.alignment = Alignment(vertical="top", wrap_text=True)
    ws.row_dimensions[row].height = _estimate_height([value], [78])
    return row + 1


def _write_narrative(ws, row: int, text: str, *, heading: bool = False) -> int:
    # Excel limita la altura de cada fila. Distribuir los párrafos largos evita
    # ocultar líneas en celdas combinadas.
    lines = [
        line for part in plain_markdown(text).split("\n")
        for line in (textwrap.wrap(part, width=100) or [""])
    ]
    for start in range(0, len(lines), 20):
        value = "\n".join(lines[start:start + 20])
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
        cell = _literal_cell(ws, row, 1, value)
        cell.font = Font(name=FONT, size=11 if heading else 10, bold=heading, color=BLUE if heading else INK)
        cell.alignment = Alignment(vertical="top", wrap_text=True, indent=1)
        if heading:
            cell.fill = _fill(BLUE_LIGHT)
        ws.row_dimensions[row].height = max(21, _estimate_height([value], [104]))
        row += 1
    return row


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
    row += 1
    if spec.summary:
        row = _write_narrative(ws, row, "Resumen ejecutivo", heading=True)
        row = _write_narrative(ws, row, spec.summary) + 1

    table_index = 0
    for section in spec.sections:
        if section.heading:
            row = _write_narrative(ws, row, section.heading, heading=True)
        for paragraph in section.body:
            row = _write_narrative(ws, row, paragraph)
        for bullet in section.bullets:
            row = _write_narrative(ws, row, f"• {bullet}")
        if section.table:
            table_index += 1
            label = section.table.title or f"Tabla {table_index}"
            row = _write_narrative(ws, row, f"{label} · Hoja Datos")

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    footer = _literal_cell(ws, row, 1, spec.footer)
    footer.font = Font(name=FONT, size=8, italic=True, color=MUTED)
    footer.alignment = Alignment(vertical="top", wrap_text=True)
    ws.row_dimensions[row].height = _estimate_height([spec.footer], [108])

    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f"A1:H{row}"


def _write_table(
    ws,
    row: int,
    table: ReportTable,
    column_widths: list[int],
    title: str,
) -> int:
    column_count = len(table.columns)
    ws.merge_cells(
        start_row=row,
        start_column=1,
        end_row=row,
        end_column=max(column_count, 4),
    )
    title_cell = _literal_cell(ws, row, 1, title)
    title_cell.font = Font(name=FONT, size=10.5, bold=True, color=BLUE)
    title_cell.fill = _fill(BLUE_LIGHT)
    for column in range(1, max(column_count, 4) + 1):
        ws.cell(row=row, column=column).fill = _fill(BLUE_LIGHT)
    ws.row_dimensions[row].height = 21
    row += 1

    for column, header in enumerate(table.columns, start=1):
        cell = _literal_cell(ws, row, column, plain_markdown(header))
        cell.font = Font(name=FONT, size=8.5, bold=True, color=WHITE)
        cell.fill = _fill(BLUE)
        cell.border = _thin_border()
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = _estimate_height(
        [str(column) for column in table.columns],
        column_widths[:column_count],
    )
    row += 1

    start_data_row = row
    for values in table.iter_rows():
        for column, value in enumerate(values, start=1):
            col_name = plain_markdown(table.columns[column - 1])
            parsed_val, num_fmt = _parse_numeric(plain_markdown(value), col_name=col_name)
            cell = _literal_cell(ws, row, column, parsed_val)
            if num_fmt:
                cell.number_format = num_fmt
            cell.font = Font(name=FONT, size=8.5, color=INK)
            cell.border = _thin_border()
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        ws.row_dimensions[row].height = _estimate_height(
            values,
            column_widths[:column_count],
        )
        row += 1
    end_data_row = row - 1

    if table.notes:
        ws.merge_cells(
            start_row=row,
            start_column=1,
            end_row=row,
            end_column=max(column_count, 4),
        )
        notes = _literal_cell(ws, row, 1, plain_markdown(table.notes))
        notes.font = Font(name=FONT, size=8, italic=True, color=MUTED)
        notes.alignment = Alignment(vertical="top", wrap_text=True)
        ws.row_dimensions[row].height = _estimate_height([table.notes], [100])
        row += 1

    if 2 <= len(table.rows) <= 20:
        numerical_columns = [
            column for column in range(2, column_count + 1)
            if all(isinstance(ws.cell(r, column).value, (int, float)) for r in range(start_data_row, end_data_row + 1))
        ][:2]
        if numerical_columns:
            chart = BarChart()
            chart.style = 10
            chart.title = title
            for column in numerical_columns:
                chart.add_data(Reference(ws, min_col=column, min_row=start_data_row - 1, max_row=end_data_row), titles_from_data=True)
            chart.set_categories(Reference(ws, min_col=1, min_row=start_data_row, max_row=end_data_row))
            ws.add_chart(chart, f"A{row + 1}")
            row += 17

    return row + 1


def _write_data(wb: Workbook, spec: ReportSpec) -> None:
    tables = [section.table for section in spec.sections if section.table]
    if not tables:
        return

    ws = wb.create_sheet("Datos")
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = RED
    widths = [30] + [24] * (max(len(table.columns) for table in tables) - 1)
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width

    row = 1
    for index, table in enumerate(tables, start=1):
        row = _write_table(ws, row, table, widths, plain_markdown(table.title) or f"Tabla {index}")
    ws.freeze_panes = "B3"
    if len(tables) == 1 and tables[0].rows:
        right_column = get_column_letter(len(tables[0].columns))
        ws.auto_filter.ref = f"A2:{right_column}{2 + len(tables[0].rows)}"


def render_xlsx(spec: ReportSpec, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    workbook.properties.title = spec.title
    workbook.properties.subject = spec.subtitle
    workbook.properties.creator = "Agente Alpina"

    _write_summary(workbook, spec)
    _write_data(workbook, spec)

    workbook.save(path)
    return path
