from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

from app.agent.prompts import ABSTENTION, DEFAULT_CATEGORY_FILTERS

VALID_CATEGORIES = {"product", "regulatory", "corporate", "general", "out_of_scope"}
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
    resolved = [token.upper() for token in re.findall(r"\b[npc]\d{1,2}\b", normalized)]
    for pattern, document_id in DOCUMENT_PATTERNS:
        if pattern.search(normalized) and document_id not in resolved:
            resolved.append(document_id)
    return list(dict.fromkeys(resolved))


GUARDRAIL_JAILBREAK_RE = re.compile(
    r"\b("
    r"cu[aá]l\s+es\s+tu\s+prompt|revela\s+tu\s+prompt|mu[eé]strame\s+tu\s+prompt|tu\s+system\s+prompt|"
    r"system\s*prompt|instrucciones\s+internas|reglas\s+internas|tu\s+prompt|ignore\s+all\s+previous|"
    r"ignore\s+previous\s+instructions|olvida\s+tus\s+instrucciones|act\s+as\s+a\s+dan|jailbreak|"
    r"developer\s+mode|dan\s+mode"
    r")\b",
    re.IGNORECASE,
)

GUARDRAIL_MALICIOUS_RE = re.compile(
    r"\b("
    r"hacking|hackear|exploit|malware|keylogger|ddos|inyecci[oó]n\s+sql|sql\s+injection|"
    r"script\s+de\s+hacking|script\s+en\s+python\s+de\s+hacking|ataque\s+cibern[eé]tico|"
    r"vulnerabilidad\s+zero-day|payload\s+malicioso|crear\s+virus"
    r")\b",
    re.IGNORECASE,
)

GUARDRAIL_RESPONSE = (
    "Como asistente corporativo de Alpina, mi labor está orientada exclusivamente a resolver consultas "
    "sobre nuestro portafolio de productos, tablas nutricionales, normativas de etiquetado en Colombia y "
    "reportes corporativos oficiales.\n\n"
    "No tengo autorización para generar código ajeno, brindar asistencia sobre explotación/hacking ni "
    "divulgar configuraciones o instrucciones internas del sistema. ¿En qué información sobre nuestros "
    "productos o documentos oficiales te puedo colaborar hoy?"
)
SCOPE_RESPONSE = (
    "Puedo ayudarte con productos de Alpina, normas de etiquetado y documentos corporativos. "
    "También puedo preparar informes sobre esos temas en PDF, Excel o Word."
)

CODE_REQUEST_RE = re.compile(
    r"\b(?:codigo|script|programa)\s+(?:(?:escrito\s+)?en\s+)?"
    r"(?:python|py|javascript|js|typescript|java|php|html|css|c\+\+)\b"
    r"|\b(?:generame|genera|escribe|hazme|crea|dame)\s+(?:un\s+)?"
    r"(?:script|codigo)(?!\s+(?:de\s+barras|ean|sku|de\s+producto|de\s+la\s+politica))\b"
    r"|\bconvertidor\s+de\s+temperaturas?\b"
)


def detect_out_of_domain_or_jailbreak(query: str) -> str | None:
    """Detecta intentos de evasión, robo de prompt o solicitudes fuera de dominio."""
    if not query:
        return None
    q = query.strip()
    if GUARDRAIL_JAILBREAK_RE.search(q) or GUARDRAIL_MALICIOUS_RE.search(q):
        return GUARDRAIL_RESPONSE
    if CODE_REQUEST_RE.search(_ascii_lower(q)):
        return SCOPE_RESPONSE
    return None


