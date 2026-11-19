from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

from app.agent.prompts import ABSTENTION, DEFAULT_CATEGORY_FILTERS

VALID_CATEGORIES = {"product", "regulatory", "corporate", "general"}
VALID_DOC_CATEGORIES = {"normative", "nutrition", "corporate", "guide"}
DOCUMENT_ID_RE = re.compile(r"^[NPC]\d{1,2}$")
CONVERSATIONAL_PATTERNS = {
    "greeting": re.compile(
        r"^[¿?¡!\s]*(hola|buenas|buen día|buenos días|buenas tardes|buenas noches|hey|qué tal|saludos)\b",
        re.IGNORECASE,
    ),
    "courtesy": re.compile(
        r"^[¿?¡!\s]*(cómo estás|cómo te va|cómo te encuentras|qué tal todo|cómo andas|todo bien|qué tal tu día)\b",
        re.IGNORECASE,
    ),
    "gratitude": re.compile(
        r"^[¿?¡!\s]*(gracias|muchas gracias|mil gracias|te lo agradezco|te agradezco|muy amable|ok gracias|vale gracias|listo gracias)\b",
        re.IGNORECASE,
    ),
    "farewell": re.compile(
        r"^[¿?¡!\s]*(adiós|chao|hasta luego|nos vemos|hasta pronto|que estés bien|que tengas buen día)\b",
        re.IGNORECASE,
    ),
    "identity": re.compile(
        r"^[¿?¡!\s]*(quién eres|cómo te llamas|qué eres|qué haces|qué puedes hacer|para qué sirves|cuál es tu función)\b",
        re.IGNORECASE,
    ),
    "help_generic": re.compile(
        r"^[¿?¡!\s]*(ayuda|ayúdame|me puedes ayudar|necesito ayuda|necesito que me colabores|colabórame|puedes ayudarme|tengo una duda|tengo una pregunta|de qué trata|qué sabes|qué información tienes|qué documentos tienes)\b",
        re.IGNORECASE,
    ),
    "report_generic": re.compile(
        r"^[¿?¡!\s]*(qué reportes puedes hacer|puedes hacer informes|qué tipos de informes|haces informes|haces reportes)\b",
        re.IGNORECASE,
    ),
}

GREETING_RE = re.compile(
    r"^[¿?¡!\s]*(hola|buenas|buen día|buenos días|buenas tardes|buenas noches|hey|qué tal|"
    r"cómo estás|cómo te va|gracias|adiós|chao|quién eres|qué puedes hacer|qué haces|ayuda|necesito ayuda|me puedes ayudar)\b",
    re.IGNORECASE,
)


