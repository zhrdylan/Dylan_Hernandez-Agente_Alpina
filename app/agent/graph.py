from __future__ import annotations

import dataclasses
import functools
import logging
import re
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from psycopg_pool import ConnectionPool

from app.agent import prompts
from app.agent.llm import chat_json
from app.agent.progress import record_progress
from app.agent.validation import (
    SCOPE_RESPONSE,
    classify_conversational_intent,
    detect_out_of_domain_or_jailbreak,
    detect_report_request,
    resolve_document_ids,
    validate_answer_payload,
    validate_router_output,
)
from app.config import settings
from app.db.connection import connect
from app.products.search import catalog_nutrition_answer, search_products
from app.reports.financial import financial_statement_answer
from app.reports.service import create_report_record
from app.retrieval.coverage import needs_coverage
from app.retrieval.search import SearchFilters, coverage_search


class AgentState(MessagesState):
    chat_id: str
    session_id: str | None
    category: str
    search_query: str
    filters: dict
    needs_documents: bool
    results: list[dict]
    retrieval_failed: bool
    answer: str
    citations: list[dict]
    abstained: bool
    verified: bool
    issues: list[str]
    timings: dict[str, float]
    generated_report: dict | None
    report_request: dict | None
    pending_report_type: str | None
    last_verified: dict | None


RetrieveFn = Callable[[str, SearchFilters], list[dict]]


def _timing(state: AgentState, node: str, started: float) -> dict[str, float]:
    timings = dict(state.get("timings") or {})
    timings[node] = round(time.perf_counter() - started, 2)
    return timings


def _tracked_progress(node: str):
    def decorator(function):
        @functools.wraps(function)
        def wrapper(state, *args, **kwargs):
            chat_id = state.get("chat_id") if isinstance(state, dict) else ""
            record_progress(chat_id, node, "running")
            try:
                result = function(state, *args, **kwargs)
                record_progress(chat_id, node, "done")
                return result
            except Exception:
                record_progress(chat_id, node, "error")
                raise

        return wrapper

    return decorator