def classify_conversational_intent(query: str) -> str | None:
    text = (query or "").strip("¿?¡!. \t\n").lower()
    if not text:
        return "greeting"
    for intent, pattern in CONVERSATIONAL_PATTERNS.items():
        if pattern.fullmatch(text):
            return intent
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

    needs_documents = category != "out_of_scope" and not is_greeting(query)

    if needs_documents:
        defaults = DEFAULT_CATEGORY_FILTERS.get(category, [])
        for default_category in defaults:
            if default_category not in categories:
                categories.append(default_category)

    raw_document_ids = payload.get("document_ids")
    if not isinstance(raw_document_ids, list):
        raw_document_ids = []
    explicit_ids = set(resolve_document_ids(query))
    document_ids = [
        str(item).strip().upper()
        for item in raw_document_ids
        if DOCUMENT_ID_RE.match(str(item).strip().upper()) and str(item).strip().upper() in explicit_ids
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
    *,
    matched_results: list[Any] | None = None,
) -> tuple[list[dict], list[str]]:
    result_list = list(results)
    valid: list[dict] = []
    issues: list[str] = []

    for citation in citations or []:
        if not isinstance(citation, dict):
            issues.append("Se ignoró una cita con formato inválido.")
            continue

        if "source" in citation:
            source = citation["source"]
            if type(source) is not int or not 1 <= source <= len(result_list):
                issues.append("La respuesta citó un fragmento que no aparece en las fuentes del turno.")
                continue
            result = result_list[source - 1]
            quote = str(citation.get("quote") or "").strip()
            if quote and not _quote_matches(quote, _value(result, "content", "")):
                quote = ""
                issues.append("Se conservó la referencia de página porque el texto citado difiere del fragmento.")
            if matched_results is not None:
                matched_results.append(result)
            valid.append(_citation_for_result(result, int(_value(result, "page_start")), quote))
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

            # Coincidencia exacta de ID o título de documento
            id_match = bool(document_id and res_doc_id == document_id)
            title_match = bool(
                citation_title
                and not document_id
                and _normalize(citation_title) == _normalize(res_title)
            )

            if id_match or title_match:
                matches.append(result)

        if not matches:
            issues.append(
                f"Se ignoró una cita de {document_id or citation_title} página {page}: "
                "no está entre las fuentes recuperadas."
            )
            continue

        quote = str(citation.get("quote") or "").strip()
        matched_result = None
        page_matches = []

        if quote:
            # Si se proporciona cita textual, DEBE coincidir con el contenido de algún fragmento
            matching_result = next(
                (
                    candidate
                    for candidate in matches
                    if _quote_matches(quote, _value(candidate, "content", ""))
                ),
                None,
            )
            if matching_result is not None:
                matched_result = matching_result
                try:
                    page = int(_value(matched_result, "page_start", page))
                except (TypeError, ValueError):
                    pass
            else:
                issues.append(
                    f"La cita textual de {document_id or citation_title} no coincide con el fragmento de la evidencia."
                )
                continue
        else:
            # Si es cita referencial sin frase, debe existir un fragmento que cubra esa página
            for candidate in matches:
                try:
                    page_start = int(_value(candidate, "page_start", 0))
                    page_end = int(_value(candidate, "page_end", page_start))
                except (TypeError, ValueError):
                    continue
                if page_start <= page <= page_end:
                    page_matches.append(candidate)

            if not page_matches:
                issues.append(
                    f"La página {page} de {document_id or citation_title} no está entre las fuentes recuperadas."
                )
                continue
            matched_result = page_matches[0]

        result_version = str(_value(matched_result, "version", ""))
        if matched_results is not None:
            if quote:
                matched_results.append(matched_result)
            else:
                matched_results.extend(
                    result for result in page_matches
                    if _value(result, "version", "") == result_version
                )

        bound = _citation_for_result(matched_result, page, quote)
        bound["version"] = result_version or str(citation.get("version") or "")
        bound["title"] = bound["title"] or citation_title
        valid.append(bound)

    return valid, issues


def _citation_for_result(result: Any, page: int, quote: str) -> dict:
    return {
        "document_id": str(_value(result, "document_id", "")).upper(),
        "title": _value(result, "document_title", ""),
        "page": page,
        "version": str(_value(result, "version") or ""),
        "quote": quote,
        "source_url": _value(result, "source_url"),
    }


NUMBER_RE = re.compile(r"(?<!\w)\d+(?:[.,]\d+)*")
GROUPED_INTEGER_RE = re.compile(r"\d{1,3}([.,])\d{3}(?:\1\d{3})*")


def extract_numbers_from_text(text: str) -> set[str]:
    """Normaliza agrupadores de miles y separadores decimales."""
    numbers = set()
    for token in NUMBER_RE.findall(text or ""):
        if GROUPED_INTEGER_RE.fullmatch(token):
            numbers.add(token.replace(",", "").replace(".", ""))
        else:
            integer, dot, decimals = token.replace(",", ".").partition(".")
            decimals = decimals.rstrip("0")
            numbers.add(f"{integer}{dot}{decimals}" if decimals else integer)
    return numbers


