from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont, TTFError
from reportlab.platypus import (
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.core.markdown import inline_runs
from app.reports.spec import ReportSpec, ReportTable

BLUE = colors.HexColor("#0152D1")
INK = colors.HexColor("#0F223D")
MUTED = colors.HexColor("#64748B")
GRID = colors.HexColor("#DCE5F0")

LOGO_PATH = Path(__file__).resolve().parents[1] / "static" / "brand" / "alpina-logo.png"

_FONTS: tuple[str, str] | None = None


def _register_fonts() -> tuple[str, str]:
    global _FONTS
    if _FONTS is not None:
        return _FONTS

    candidates = (
        ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
        ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    )
    for files in candidates:
        paths = [Path("C:/Windows/Fonts") / file for file in files]
        if all(path.is_file() for path in paths):
            names = ["AlpinaSans", "AlpinaSans-Bold", "AlpinaSans-Italic", "AlpinaSans-BoldItalic"]
            try:
                for name, path in zip(names, paths):
                    pdfmetrics.registerFont(TTFont(name, str(path)))
            except (OSError, TTFError):
                continue
            pdfmetrics.registerFontFamily(names[0], *names)
            _FONTS = (names[0], names[1])
            break
    else:
        _FONTS = ("Helvetica", "Helvetica-Bold")
    return _FONTS


def _styles() -> dict[str, ParagraphStyle]:
    regular, bold = _register_fonts()
    base = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle(
            "Brand",
            parent=base["Title"],
            fontName=bold,
            fontSize=22,
            leading=24,
            textColor=BLUE,
            alignment=TA_LEFT,
            spaceAfter=1,
        ),
        "title": ParagraphStyle(
            "ReportTitle",
            fontName=bold,
            fontSize=19,
            leading=23,
            textColor=INK,
            spaceAfter=5,
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle",
            fontName=regular,
            fontSize=10.5,
            leading=13,
            textColor=MUTED,
            spaceAfter=9,
        ),
        "meta": ParagraphStyle(
            "Meta",
            fontName=regular,
            fontSize=8.3,
            leading=11,
            textColor=MUTED,
            spaceAfter=1,
        ),
        "h2": ParagraphStyle(
            "H2",
            fontName=bold,
            fontSize=12.5,
            leading=15,
            textColor=BLUE,
            spaceBefore=13,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "H3",
            fontName=bold,
            fontSize=9.8,
            leading=12,
            textColor=INK,
            spaceBefore=6,
            spaceAfter=2,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body",
            fontName=regular,
            fontSize=9.4,
            leading=13.6,
            textColor=INK,
            spaceAfter=5,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            fontName=regular,
            fontSize=9.4,
            leading=13,
            textColor=INK,
            leftIndent=12,
            bulletIndent=0,
            spaceAfter=2,
        ),
        "small": ParagraphStyle(
            "Small",
            fontName=regular,
            fontSize=7.4,
            leading=9.8,
            textColor=MUTED,
            spaceAfter=4,
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            fontName=bold,
            fontSize=7.3,
            leading=8.8,
            textColor=colors.white,
        ),
        "table_cell": ParagraphStyle(
            "TableCell",
            fontName=regular,
            fontSize=7.3,
            leading=8.8,
            textColor=INK,
        ),
    }


def _markdown_to_reportlab(text: str) -> str:
    parts = []
    for value, styles in inline_runs(text):
        value = escape(value).replace("\n", "<br/>")
        if "code" in styles:
            value = f'<font face="Courier">{value}</font>'
        if "strong" in styles:
            value = f"<b>{value}</b>"
        if "em" in styles:
            value = f"<i>{value}</i>"
        if "s" in styles:
            value = f"<strike>{value}</strike>"
        parts.append(value)
    return "".join(parts)


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_markdown_to_reportlab(text), style)


