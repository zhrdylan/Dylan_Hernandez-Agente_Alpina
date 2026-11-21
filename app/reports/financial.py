from __future__ import annotations

import re
from typing import Any

from app.core.utils import get_value

FINANCIAL_KEYWORDS = {
    "venta", "ventas", "ingreso", "ingresos", "financiero",
    "financiera", "financieros", "financieras", "balance", "ebitda", "utilidad", "utilidades",
    "eeff", "costo", "costos", "p&l", "perdida", "pérdida", "ganancia",
    "ganancias", "activo", "activos", "pasivo", "pasivos", "patrimonio",
    "ejercicio", "tributar", "tributario", "tributaria", "tributarios", "tributarias", "impuesto", "impuestos", "renta",
    "margen", "márgenes", "dividendo", "dividendos", "estados financieros",
}
FINANCIAL_KEYWORD_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(term).replace(r"\ ", r"\s+") for term in sorted(FINANCIAL_KEYWORDS)) + r")\b",
    re.IGNORECASE,
)
STATEMENT_SCOPES = {"C4": "Separados", "C5": "Consolidados"}
STATEMENT_METRICS = (
    "Ingresos de actividades ordinarias",
    "Costo de ventas",
    "Ganancia bruta",
    "Resultados de actividades de la operación",
    "Resultado neto del año",
)
STATEMENT_PERIODS_RE = re.compile(r"\b(?:Notas|Años)\s+((?:19|20)\d{2})\s+((?:19|20)\d{2})\b", re.IGNORECASE)
STATEMENT_AMOUNT_RE = re.compile(r"(?<!\w)(?:\(\s*)?-?\d+(?:[.,]\d{3})*(?:\s*\))?")
DETAILED_FINANCIAL_QUESTION_RE = re.compile(
    r"\b(?:ebitda|m[aá]rgen\w*|crecimiento|causas?|segmentos?|desglos\w*|recomend\w*|"
    r"por\s+qu[eé]|porcent\w*|activos?|pasivos?|patrimonio)\b",
    re.IGNORECASE,
)


def is_financial_query(query: str, citations: list[Any] | None = None) -> bool:
    return bool(FINANCIAL_KEYWORD_RE.search(query or "")) or any(
        str(get_value(citation, "document_id", "")).upper() in STATEMENT_SCOPES
        for citation in citations or []
    )


def financial_statement_answer(query: str, results: list[dict]) -> dict | None:
    """Extrae las cifras comparables de los estados de resultados citados."""
    if DETAILED_FINANCIAL_QUESTION_RE.search(query):
        return None

    requested_years = list(dict.fromkeys(re.findall(r"\b(?:19|20)\d{2}\b", query)))
    columns: list[str] = []
    amounts: dict[str, list[str]] = {metric: [] for metric in STATEMENT_METRICS}
    citations: list[dict] = []
    included_scopes: set[str] = set()
    for index, source in enumerate(results, start=1):
        scope = STATEMENT_SCOPES.get(source.get("document_id"))
        content = source["content"]
        periods = STATEMENT_PERIODS_RE.search(content)
        if not scope or scope in included_scopes or not periods or "miles de pesos" not in content.casefold():
            continue
        years = periods.groups()
        selected = requested_years or [years[0]]
        if not all(year in years for year in selected):
            return None

        rows = {}
        for line in content.splitlines():
            line = line.strip()
            for metric in STATEMENT_METRICS:
                if line.startswith(metric):
                    values = STATEMENT_AMOUNT_RE.findall(line[len(metric):])
                    if len(values) >= len(years):
                        rows[metric] = (line, values[-len(years):])
        if set(rows) != set(STATEMENT_METRICS):
            continue
        included_scopes.add(scope)
        columns.extend(f"{scope} {year}" for year in selected)
        for metric, (_, values) in rows.items():
            amounts[metric].extend(values[years.index(year)].strip() for year in selected)
        citations.append({"source": index, "quote": rows[STATEMENT_METRICS[0]][0]})

    if not citations:
        return None

    headers = ["Concepto", *columns]
    table = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *["| " + " | ".join((metric, *amounts[metric])) + " |" for metric in STATEMENT_METRICS],
    ]
    return {
        "answer": "Los estados de resultados de Alpina reportan estas cifras en miles de pesos colombianos.\n\n"
        + "\n".join(table),
        "citations": citations,
        "abstained": False,
    }
