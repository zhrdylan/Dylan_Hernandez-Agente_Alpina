from __future__ import annotations

import re

from app.core.utils import ascii_fold

DOCUMENT_ID_RE = re.compile(r"[NPC][0-9]{1,2}")

OFFICIAL_DOCUMENT_TITLES = {
    "C1": "Informe de Gestión 2026 · Alpina",
    "C2": "Informe de Sostenibilidad 2025 · Alpina",
    "C3": "Informe Alpina BIC 2025",
    "C4": "Estados Financieros Separados 2025 · Alpina S.A.S. BIC",
    "C5": "Estados Financieros Consolidados 2025 · Alpina",
    "N1": "Ley 2120 de 2021 (Ley de Comida Chatarra)",
    "N2": "Resolución 810 de 2021 (Etiquetado Nutricional y Frontal)",
    "N3": "Resolución 2492 de 2022 (Sellos Frontales de Advertencia)",
    "N4": "Resolución 2025013945 de 2025",
    "N5": "Resolución 5109 de 2005",
    "N6": "Resolución 333 de 2011",
    "N7": "Resolución 2674 de 2013",
    "N8": "Normograma de aditivos alimentarios",
    "N9": "ABECE: aplicación Resolución 2492 de 2022 y Resolución 810 de 2021",
    "N10": "Consolidado normativo 2026",
    "N11": "Política de Calidad de Alpina",
    "P1": "Portafolio de Claims Nutricionales 2024",
    "P2": "Finesse y Yox con Defensis",
    "P3": "Alpi10",
    "P4": "Alpina Baby Gu",
}


DOCUMENT_PATTERNS = [
    (re.compile(r"\bley\s+2120\b"), "N1"),
    (re.compile(r"\bresolucion\s+810\b"), "N2"),
    (re.compile(r"\bresolucion\s+2492\b"), "N3"),
    (re.compile(r"\bresolucion\s+2025013945\b"), "N4"),
    (re.compile(r"\bresolucion\s+5109\b"), "N5"),
    (re.compile(r"\bresolucion\s+333\b"), "N6"),
    (re.compile(r"\bresolucion\s+2674\b"), "N7"),
    (re.compile(r"\bnormograma\b"), "N8"),
    (re.compile(r"\babece\b"), "N9"),
    (re.compile(r"\bconsolidado\s+normativo\b"), "N10"),
    (re.compile(r"\bpolitica\s+de\s+calidad\b"), "N11"),
    (re.compile(r"\bportafolio\s+de\s+claims\b"), "P1"),
    (re.compile(r"\bdefensis\b|\byox\b"), "P2"),
    (re.compile(r"\balpi10\b"), "P3"),
    (re.compile(r"\bbaby\s+gu\b|\balpina\s+baby\b"), "P4"),
    (re.compile(r"\binforme\s+de\s+gestion\b"), "C1"),
    (re.compile(r"\bsostenibilidad\b"), "C2"),
    (re.compile(r"\binforme\s+bic\b"), "C3"),
    (re.compile(r"\bestados\s+financieros\s+separados\b"), "C4"),
    (re.compile(r"\bestados\s+financieros\s+consolidados\b"), "C5"),
]


def resolve_document_ids(query: str) -> list[str]:
    normalized = ascii_fold(query).lower()
    resolved = [token.upper() for token in re.findall(r"\b[npc]\d{1,2}\b", normalized)]
    for pattern, document_id in DOCUMENT_PATTERNS:
        if pattern.search(normalized) and document_id not in resolved:
            resolved.append(document_id)
    return list(dict.fromkeys(resolved))