def _split_paragraphs(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\n\s*\n", str(text or ""))]
    return [part for part in parts if part] or [str(text or "").strip()]


def _make_on_page(spec: ReportSpec, regular: str, bold: str):
    def on_page(canvas, doc) -> None:
        width, height = A4
        canvas.saveState()
        canvas.setFillColor(BLUE)
        canvas.rect(2 * cm, height - 1.35 * cm, width - 4 * cm, 2.2, stroke=0, fill=1)
        canvas.setFont(bold, 7.4)
        canvas.setFillColor(MUTED)
        canvas.drawString(2 * cm, height - 1.02 * cm, "ALPINA · AGENTE DOCUMENTAL")
        canvas.drawRightString(
            width - 2 * cm,
            height - 1.02 * cm,
            spec.report_date.strftime("%d/%m/%Y"),
        )
        canvas.setFont(regular, 6.8)
        canvas.drawString(2 * cm, 1.12 * cm, spec.footer[:120])
        canvas.drawRightString(width - 2 * cm, 1.12 * cm, f"Página {doc.page}")
        canvas.restoreState()

    return on_page


def _logo_flowables(styles: dict[str, ParagraphStyle]) -> list:
    if LOGO_PATH.is_file():
        logo = RLImage(str(LOGO_PATH), width=118, height=71)
        logo.hAlign = "LEFT"
        return [logo, Spacer(1, 0.12 * cm)]
    return [_paragraph("ALPINA", styles["brand"])]


def _table_flowables(table: ReportTable, width: float, styles: dict[str, ParagraphStyle]) -> list:
    column_count = len(table.columns)
    data = [
        [
            _paragraph(column, styles["table_header"])
            for column in table.columns
        ]
    ]
    for values in table.iter_rows():
        data.append(
            [
                _paragraph(value, styles["table_cell"])
                for value in values
            ]
        )

    column_width = width / column_count
    rendered = Table(
        data,
        colWidths=[column_width] * column_count,
        repeatRows=1,
        splitInRow=1,
    )
    rendered.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("GRID", (0, 0), (-1, -1), 0.35, GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#F8FAFC")],
                ),
            ]
        )
    )

    flowables: list = []
    if table.title:
        flowables.append(_paragraph(table.title, styles["h3"]))
    flowables.append(rendered)
    if table.notes:
        flowables.append(_paragraph(table.notes, styles["small"]))
    flowables.append(Spacer(1, 0.15 * cm))
    return flowables


def render_pdf(spec: ReportSpec, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    regular, bold = _register_fonts()
    styles = _styles()

    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=spec.title,
        author="Agente Alpina",
        subject=spec.subtitle,
    )

    story: list = []
    story.extend(_logo_flowables(styles))
    story.append(_paragraph(spec.title, styles["title"]))
    if spec.subtitle:
        story.append(_paragraph(spec.subtitle, styles["subtitle"]))
    story.append(_paragraph(f"Preparado para: {spec.prepared_for}", styles["meta"]))
    story.append(
        _paragraph(
            f"Fecha del informe: {spec.report_date.strftime('%d/%m/%Y')}",
            styles["meta"],
        )
    )
    story.append(Spacer(1, 0.2 * cm))

    if spec.summary:
        story.append(_paragraph("Resumen ejecutivo", styles["h2"]))
        for part in _split_paragraphs(spec.summary):
            story.append(_paragraph(part, styles["body"]))

    for section in spec.sections:
        if section.heading:
            story.append(_paragraph(section.heading, styles["h2"]))
        for paragraph in section.body:
            for part in _split_paragraphs(paragraph):
                story.append(_paragraph(part, styles["body"]))
        for bullet in section.bullets:
            story.append(
                Paragraph(
                    _markdown_to_reportlab(bullet),
                    styles["bullet"],
                    bulletText="•",
                )
            )
        if section.table:
            for table in section.table.printable_parts():
                story.extend(_table_flowables(table, document.width - 12, styles))

    document.build(
        story,
        onFirstPage=_make_on_page(spec, regular, bold),
        onLaterPages=_make_on_page(spec, regular, bold),
    )
    return path