def verify_claims_against_evidence(
    answer: str,
    results: Iterable[Any],
) -> tuple[str, bool, list[str]]:
    """Valida cada afirmación y cifra material de la respuesta contra la evidencia documental exacta (R01).

    Detecta contradicciones numéricas materiales (ej. fuente dice 12 y respuesta dice 999).
    Si la respuesta afirma cifras no sustentadas o contradictorias, omite los hechos incompatibles
    o se abstiene si el núcleo de la respuesta queda sin sustento.
    """
    if not answer or answer.strip() == ABSTENTION.strip():
        return ABSTENTION, True, []

    result_list = list(results)
    if not result_list:
        return ABSTENTION, True, ["Sin evidencia documental para verificar afirmaciones."]

    evidence_numbers = extract_numbers_from_text(" ".join(
        str(_value(result, field) or "")
        for result in result_list
        for field in ("content", "document_title", "version")
    ))
    valid_lines: list[str] = []
    issues: list[str] = []

    for line in answer.splitlines():
        valid_sentences = []
        line = re.sub(r"[ \t]*\[FUENTE\s+\d+\]", "", line, flags=re.IGNORECASE)
        index = re.match(r"^\s*(?:#{1,6}\s+|\*\*)?\d+[.)]\s+", line)
        first_char = index.end() if index else 0
        for sentence in re.split(r"(?<=[.!?])(?=[ \t]+)", line[first_char:]):
            unsupported = extract_numbers_from_text(sentence) - evidence_numbers
            if unsupported:
                issues.append(f"Cifras sin respaldo en las fuentes citadas: {', '.join(sorted(unsupported))}.")
            else:
                valid_sentences.append(sentence)
        if valid_sentences:
            valid_lines.append((line[:first_char] + "".join(valid_sentences)).rstrip())

    filtered_answer = "\n".join(valid_lines).strip()
    if not filtered_answer:
        return ABSTENTION, True, issues

    return filtered_answer, False, issues


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

    if abstained:
        return {
            "answer": ABSTENTION,
            "citations": [],
            "abstained": True,
            "issues": [],
        }

    if not answer:
        return {
            "answer": ABSTENTION,
            "citations": [],
            "abstained": True,
            "issues": ["El modelo no entregó texto para la respuesta."],
        }

    if _normalize(answer) == _normalize(ABSTENTION):
        return {
            "answer": ABSTENTION,
            "citations": [],
            "abstained": True,
            "issues": [],
        }

    cited_results: list[Any] = []
    valid_citations, issues = validate_citations(citations, results, matched_results=cited_results)
    if not valid_citations:
        return {
            "answer": ABSTENTION,
            "citations": [],
            "abstained": True,
            "issues": [*issues, "La respuesta no tiene citas documentales válidas respaldadas en la evidencia."],
        }

    # Verificación rigurosa de afirmaciones materiales contra la evidencia (R01)
    filtered_answer, contradicted, claim_issues = verify_claims_against_evidence(answer, cited_results)
    issues.extend(claim_issues)
    if contradicted:
        return {
            "answer": ABSTENTION,
            "citations": [],
            "abstained": True,
            "issues": [*issues, "Respuesta rechazada por contener afirmaciones o cifras incompatibles con la fuente."],
        }
    answer = filtered_answer

    return {
        "answer": answer,
        "citations": valid_citations,
        "abstained": False,
        "issues": issues,
    }


EXPLICIT_PDF_RE = re.compile(r"\b(pdf)\b", re.IGNORECASE)
EXPLICIT_XLSX_RE = re.compile(
    r"\b(excel|xlsx|hoja\s+de\s+c[aá]lculo|hojas\s+de\s+c[aá]lculo)\b",
    re.IGNORECASE,
)
EXPLICIT_DOCX_RE = re.compile(r"\b(word|docx|doc)\b", re.IGNORECASE)
FILE_ACTION_RE = re.compile(
    r"\b(?:gen[eé]r|cr[eé]a|haz|elabor|export|descarg|saca|arma|baja|p[aá]sa|env[ií]a|dame|entreg|quiero|necesito|prep[aá]ra)\w*\b",
    re.IGNORECASE,
)
FILE_PREFIX_RE = re.compile(
    r"^(?:(?:me|por\s+favor|puedes?|podr[ií]as?|un|una|el|la|los|las|en|a|de|al|del|para|sobre|con|"
    r"formato|archivo|reporte|informe|documento|dossier|lo\s+anterior|lo\s+de\s+arriba)\b[\s,]*)+",
    re.IGNORECASE,
)
FILE_REFERENCE_RE = re.compile(
    r"^(?:(?:la\s+|el\s+|lo\s+)?(?:respuesta(?: anterior)?|texto anterior|tema anterior|anterior|"
    r"que acabas de decir|lo que me dijiste|eso|esto|lo mismo|lo de arriba))$"
)
FILE_TOPIC_CONNECTOR_RE = re.compile(r"^(?:(?:sobre|con|acerca\s+de|de|del|el|la|los|las)\b[\s,]*)+", re.IGNORECASE)


def detect_report_request(query: str) -> dict | None:
    """Detecta de forma estricta si la consulta solicita generar un archivo PDF, Excel/XLSX o Word/DOCX.
    
    SOLO se activa si el usuario pide explícitamente un PDF, Excel o Word.
    Consultas normales sobre informes documentales (como 'informe de gestión') NO activan la herramienta.
    """
    if not query:
        return None
    q = query.strip("¿?¡!. \t\n")
    for report_type, pattern in (("docx", EXPLICIT_DOCX_RE), ("xlsx", EXPLICIT_XLSX_RE), ("pdf", EXPLICIT_PDF_RE)):
        match = pattern.search(q)
        if match:
            break
    else:
        return None

    before = q[:match.start()].strip(" ,")
    after = re.sub(r"\bpor\s+favor\s*$", "", q[match.end():], flags=re.IGNORECASE).strip(" ,")
    action = FILE_ACTION_RE.search(before)
    prefix = FILE_PREFIX_RE.sub("", re.sub(r"\b(?:en|a)\s*$", "", before, flags=re.IGNORECASE).strip())
    if not action and prefix and not FILE_REFERENCE_RE.fullmatch(_ascii_lower(prefix)):
        return None

    if action:
        before = before[action.end():].strip()
    before = re.sub(r"\b(?:en|a)\s*$", "", before, flags=re.IGNORECASE).strip()
    topic = (FILE_TOPIC_CONNECTOR_RE.sub("", after) if after else FILE_PREFIX_RE.sub("", before)).strip(" ,")
    if FILE_REFERENCE_RE.fullmatch(_ascii_lower(topic)):
        topic = ""
    return {"report_type": report_type, "topic": topic}


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