def _last_user_query(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
        if isinstance(message, dict) and message.get("role") in {"user", "human"}:
            return str(message.get("content") or "")
    return ""


def _default_retrieve(query: str, filters: SearchFilters) -> list[dict]:
    results = []
    products = []
    with connect() as conn:
        if not filters.document_ids and (not filters.categories or "nutrition" in filters.categories):
            try:
                with conn.transaction():
                    products = search_products(conn, query, limit=3)
            except Exception as exc:
                logger.warning("Fallo en búsqueda de productos: %s", exc)

        try:
            with conn.transaction():
                results = coverage_search(conn, query, filters=filters)
        except Exception:
            if not products:
                raise
            logger.warning("Fallo en búsqueda de documentos. El catálogo sigue disponible.")

    return [dataclasses.asdict(result) for result in [*products, *results]]


CONVERSATIONAL_RESPONSES = {
    "greeting": "¡Hola! Soy el asistente de Alpina. ¿Qué deseas consultar?",
    "courtesy": "¡Muy bien, gracias! ¿Qué información de Alpina buscas?",
    "gratitude": "¡Con gusto!",
    "farewell": "¡Hasta pronto!",
}
PRODUCT_RE = re.compile(
    r"\b(alpinito|bon\s*yurt|finesse|yox|defensis|kumis|arequipe|baby\s*gu|"
    r"yogurt?|leche\s+deslactosada|queso\s+campesino|quesito|avena\s+alpina|soplamin|"
    r"c[oó]digo\s+de\s+barras|ean|sku)\b",
    re.IGNORECASE,
)
FINANCIAL_RESULTS_RE = re.compile(
    r"\b(?:resultados?\s+financier[oa]s?|desempeño\s+financiero)\b", re.IGNORECASE,
)
FRONT_LABEL_RE = re.compile(
    r"\b(?:etiquetado\s+frontal|sellos?\s+(?:frontales?|de\s+advertencia))\b", re.IGNORECASE,
)


@_tracked_progress("supervisor")
def supervisor_node(state: AgentState) -> dict:
    started = time.perf_counter()
    messages = list(state.get("messages") or [])
    query = _last_user_query(messages)
    history = prompts.format_history(messages[:-1])
    issues = list(state.get("issues") or [])

    guardrail_answer = detect_out_of_domain_or_jailbreak(query)
    if guardrail_answer:
        return {
            "category": "guardrail",
            "needs_documents": False,
            "answer": guardrail_answer,
            "pending_report_type": None,
            "issues": ["Solicitud fuera del alcance documental."],
            "timings": _timing(state, "supervisor", started),
        }

    report_request = detect_report_request(query)
    if report_request and not report_request["topic"]:
        previous = state.get("last_verified") or {}
        return {
            "category": previous.get("category") or "general",
            "needs_documents": False,
            "answer": previous.get("answer") or prompts.REPORT_TOPIC_REQUEST,
            "citations": previous.get("citations") or [],
            "report_request": report_request if previous else None,
            "pending_report_type": None if previous else report_request["report_type"],
            "timings": _timing(state, "supervisor", started),
        }

    intent = classify_conversational_intent(query)
    if intent is not None:
        return {
            "category": "general",
            "needs_documents": False,
            "answer": CONVERSATIONAL_RESPONSES.get(intent, SCOPE_RESPONSE),
            "timings": _timing(state, "supervisor", started),
        }

    if not report_request and state.get("pending_report_type"):
        report_request = {"report_type": state["pending_report_type"], "topic": query}
    subject = report_request["topic"] if report_request else query
    resolved_ids = resolve_document_ids(query)
    financial_summary = FINANCIAL_RESULTS_RE.search(subject)
    if not resolved_ids and financial_summary:
        named_scopes = [
            doc_id for doc_id, pattern in (("C4", r"\bseparad[oa]s?\b"), ("C5", r"\bconsolidad[oa]s?\b"))
            if re.search(pattern, subject, re.IGNORECASE)
        ]
        resolved_ids = named_scopes or ["C4", "C5"]
    if resolved_ids == ["N2"] and FRONT_LABEL_RE.search(subject) and not re.search(
        r"\b(?:original|sin modificaciones)\b", subject, re.IGNORECASE,
    ):
        resolved_ids.append("N3")
    filters: dict[str, Any] = {"coverage": needs_coverage(subject)}
    search_query = subject
    if resolved_ids:
        if set(resolved_ids) <= {"C4", "C5"} and financial_summary:
            filters["focus_query"] = '"ingresos de actividades ordinarias" "costo de ventas" "resultado neto del año"'
        if set(resolved_ids) <= {"N2", "N3"} and FRONT_LABEL_RE.search(subject):
            filters["focus_query"] = '"forma del sello de advertencia" OR "forma del sello frontal de advertencia" "octagonal"'
        if any(doc_id.startswith("C") or doc_id == "N11" for doc_id in resolved_ids):
            category = "corporate"
        elif any(doc_id.startswith("P") for doc_id in resolved_ids):
            category = "product"
        else:
            category = "regulatory"
        filters["document_ids"] = resolved_ids
    elif PRODUCT_RE.search(subject) and not history:
        category = "product"
        filters["categories"] = ["nutrition"]
    else:
        try:
            payload = chat_json(
                settings.groq_model_router,
                prompts.ROUTER_SYSTEM,
                prompts.build_router_user(subject, history),
                max_tokens=650,
                fallback_model=settings.groq_model_fallback,
                schema=prompts.ROUTER_SCHEMA,
            )
            router = validate_router_output(payload, subject)
        except Exception as exc:
            router = validate_router_output({}, subject)
            issues.append(f"No se pudo clasificar la consulta con Groq: {exc}")
        category = router["category"]
        if category == "out_of_scope":
            return {
                "category": "guardrail",
                "needs_documents": False,
                "answer": SCOPE_RESPONSE,
                "pending_report_type": None,
                "issues": ["Solicitud fuera del alcance documental."],
                "timings": _timing(state, "supervisor", started),
            }
        search_query = router["search_query"] or subject
        filters["categories"] = router["categories"]

    return {
        "category": category,
        "search_query": search_query,
        "filters": filters,
        "needs_documents": True,
        "report_request": report_request,
        "pending_report_type": None,
        "issues": issues,
        "timings": _timing(state, "supervisor", started),
    }


@_tracked_progress("retrieve")
def retrieve_node(state: AgentState, retrieve_fn: RetrieveFn) -> dict:
    started = time.perf_counter()
    issues = list(state.get("issues") or [])
    query = state.get("search_query") or _last_user_query(list(state.get("messages") or []))
    if not state.get("needs_documents", True) or not query:
        return {"results": [], "timings": _timing(state, "retrieve", started)}

    try:
        filters = SearchFilters(**(state.get("filters") or {}))
        results = retrieve_fn(query, filters)
        if not results and filters.categories:
            results = retrieve_fn(query, dataclasses.replace(filters, categories=None))
            if results:
                issues.append("Se amplió la búsqueda porque los filtros iniciales no devolvieron fuentes.")
    except Exception as exc:
        logger.exception("No se pudo completar la recuperación de fuentes")
        return {
            "results": [],
            "retrieval_failed": True,
            "issues": [*issues, f"Búsqueda documental interrumpida ({type(exc).__name__})."],
            "timings": _timing(state, "retrieve", started),
        }

    return {"results": results, "issues": issues, "timings": _timing(state, "retrieve", started)}


@_tracked_progress("answer")
def answer_node(state: AgentState) -> dict:
    started = time.perf_counter()
    if not state.get("needs_documents", True):
        return {"timings": _timing(state, "answer", started)}

    messages = list(state.get("messages") or [])
    query = _last_user_query(messages)
    report = state.get("report_request")
    subject = report["topic"] if report else query
    results = list(state.get("results") or [])
    issues = list(state.get("issues") or [])

    if not results:
        return {
            "answer": prompts.RETRIEVAL_UNAVAILABLE if state.get("retrieval_failed") else prompts.ABSTENTION,
            "citations": [],
            "abstained": True,
            "issues": issues if state.get("retrieval_failed") else [*issues, "La búsqueda no devolvió fuentes."],
            "timings": _timing(state, "answer", started),
        }

    category = state.get("category") or "general"
    answer_results = results[:6] if (state.get("filters") or {}).get("coverage") else results[:4]
    task = f"Prepara un informe documental sobre el tema indicado. {subject}" if report else subject
    if {"N2", "N3"}.issubset((state.get("filters") or {}).get("document_ids") or []) and FRONT_LABEL_RE.search(subject):
        task += "\nDistingue el texto original de la Resolución 810 y los cambios de la Resolución 2492."
    try:
        direct_answer = None
        if category == "product":
            direct_answer = catalog_nutrition_answer(subject, answer_results)
        elif category == "corporate" and FINANCIAL_RESULTS_RE.search(subject):
            direct_answer = financial_statement_answer(subject, answer_results)

        payload = direct_answer or chat_json(
            settings.groq_model_answer,
            prompts.ANSWER_SYSTEM,
            prompts.build_answer_user(
                task, category, prompts.format_history(messages[:-1], limit=4), answer_results,
            ),
            max_tokens=1500,
            fallback_model=settings.groq_model_fallback,
            schema=prompts.ANSWER_SCHEMA,
        )
        validated = validate_answer_payload(payload, answer_results)
    except Exception as exc:
        return {
            "answer": prompts.ANSWER_UNAVAILABLE,
            "citations": [],
            "abstained": True,
            "issues": [*issues, f"Error al preparar la respuesta documental: {exc}"],
            "timings": _timing(state, "answer", started),
        }

    validation_failed = validated["abstained"] and bool(validated["issues"])
    return {
        "answer": prompts.ANSWER_UNAVAILABLE if validation_failed else validated["answer"],
        "citations": validated["citations"],
        "abstained": validated["abstained"],
        "issues": [*issues, *validated["issues"]],
        "timings": _timing(state, "answer", started),
    }


@_tracked_progress("verify")
def verify_node(state: AgentState) -> dict:
    started = time.perf_counter()
    answer = state.get("answer") or prompts.ABSTENTION
    citations = list(state.get("citations") or [])
    abstained = bool(state.get("abstained"))
    issues = list(state.get("issues") or [])
    category = state.get("category") or "general"

    if not citations and not state.get("needs_documents", True):
        return {
            "answer": answer,
            "citations": [],
            "abstained": False,
            "verified": False,
            "last_verified": None,
            "generated_report": None,
            "messages": [AIMessage(content=answer)],
            "timings": _timing(state, "verify", started),
        }

    if abstained or not citations or answer.strip() == prompts.ABSTENTION:
        final = answer if answer in {prompts.RETRIEVAL_UNAVAILABLE, prompts.ANSWER_UNAVAILABLE} else prompts.ABSTENTION
        return {
            "answer": final,
            "citations": [],
            "abstained": True,
            "verified": False,
            "last_verified": None,
            "generated_report": None,
            "messages": [AIMessage(content=final)],
            "timings": _timing(state, "verify", started),
        }

    query = _last_user_query(list(state.get("messages") or []))
    explicit_req = state.get("report_request")
    report = None
    source_question = query
    final_answer = answer
    if explicit_req:
        source_question = explicit_req["topic"] or (state.get("last_verified") or {}).get("question", "")
        try:
            report = create_report_record(
                chat_id=state.get("chat_id") or "",
                question=source_question,
                answer=answer,
                citations=citations,
                report_type=explicit_req["report_type"],
                verification_status="Verificado",
                abstained=False,
                category=category,
                session_id=state.get("session_id"),
            )
        except Exception as exc:
            logger.exception("No se pudo generar el informe solicitado")
            issues.append(f"Error al generar el archivo ({type(exc).__name__}).")
            final_answer = f"{answer}\n\n{prompts.REPORT_UNAVAILABLE}"

    return {
        "answer": final_answer,
        "verified": True,
        "abstained": False,
        "citations": citations,
        "issues": [*issues, "Citas documentales validadas."],
        "last_verified": {"question": source_question, "answer": answer, "citations": citations, "category": category},
        "generated_report": report,
        "messages": [AIMessage(content=final_answer)],
        "timings": _timing(state, "verify", started),
    }


def build_graph(
    checkpointer: Any,
    *,
    retrieve_fn: RetrieveFn = _default_retrieve,
):
    builder = StateGraph(AgentState)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("retrieve", lambda state: retrieve_node(state, retrieve_fn))
    builder.add_node("answer", answer_node)
    builder.add_node("verify", verify_node)

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        lambda state: "retrieve" if state.get("needs_documents", True) else "answer",
        {"retrieve": "retrieve", "answer": "answer"},
    )
    builder.add_edge("retrieve", "answer")
    builder.add_edge("answer", "verify")
    builder.add_edge("verify", END)
    return builder.compile(checkpointer=checkpointer)


def create_postgres_checkpointer() -> tuple[PostgresSaver, ConnectionPool]:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL no está configurada.")
    pool = ConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=5,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    return checkpointer, pool


def ask(graph: Any, question: str, chat_id: str, *, session_id: str | None = None) -> dict:
    config = {"configurable": {"thread_id": chat_id}}
    return graph.invoke(
        {
            "messages": [HumanMessage(content=question)],
            "chat_id": chat_id,
            "session_id": session_id,
            "category": "",
            "search_query": "",
            "filters": {},
            "needs_documents": True,
            "results": [],
            "retrieval_failed": False,
            "answer": "",
            "citations": [],
            "abstained": False,
            "verified": False,
            "generated_report": None,
            "report_request": None,
            "issues": [],
            "timings": {},
        },
        config=config,
        durability="exit",
    )
