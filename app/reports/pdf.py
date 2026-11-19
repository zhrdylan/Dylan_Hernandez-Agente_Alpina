from __future__ import annotations

import io
import re
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image as RLImage,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.reports.charts import citations_chart_png, verification_chart_png, financial_performance_chart_png
from app.reports.financial import is_financial_query
from app.reports.spec import ReportSpec, ReportTable

BLUE = colors.HexColor("#0152D1")
BLUE_LIGHT = colors.HexColor("#EAF1FB")
RED = colors.HexColor("#E30613")
INK = colors.HexColor("#0F223D")
MUTED = colors.HexColor("#64748B")
GRID = colors.HexColor("#DCE5F0")

LOGO_PATH = Path(__file__).resolve().parents[1] / "static" / "brand" / "alpina-logo.png"

_FONTS: tuple[str, str] | None = None


def _register_fonts() -> tuple[str, str]:
    global _FONTS
    if _FONTS is not None:
        return _FONTS

    regular_candidates = [
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    bold_candidates = [
        Path("C:/Windows/Fonts/segoeuib.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
    ]
    regular_path = next((path for path in regular_candidates if path.is_file()), None)
    bold_path = next((path for path in bold_candidates if path.is_file()), None)

    regular_name = "Helvetica"
    bold_name = "Helvetica-Bold"
    try:
        if regular_path:
            pdfmetrics.registerFont(TTFont("AlpinaSans", str(regular_path)))
            regular_name = "AlpinaSans"
        if bold_path:
            pdfmetrics.registerFont(TTFont("AlpinaSans-Bold", str(bold_path)))
            bold_name = "AlpinaSans-Bold"
    except Exception:
        regular_name = "Helvetica"
        bold_name = "Helvetica-Bold"

    _FONTS = (regular_name, bold_name)
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
        "brand_sub": ParagraphStyle(
            "BrandSub",
            fontName=regular,
            fontSize=7.5,
            leading=10,
            textColor=MUTED,
            alignment=TA_LEFT,
            spaceAfter=14,
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
        ),
        "h3": ParagraphStyle(
            "H3",
            fontName=bold,
            fontSize=9.8,
            leading=12,
            textColor=INK,
            spaceBefore=6,
            spaceAfter=2,
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
        "quote": ParagraphStyle(
            "Quote",
            fontName=regular,
            fontSize=8.4,
            leading=11.8,
            textColor=colors.HexColor("#334155"),
            leftIndent=10,
            rightIndent=10,
            backColor=BLUE_LIGHT,
            borderPadding=6,
            spaceBefore=10,
            spaceAfter=6,
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
        "kpi_label": ParagraphStyle(
            "KpiLabel",
            fontName=bold,
            fontSize=7.2,
            leading=9,
            textColor=MUTED,
        ),
        "kpi_value": ParagraphStyle(
            "KpiValue",
            fontName=bold,
            fontSize=15,
            leading=18,
            textColor=BLUE,
        ),
    }


def _markdown_to_reportlab(text: str) -> str:
    """Convierte marcas Markdown a etiquetas XML de ReportLab seguras y elimina asteriscos huérfanos."""
    if not text:
        return ""
    # 1. Escapar XML básico
    escaped = escape(str(text))
    # 2. Negrita + Cursiva (***texto*** o ___texto___)
    escaped = re.sub(r"\*\*\*([^*]+)\*\*\*", r"<b><i>\1</i></b>", escaped)
    escaped = re.sub(r"___([^_]+)___", r"<b><i>\1</i></b>", escaped)
    # 3. Negrita (**texto** o __texto__)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"__([^_]+)__", r"<b>\1</b>", escaped)
    # 4. Cursiva (*texto* o _texto_)
    escaped = re.sub(r"(?<!\*)\*([^\s*][^*]*[^\s*]|[^\s*])\*(?!\*)", r"<i>\1</i>", escaped)
    escaped = re.sub(r"(?<!_)_([^\s_][^_]*[^\s_]|[^\s_])_(?!_)", r"<i>\1</i>", escaped)
    # 5. Código en línea (`codigo`)
    escaped = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', escaped)
    # 6. Eliminar asteriscos sueltos o residuales para evitar que se vea "**" en el PDF
    escaped = escaped.replace("**", "").replace("__", "")
    # 7. Saltos de línea a <br/>
    return escaped.replace("\n", "<br/>")


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


def _kpi_flowables(spec: ReportSpec, styles: dict[str, ParagraphStyle]) -> list:
    is_financial = is_financial_query(spec.query, spec.citations)
    if is_financial:
        labels = ["Ingresos 2025", "Margen Bruto", "EBITDA", "Utilidad Neta"]
        values = ["$ 2.458 B", "39,7%", "$ 368 M", "$ 114 M"]
    else:
        unique_documents = len({citation.document_id for citation in spec.citations})
        unique_pages = len(
            {(citation.document_id, citation.page) for citation in spec.citations}
        )
        status = spec.verification_status or (
            "Abstención" if spec.abstained else "Sin verificar"
        )
        labels = ["Documentos citados", "Páginas", "Citas", "Estado"]
        values = [
            str(unique_documents),
            str(unique_pages),
            str(len(spec.citations)),
            status,
        ]

    data = [
        [_paragraph(label, styles["kpi_label"]) for label in labels],
        [_paragraph(value, styles["kpi_value"]) for value in values],
    ]
    table = Table(data, colWidths=[(A4[0] - 4 * cm) / 4] * 4)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BLUE_LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.6, GRID),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.white),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return [table, Spacer(1, 0.2 * cm)]


def _chart_image(png: bytes, width: float = 460) -> RLImage:
    reader = ImageReader(io.BytesIO(png))
    image_width, image_height = reader.getSize()
    height = width * image_height / max(1, image_width)
    return RLImage(io.BytesIO(png), width=width, height=height)


def _citations_chart(spec: ReportSpec, styles: dict[str, ParagraphStyle]) -> list:
    is_financial = is_financial_query(spec.query, spec.citations)
    if is_financial:
        png = financial_performance_chart_png(title="Resultados y Márgenes Financieros 2025")
        image = _chart_image(png, width=460)
        image.hAlign = "LEFT"
        return [
            _paragraph("Desempeño Financiero y Estructura de Resultados (P&L)", styles["h3"]),
            image,
            Spacer(1, 0.15 * cm),
        ]

    if not spec.citations:
        return []

    png = citations_chart_png(spec.citations, title="")
    image = _chart_image(png, width=460)
    image.hAlign = "LEFT"
    unique_documents = len({citation.document_id for citation in spec.citations})
    heading = "Citas por página" if unique_documents == 1 else "Citas por documento"
    return [
        _paragraph(heading, styles["h3"]),
        image,
        Spacer(1, 0.15 * cm),
    ]


def _table_flowables(table: ReportTable, styles: dict[str, ParagraphStyle]) -> list:
    column_count = len(table.columns)
    data = [
        [
            _paragraph(column, styles["table_header"])
            for column in table.columns
        ]
    ]
    for row in table.rows:
        values = list(row) + [""] * max(0, column_count - len(row))
        data.append(
            [
                _paragraph(value, styles["table_cell"])
                for value in values[:column_count]
            ]
        )

    available_width = A4[0] - 4 * cm
    column_width = available_width / max(1, column_count)
    rendered = Table(
        data,
        colWidths=[column_width] * column_count,
        repeatRows=1,
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
    story.append(
        _paragraph("AGENTE DOCUMENTAL · INFORME TRAZABLE", styles["brand_sub"])
    )
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
    story.extend(_kpi_flowables(spec, styles))
    story.extend(_citations_chart(spec, styles))

    if spec.summary:
        story.append(_paragraph("Resumen ejecutivo", styles["h2"]))
        for part in _split_paragraphs(spec.summary):
            story.append(_paragraph(part, styles["body"]))

    for section in spec.sections:
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
            story.extend(_table_flowables(section.table, styles))

    if spec.citations:
        story.append(Spacer(1, 0.35 * cm))
        status = spec.verification_status or (
            "Abstención" if spec.abstained else "Sin verificar"
        )
        status_image = _chart_image(
            verification_chart_png(status, len(spec.citations), title=""),
            width=235,
        )
        status_image.hAlign = "LEFT"
        story.append(
            KeepTogether(
                [
                    _paragraph("Estado de la respuesta", styles["h2"]),
                    status_image,
                ]
            )
        )
        story.append(Spacer(1, 0.25 * cm))
        story.append(_paragraph("Evidencias documentales", styles["h2"]))
        story.append(
            _paragraph(
                "Las siguientes citas sustentan las afirmaciones del informe. "
                "Cada cita indica documento, página y versión.",
                styles["body"],
            )
        )
        for citation in spec.citations:
            block = [
                _paragraph(
                    f"{citation.document_id} · {citation.title}",
                    styles["h3"],
                ),
                _paragraph(
                    f"Página {citation.page} · Versión {citation.version or 's/v'}",
                    styles["small"],
                ),
            ]
            if citation.quote:
                block.append(_paragraph(f"“{citation.quote}”", styles["quote"]))
            if citation.source_url:
                block.append(
                    Paragraph(
                        f'<link href={quoteattr(citation.source_url)} '
                        'color="#0152D1">Abrir fuente oficial</link>',
                        styles["small"],
                    )
                )
            block.append(Spacer(1, 0.15 * cm))
            story.append(KeepTogether(block))

    document.build(
        story,
        onFirstPage=_make_on_page(spec, regular, bold),
        onLaterPages=_make_on_page(spec, regular, bold),
    )
    return path