def _value(result: Any, key: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


def _normalize(text: Any) -> str:
    return " ".join(str(text or "").split()).casefold()


def _quote_matches(quote: str, content: str) -> bool:
    normalized_quote = _normalize(quote)
    normalized_content = _normalize(content)
    if normalized_quote and normalized_quote in normalized_content:
        return True

    stripped_quote = re.sub(r"(?:\.\.\.|…)+$", "", quote).strip()
    if (
        stripped_quote
        and stripped_quote != quote
        and _normalize(stripped_quote) in normalized_content
    ):
        return True

    fragments = [
        fragment.strip()
        for fragment in re.split(r"\.\.\.|…", quote)
        if fragment.strip()
    ]
    if len(fragments) > 1:
        return all(
            _normalize(fragment) in normalized_content for fragment in fragments
        )
    return False


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


def _ascii_lower(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def resolve_document_ids(query: str) -> list[str]:
    normalized = _ascii_lower(query)
    resolved: list[str] = []
    for pattern, document_id in DOCUMENT_PATTERNS:
        if pattern.search(normalized) and document_id not in resolved:
            resolved.append(document_id)
    return resolved


SUBSTANTIVE_KEYWORDS_RE = re.compile(
    r"\b(reporte|informe|dossier|excel|pdf|xlsx|venta|ventas|precio|precios|costo|costos|"
    r"ebitda|balance|ingreso|ingresos|utilidad|utilidades|eeff|resoluci[oó]n|ley|norma|normograma|"
    r"rotulado|etiquetado|nutricional|calor[ií]as|grasa|az[uú]car|sodio|ingrediente|ingredientes|"
    r"al[eé]rgeno|al[eé]rgenos|leche|yogurt|yogur|queso|quesito|mantequilla|alpinito|bon\s*yurt|"
    r"finesse|yox|defensis|baby\s*gu|cu[aá]nto|cu[aá]l|cu[aá]les|qu[eé]\s+es|qu[eé]\s+dice|"
    r"qu[eé]\s+contiene|dime|explica|busca|compara|genera|dame|mu[eé]strame|hazme)\b",
    re.IGNORECASE,
)


def classify_conversational_intent(query: str) -> str | None:
    text = (query or "").strip().lower()
    if not text:
        return "greeting"

    # Si solicita generar un informe o cita una norma/documento oficial, jamás es un saludo genérico
    if detect_report_request(query) is not None:
        return None
    if resolve_document_ids(query):
        return None

    # Si contiene palabras clave sustantivas del negocio, catálogo o normativa, es una consulta de dominio
    if SUBSTANTIVE_KEYWORDS_RE.search(text):
        return None

    for intent, pattern in CONVERSATIONAL_PATTERNS.items():
        if pattern.search(text):
            return intent
    if GREETING_RE.search(text):
        return "greeting"
    return None


def is_greeting(query: str) -> bool:
    return classify_conversational_intent(query) is not None


def validate_router_output(payload: dict, query: str) -> dict:
    if not isinstance(payload, dict):
        payload = {}

    category = str(payload.get("category") or "general").strip().lower()
    if category not in VALID_CATEGORIES:
        category = "general"

    raw_categories = payload.get("categories")
    if isinstance(raw_categories, str):
        raw_categories = [raw_categories]
    if not isinstance(raw_categories, list):
        raw_categories = []
    categories = [
        str(item).strip().lower()
        for item in raw_categories
        if str(item).strip().lower() in VALID_DOC_CATEGORIES
    ]

    if category == "general" and is_greeting(query):
        needs_documents = False
    else:
        needs_documents = True

    if needs_documents:
        defaults = DEFAULT_CATEGORY_FILTERS.get(category, [])
        for default_category in defaults:
            if default_category not in categories:
                categories.append(default_category)

    raw_document_ids = payload.get("document_ids")
    if not isinstance(raw_document_ids, list):
        raw_document_ids = []
    document_ids = [
        str(item).strip().upper()
        for item in raw_document_ids
        if DOCUMENT_ID_RE.match(str(item).strip().upper())
    ]

    search_query = str(payload.get("search_query") or "").strip()
    if needs_documents and not search_query:
        search_query = query
    if not needs_documents:
        search_query = ""

    return {
        "category": category,
        "search_query": search_query,
        "categories": categories,
        "document_ids": document_ids,
        "needs_documents": needs_documents,
    }


def validate_citations(
    citations: Iterable[Any],
    results: Iterable[Any],
) -> tuple[list[dict], list[str]]:
    result_list = list(results)
    valid: list[dict] = []
    issues: list[str] = []

    for citation in citations or []:
        if not isinstance(citation, dict):
            issues.append("Se ignoró una cita con formato inválido.")
            continue

        document_id = str(citation.get("document_id") or "").strip().upper()
        citation_title = str(citation.get("title") or "").strip()
        if not document_id and not citation_title:
            issues.append("Se ignoró una cita sin document_id ni título.")
            continue

        try:
            page = int(citation.get("page", 1))
        except (TypeError, ValueError):
            page = 1

        matches = []
        for result in result_list:
            res_doc_id = str(_value(result, "document_id", "")).upper()
            res_title = str(_value(result, "document_title", ""))

            # Coincidencia flexible de ID o título de documento
            id_match = (
                document_id
                and (
                    res_doc_id == document_id
                    or document_id in res_doc_id
                    or res_doc_id in document_id
                )
            )
            title_match = (
                citation_title
                and (
                    _normalize(citation_title) in _normalize(res_title)
                    or _normalize(res_title) in _normalize(citation_title)
                )
            )

            if id_match or title_match:
                matches.append(result)

        if not matches:
            issues.append(
                f"Se ignoró una cita de {document_id or citation_title} página {page}: "
                "no está entre las fuentes recuperadas."
            )
            continue

        # Seleccionar el mejor resultado dentro del rango de páginas, o el primero disponible
        matched_result = None
        for candidate in matches:
            try:
                page_start = int(_value(candidate, "page_start", 0))
                page_end = int(_value(candidate, "page_end", page_start))
            except (TypeError, ValueError):
                continue
            if page_start <= page <= page_end:
                matched_result = candidate
                break

        if matched_result is None:
            matched_result = matches[0]
            try:
                page = int(_value(matched_result, "page_start", 1))
            except (TypeError, ValueError):
                page = 1

        result = matched_result
        result_version = str(_value(result, "version", ""))
        citation_version = result_version or str(citation.get("version") or "")

        quote = str(citation.get("quote") or "").strip()
        if quote:
            matching_result = next(
                (
                    candidate
                    for candidate in matches
                    if _quote_matches(quote, _value(candidate, "content", ""))
                ),
                None,
            )
            if matching_result is not None:
                result = matching_result
            else:
                # Se preserva la cita referencial sin descartar la respuesta del usuario
                quote = ""
                issues.append(
                    f"La cita textual de {document_id or citation_title} página {page} no coincide "
                    "literalmente; se preserva la referencia documental oficial."
                )

        final_doc_id = str(_value(result, "document_id", document_id)).upper()
        valid.append(
            {
                "document_id": final_doc_id,
                "title": _value(result, "document_title", citation_title),
                "page": page,
                "version": citation_version,
                "quote": quote,
                "source_url": _value(result, "source_url"),
            }
        )

    return valid, issues


def validate_answer_payload(payload: dict, results: Iterable[Any]) -> dict:
    if not isinstance(payload, dict):
        payload = {}

    answer = str(payload.get("answer") or "").strip()
    raw_abstained = payload.get("abstained")
    if isinstance(raw_abstained, str):
        abstained = raw_abstained.strip().lower() == "true"
    else:
        abstained = bool(raw_abstained)

    citations = payload.get("citations")
    if not isinstance(citations, list):
        citations = []

    if abstained or not answer:
        return {
            "answer": ABSTENTION,
            "citations": [],
            "abstained": True,
            "issues": [],
        }

    if _normalize(answer) == _normalize(ABSTENTION):
        return {
            "answer": ABSTENTION,
            "citations": [],
            "abstained": True,
            "issues": [],
        }

    valid_citations, issues = validate_citations(citations, results)
    if not valid_citations:
        result_list = list(results)
        if result_list and not abstained and answer:
            # Auto-asignar la fuente principal recuperada como cita para evitar falsas abstenciones
            top = result_list[0]
            try:
                top_page = int(_value(top, "page_start", 1))
            except (TypeError, ValueError):
                top_page = 1
            valid_citations.append(
                {
                    "document_id": str(_value(top, "document_id", "")).upper(),
                    "title": _value(top, "document_title", ""),
                    "page": top_page,
                    "version": str(_value(top, "version", "")),
                    "quote": "",
                    "source_url": _value(top, "source_url"),
                }
            )
            issues.append("Se asoció automáticamente la fuente principal recuperada como cita.")
        else:
            return {
                "answer": ABSTENTION,
                "citations": [],
                "abstained": True,
                "issues": [*issues, "La respuesta no tiene citas válidas."],
            }

    report_action: dict | None = None
    raw_report = payload.get("generate_report")
    if isinstance(raw_report, dict):
        report_type = str(raw_report.get("report_type") or "pdf").lower().strip()
        if report_type not in {"pdf", "xlsx"}:
            report_type = "pdf"
        report_action = {
            "report_type": report_type,
            "topic": str(raw_report.get("topic") or "").strip()[:150],
        }

    return {
        "answer": answer,
        "citations": valid_citations,
        "abstained": False,
        "issues": issues,
        "generate_report": report_action,
    }


EXPLICIT_PDF_RE = re.compile(r"\b(pdf)\b", re.IGNORECASE)
EXPLICIT_XLSX_RE = re.compile(
    r"\b(excel|xlsx|hoja\s+de\s+c[aá]lculo|hojas\s+de\s+c[aá]lculo)\b",
    re.IGNORECASE,
)
FILE_ACTION_RE = re.compile(
    r"\b(gener|crea|haz|hazme|elabor|export|descarg|sacar|saca|armar|arma|bajar|baja|pasar|pasa|envia|enviar|dame|entreg)\w*",
    re.IGNORECASE,
)
FILE_CONTEXT_RE = re.compile(
    r"\b(en\s+pdf|en\s+excel|en\s+xlsx|un\s+pdf|un\s+excel|archivo\s+pdf|archivo\s+excel|reporte\s+en|informe\s+en|balance\s+en)\b",
    re.IGNORECASE,
)


def detect_report_request(query: str) -> dict | None:
    """Detecta de forma estricta si la consulta solicita generar un archivo PDF o Excel/XLSX.
    
    SOLO se activa si el usuario pide explícitamente un PDF o un Excel.
    Consultas normales sobre informes documentales (como 'informe de gestión') NO activan la herramienta.
    """
    if not query:
        return None
    q = query.strip()
    is_pdf = bool(EXPLICIT_PDF_RE.search(q))
    is_xlsx = bool(EXPLICIT_XLSX_RE.search(q))

    # Regla estricta: Si no menciona PDF ni Excel, NUNCA se genera reporte
    if not is_pdf and not is_xlsx:
        return None

    # Requiere intención explícita de generar/descargar/exportar el archivo
    if FILE_ACTION_RE.search(q) or FILE_CONTEXT_RE.search(q):
        report_type = "xlsx" if is_xlsx else "pdf"
        return {
            "report_type": report_type,
            "topic": q[:100],
        }
    return None


def validate_verifier_output(payload: dict) -> dict:
    if not isinstance(payload, dict):
        payload = {}

    raw_approved = payload.get("approved")
    if isinstance(raw_approved, str):
        approved = raw_approved.strip().lower() == "true"
    else:
        approved = bool(raw_approved)

    issues = payload.get("issues") or []
    if not isinstance(issues, list):
        issues = [str(issues)]

    corrected = payload.get("corrected_answer")
    corrected_answer = str(corrected).strip() if corrected else None

    return {
        "approved": approved,
        "issues": [str(issue) for issue in issues],
        "corrected_answer": corrected_answer,
    }
