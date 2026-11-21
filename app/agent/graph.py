from __future__ import annotations

import dataclasses
import functools
import logging
import re
import time
from uuid import uuid4
from typing import Annotated, Any, Callable

logger = logging.getLogger(__name__)

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.channels import UntrackedValue
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from psycopg_pool import ConnectionPool

from app.agent import prompts
from app.agent.checkpoints import CheckpointPool, checkpoint_serializer, checkpoint_session, setup_checkpointer
from app.agent.llm import chat_json
from app.agent.progress import record_progress
from app.agent.report_tools import REPORT_TOOLS, handle_report_error
from app.agent.validation import (
    SCOPE_RESPONSE,
    classify_conversational_intent,
    detect_out_of_domain_or_jailbreak,
    detect_report_request,
    provided_report_content,
    validate_answer_payload,
    validate_router_output,
)
from app.config import settings
from app.db.connection import connect, verify_web_role
from app.documents.catalog import resolve_document_ids
from app.products.search import catalog_nutrition_answer, search_products
from app.reports.financial import financial_statement_answer
from app.retrieval.coverage import needs_coverage
from app.retrieval.search import SearchFilters, coverage_search


class AgentState(MessagesState):
    chat_id: str
    session_id: str | None
    category: str
    search_query: Annotated[str, UntrackedValue(str)]
    filters: dict
    needs_documents: bool
    results: Annotated[list[dict], UntrackedValue(list)]
    retrieval_failed: bool
    answer: Annotated[str, UntrackedValue(str)]
    citations: list[dict]
    abstained: bool
    verified: bool
    issues: list[str]
    timings: dict[str, float]
    generated_report: dict | None
    report_request: Annotated[dict | None, UntrackedValue(dict)]
    report_tool_messages: Annotated[list, UntrackedValue(list)]
    report_tool: str | None
    pending_report_type: str | None
    provided_report_content: dict[str, str] | str | None
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
            "provided_report_content": None,
            "last_verified": None,
            "issues": ["Solicitud fuera del alcance documental."],
            "timings": _timing(state, "supervisor", started),
        }

    report_request = detect_report_request(query)
    provided = report_request.get("content", "") if report_request else provided_report_content(query)
    previous = state.get("last_verified") or {}
    if report_request and not report_request["topic"] and report_request.get("detailed") and previous.get("question"):
        report_request = {**report_request, "topic": previous["question"]}
    if provided and not report_request and state.get("pending_report_type"):
        report_request = {"report_type": state["pending_report_type"], "topic": "", "content": provided}
    if report_request and not report_request["topic"] and not provided:
        saved_content = state.get("provided_report_content")
        provided = saved_content.get("text", "") if isinstance(saved_content, dict) else (saved_content or "")
    if provided:
        if report_request:
            report_request = {**report_request, "content": provided}
        return {
            "category": "general",
            "needs_documents": False,
            "answer": provided if report_request else prompts.REPORT_FORMAT_REQUEST,
            "report_request": report_request,
            "pending_report_type": None,
            "provided_report_content": {"text": provided},
            "last_verified": None,
            "timings": _timing(state, "supervisor", started),
        }
    if report_request and not report_request["topic"]:
        return {
            "category": previous.get("category") or "general",
            "needs_documents": False,
            "answer": previous.get("answer") or prompts.REPORT_TOPIC_REQUEST,
            "citations": previous.get("citations") or [],
            "report_request": report_request if previous.get("citations") else None,
            "pending_report_type": None if previous.get("citations") else report_request["report_type"],
            "timings": _timing(state, "supervisor", started),
        }

    intent = classify_conversational_intent(query)
    if intent is not None and not report_request:
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
    filters: dict[str, Any] = {"coverage": bool(report_request) or needs_coverage(subject)}
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
        except Exception:
            logger.warning("No se pudo clasificar la consulta con Groq", exc_info=True)
            router = validate_router_output({}, subject)
            issues.append("No se pudo clasificar la consulta con el modelo.")
        category = router["category"]
        if category == "out_of_scope":
            issues.append("Solicitud fuera del alcance documental.")
            return {
                "category": "guardrail",
                "needs_documents": False,
                "answer": SCOPE_RESPONSE,
                "pending_report_type": None,
                "provided_report_content": None,
                "last_verified": None,
                "issues": issues,
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
        "provided_report_content": None,
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
    limit = 12 if report else (6 if (state.get("filters") or {}).get("coverage") else 4)
    answer_results = results[:limit]
    task = subject
    if report:
        task = (
            f"Redacta el contenido completo para un informe sobre la solicitud: {subject}\n"
            f"El archivo se generará en {prompts.REPORT_FORMAT_LABELS[report['report_type']]}. "
            "Cubre cada aspecto que pidió el usuario y empieza con una síntesis. "
            "Desarrolla los hallazgos por tema, con detalle concreto, alcance, fechas y unidades. "
            "Presenta los datos comparables en tablas Markdown y explica su significado. "
            "Incluye conclusiones, recomendaciones o pasos cuando los soliciten y estén sustentados. "
            "Indica qué datos faltan para responder cualquier punto de la solicitud."
        )
    if {"N2", "N3"}.issubset((state.get("filters") or {}).get("document_ids") or []) and FRONT_LABEL_RE.search(subject):
        task += "\nDistingue el texto original de la Resolución 810 y los cambios de la Resolución 2492."
    try:
        direct_answer = None
        if category == "product":
            direct_answer = catalog_nutrition_answer(subject, answer_results)
        elif category == "corporate" and FINANCIAL_RESULTS_RE.search(subject):
            direct_answer = financial_statement_answer(subject, answer_results)

        payload = direct_answer
        if report or not payload:
            try:
                payload = chat_json(
                    settings.groq_model_answer,
                    prompts.ANSWER_SYSTEM,
                    prompts.build_answer_user(
                        task, category, prompts.format_history(messages[:-1], limit=4), answer_results,
                    ),
                    max_tokens=3800 if report else 1500,
                    fallback_model=settings.groq_model_fallback,
                    fallback_max_tokens=3000 if report else 750,
                    schema=prompts.ANSWER_SCHEMA,
                )
            except Exception:
                if not direct_answer:
                    raise
        validated = validate_answer_payload(payload, answer_results)
        if validated["abstained"] and direct_answer and payload is not direct_answer:
            validated = validate_answer_payload(direct_answer, answer_results)
    except Exception:
        logger.exception("No se pudo preparar la respuesta documental")
        return {
            "answer": prompts.ANSWER_UNAVAILABLE,
            "citations": [],
            "abstained": True,
            "issues": [*issues, "Error al preparar la respuesta documental."],
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
    explicit_req = state.get("report_request")
    user_provided = bool(explicit_req and explicit_req.get("content"))

    if not user_provided and not citations and not state.get("needs_documents", True):
        return {
            "answer": answer,
            "citations": [],
            "abstained": False,
            "verified": False,
            "generated_report": None,
            "messages": [AIMessage(content=answer)],
            "timings": _timing(state, "verify", started),
        }

    if abstained or (not user_provided and (not citations or answer.strip() == prompts.ABSTENTION)):
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
    source_question = (
        explicit_req["topic"] or (state.get("last_verified") or {}).get("question", "")
        if explicit_req else query
    )
    update = {
        "answer": answer,
        "verified": not user_provided,
        "abstained": False,
        "citations": citations,
        "issues": issues if user_provided else [*issues, "Citas documentales validadas."],
        "last_verified": (
            None if user_provided else
            {"question": source_question, "answer": answer, "citations": citations, "category": category}
        ),
        "timings": _timing(state, "verify", started),
    }
    if explicit_req and (tool := REPORT_TOOLS.get(explicit_req["report_type"])):
        update["report_tool_messages"] = [
            AIMessage(content="", tool_calls=[{"name": tool.name, "args": {}, "id": str(uuid4())}])
        ]
    else:
        update["messages"] = [AIMessage(content=answer)]
    return update


def finish_report_node(state: AgentState) -> dict:
    messages = state.get("report_tool_messages") or []
    result = messages[-1] if messages and isinstance(messages[-1], ToolMessage) else None
    report = result.artifact if result and result.status == "success" else None
    answer = state["answer"]
    issues = list(state.get("issues") or [])
    if not report:
        answer = f"{answer}\n\n{prompts.REPORT_UNAVAILABLE}"
        issues.append("La herramienta de informes no pudo guardar el archivo.")
    record_progress(state.get("chat_id", ""), "report", "done" if report else "error")
    return {
        "answer": answer,
        "messages": [AIMessage(content=answer)],
        "issues": issues,
        "generated_report": report,
        "report_tool": result.name if result else None,
        "report_tool_messages": [],
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
    builder.add_node(
        "report",
        ToolNode(list(REPORT_TOOLS.values()), messages_key="report_tool_messages", handle_tool_errors=handle_report_error),
    )
    builder.add_node("finish_report", finish_report_node)

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        lambda state: "retrieve" if state.get("needs_documents", True) else "answer",
        {"retrieve": "retrieve", "answer": "answer"},
    )
    builder.add_edge("retrieve", "answer")
    builder.add_edge("answer", "verify")
    builder.add_conditional_edges("verify", lambda state: "report" if state.get("report_tool_messages") else END)
    builder.add_edge("report", "finish_report")
    builder.add_edge("finish_report", END)
    return builder.compile(checkpointer=checkpointer)


def create_postgres_checkpointer() -> tuple[PostgresSaver, ConnectionPool]:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL no está configurada.")
    pool = CheckpointPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=5,
        kwargs={"autocommit": True, "prepare_threshold": None},
        open=False,
    )
    try:
        pool.open(wait=True, timeout=20)
        with pool.connection() as conn:
            verify_web_role(conn)
        checkpointer = PostgresSaver(pool, serde=checkpoint_serializer())
        setup_checkpointer(checkpointer, pool)
    except Exception:
        pool.close()
        raise
    return checkpointer, pool


def ask(graph: Any, question: str, chat_id: str, *, session_id: str | None = None) -> dict:
    config = {"configurable": {"thread_id": chat_id}}
    state = {
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
        "report_tool_messages": [],
        "report_tool": None,
        "issues": [],
        "timings": {},
    }
    with checkpoint_session(session_id):
        return graph.invoke(state, config=config, durability="exit")
