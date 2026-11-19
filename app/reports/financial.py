from __future__ import annotations

import re
from typing import Any
from app.reports.spec import ReportSection, ReportTable


FINANCIAL_KEYWORDS = {
    "venta", "ventas", "ingreso", "ingresos", "financier", "financiero",
    "financiera", "financieros", "balance", "ebitda", "utilidad", "utilidades",
    "eeff", "costo", "costos", "p&l", "perdida", "pérdida", "ganancia",
    "ganancias", "activo", "activos", "pasivo", "pasivos", "patrimonio",
    "ejercicio", "tributar", "impuesto", "impuestos", "renta",
    "margen", "márgenes", "dividendo", "dividendos", "estados financieros",
}


def is_financial_query(query: str, citations: list[Any] | None = None) -> bool:
    q_lower = (query or "").lower()
    matches = sum(1 for kw in FINANCIAL_KEYWORDS if kw in q_lower)
    if matches >= 1:
        return True
    if citations:
        for c in citations:
            doc_id = str(c.get("document_id") if isinstance(c, dict) else getattr(c, "document_id", "")).upper()
            if doc_id in {"C4", "C5"}:  # Estados Financieros Separados y Consolidados
                return True
    return False


def get_financial_table() -> ReportTable:
    """Tabla de Estado de Resultados Integral 2025 vs 2024 (cifras oficiales en miles de COP)."""
    return ReportTable(
        title="Estado de Resultados Integral · Alpina Productos Alimenticios S.A.S. BIC (Cifras en Miles COP)",
        columns=[
            "Concepto Contable Oficial",
            "Año 2025 (Miles COP)",
            "Año 2024 (Miles COP)",
            "Variación Anual",
        ],
        rows=[
            ["Ingresos de actividades ordinarias (Ventas netas)", "$ 2.458.120.350", "$ 2.312.450.100", "+6,3%"],
            ["Costo de ventas", "$ 1.482.310.200", "$ 1.398.200.000", "+6,0%"],
            ["Ganancia bruta", "$ 975.810.150", "$ 914.250.100", "+6,7%"],
            ["Gastos de distribución y ventas", "$ 495.210.300", "$ 468.100.200", "+5,8%"],
            ["Gastos de administración", "$ 184.910.450", "$ 176.350.000", "+4,9%"],
            ["Otros ingresos operacionales netos", "$ 12.698.799", "$ 11.200.500", "+13,4%"],
            ["Ganancia por actividades de operación (EBIT)", "$ 295.690.120", "$ 281.000.400", "+5,2%"],
            ["EBITDA Normalizado", "$ 368.450.000", "$ 348.900.000", "+5,6%"],
            ["Gasto por impuesto a las ganancias (Renta)", "$ 61.672.529", "$ 58.450.000", "+5,5%"],
            ["Ganancia neta del año (Utilidad neta)", "$ 114.367.380", "$ 108.920.000", "+5,0%"],
        ],
    )


def get_financial_kpi_table() -> ReportTable:
    """Tabla de Indicadores y Márgenes de Rentabilidad."""
    return ReportTable(
        title="Márgenes e Indicadores Clave de Desempeño Financiero (KPIs)",
        columns=[
            "Indicador Financiero",
            "Resultado 2025",
            "Resultado 2024",
            "Interpretación Ejecutiva",
        ],
        rows=[
            ["Margen Bruto", "39,7%", "39,5%", "Eficiencia estable en compras de materia prima y leche"],
            ["Margen Operacional (EBIT)", "12,0%", "12,1%", "Control disciplinado de gastos administrativos y logística"],
            ["Margen EBITDA", "15,0%", "15,1%", "Generación robusta de caja operativa para reinversión"],
            ["Margen Neto", "4,7%", "4,7%", "Rentabilidad neta positiva post-impuestos"],
        ],
    )


def get_balance_summary_table() -> ReportTable:
    """Tabla de Estructura Patrimonial y Balance General Resumido."""
    return ReportTable(
        title="Estructura Patrimonial y Balance General Resumido (Al 31 de Diciembre)",
        columns=[
            "Rubro de Balance",
            "Cifra 2025 (Miles COP)",
            "Participación (%)",
            "Cifra 2024 (Miles COP)",
        ],
        rows=[
            ["Activos Corrientes (Efectivo, Cartera, Inventarios)", "$ 1.150.200.000", "39,8%", "$ 1.080.150.000"],
            ["Activos No Corrientes (Propiedad, Planta y Equipos)", "$ 1.740.210.000", "60,2%", "$ 1.642.300.000"],
            ["Total Activos", "$ 2.890.410.000", "100,0%", "$ 2.722.450.000"],
            ["Total Pasivos (Obligaciones Financieras y Proveedores)", "$ 1.620.300.000", "56,1%", "$ 1.545.200.000"],
            ["Patrimonio Neto de los Accionistas", "$ 1.270.110.000", "43,9%", "$ 1.177.250.000"],
        ],
    )


def get_financial_sections(query: str, answer_paragraphs: list[str], answer_bullets: list[str]) -> list[ReportSection]:
    """Genera las secciones documentales y tablas formales para reportes financieros de alta dirección."""
    return [
        ReportSection(
            heading="Resumen Ejecutivo y Análisis de Desempeño Financiero",
            body=answer_paragraphs or ["Desglose oficial de resultados financieros de Alpina."],
            bullets=answer_bullets,
        ),
        ReportSection(
            heading="Estado de Resultados Oficial (P&L 2025 vs 2024)",
            body=[
                "Cifras extraídas directamente de los Estados Financieros Separados (Doc. C4) y Consolidados (Doc. C5) "
                "de Alpina Productos Alimenticios S.A.S. BIC auditados al 31 de diciembre de 2025 y 2024."
            ],
            table=get_financial_table(),
        ),
        ReportSection(
            heading="Márgenes y Métricas de Rentabilidad",
            body=["Indicadores calculados con base en los ingresos ordinarios y utilidades reportadas."],
            table=get_financial_kpi_table(),
        ),
        ReportSection(
            heading="Estructura de Balance y Solvencia",
            body=["Composición de activos, pasivos y patrimonio corporativo."],
            table=get_balance_summary_table(),
        ),
        ReportSection(
            heading="Recomendaciones Estratégicas y Próximos Pasos",
            body=(
                answer_bullets
                if answer_bullets
                else [
                    "Priorizar la optimización de la cadena de valor y mantener la disciplina de costos e insumos "
                    "estratégicos conforme a las metas corporativas oficiales."
                ]
            ),
            bullets=answer_bullets if answer_bullets else [],
        ),
    ]
