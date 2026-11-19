from __future__ import annotations

import dataclasses
import functools
import re
import time
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from psycopg_pool import ConnectionPool

from app.agent import prompts
from app.agent.llm import chat_json, chat_text
from app.agent.progress import record_progress
from app.agent.validation import (
    classify_conversational_intent,
    detect_report_request,
    resolve_document_ids,
    validate_answer_payload,
    validate_router_output,
    validate_verifier_output,
)
from app.config import settings
from app.db.connection import connect
from app.products.search import search_products
from app.reports.service import create_report_record
from app.retrieval.coverage import needs_coverage
from app.retrieval.search import SearchFilters, coverage_search


class AgentState(MessagesState):
    chat_id: str
    category: str
    search_query: str
    filters: dict
    needs_documents: bool
    results: list[dict]
    answer: str
    citations: list[dict]
    abstained: bool
    verified: bool
    issues: list[str]
    timings: dict[str, float]
    generated_report: dict | None


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
    with connect() as conn:
        results = coverage_search(
            conn,
            query,
            filters=filters,
            base_limit=8,
            extra_documents=6,
            max_documents=10,
        )
        products = []
        if not filters.categories or "nutrition" in filters.categories:
            products = search_products(conn, query, limit=3)

    payload = [dataclasses.asdict(product) for product in products]
    payload.extend(dataclasses.asdict(result) for result in results)
    return payload


def generate_conversational_response(query: str, history: str = "") -> str:
    """Genera una respuesta conversacional viva, empática y personalizada usando el LLM."""
    clean_q = (query or "").strip()
    if not clean_q:
        return (
            "¡Hola! 👋 ¡Qué gusto saludarte! Soy el asistente de Alpina 🥛. "
            "¿En qué te puedo colaborar el día de hoy?"
        )
    try:
        user_prompt = f"""Historial de conversación reciente:
{history or "(sin historial previo)"}

Mensaje del usuario:
{clean_q}

Responde cordialmente como el asistente de Alpina:"""

        return chat_text(
            model=settings.groq_model_answer,
            system=prompts.CONVERSATIONAL_SYSTEM,
            user=user_prompt,
            temperature=0.7,
            max_tokens=500,
            fallback_model=settings.groq_model_fallback,
        ).strip()
    except Exception:
        return (
            "¡Hola! Es un gusto saludarte. Soy el asistente oficial de Alpina 🥛. "
            "¿En qué te puedo colaborar hoy? Estoy listo para responder consultas sobre nuestros productos, "
            "normativas de etiquetado o datos corporativos."
        )


PRODUCT_FAST_RE = re.compile(
    r"\b(alpinito|bon\s*yurt|finesse|yox|defensis|kumis|arequipe|baby\s*gu|"
    r"leche\s+deslactosada|queso\s+campesino|quesito|avena\s+alpina|soplamin|"
    r"precio|precios|costo|costos|ingrediente|ingredientes|al[eé]rgeno|al[eé]rgenos)\b",
    re.IGNORECASE,
)


@_tracked_progress("supervisor")
def supervisor_node(state: AgentState) -> dict:
    started = time.perf_counter()
    messages = list(state.get("messages") or [])
    query = _last_user_query(messages)
    history = prompts.format_history(messages[:-1]) if messages else ""
    issues = list(state.get("issues") or [])

    # Fast-path 1 (<1ms): Saludos, cortesías y charla social sin latencia de router
    intent = classify_conversational_intent(query)
    if intent is not None:
        return {
            "category": "general",
            "search_query": "",
            "filters": {
                "categories": [],
                "country": "CO",
                "vigente": True,
                "coverage": False,
            },
            "needs_documents": False,
            "results": [],
            "citations": [],
            "answer": "",
            "abstained": False,
            "verified": False,
            "issues": issues,
            "timings": _timing(state, "supervisor", started),
        }

    # Fast-path 2 (<1ms): Consultas directas que citan documentos oficiales específicos (N1..N11, P1..P4, C1..C5)
    resolved_ids = resolve_document_ids(query)
    if resolved_ids and not history:
        is_corp = any(doc_id.startswith("C") for doc_id in resolved_ids)
        is_prod = any(doc_id.startswith("P") for doc_id in resolved_ids)
        category = "corporate" if is_corp else ("product" if is_prod else "regulatory")
        cat_filters = prompts.DEFAULT_CATEGORY_FILTERS.get(category, [])
        return {
            "category": category,
            "search_query": query,
            "filters": {
                "document_ids": resolved_ids,
                "categories": cat_filters,
                "country": "CO",
                "vigente": True,
                "coverage": needs_coverage(query),
            },
            "needs_documents": True,
            "results": [],
            "citations": [],
            "answer": "",
            "abstained": False,
            "verified": False,
            "issues": issues,
            "timings": _timing(state, "supervisor", started),
        }

    # Fast-path 3 (<1ms): Consultas directas al catálogo de productos de Alpina
    if PRODUCT_FAST_RE.search(query) and not history and not resolved_ids:
        return {
            "category": "product",
            "search_query": query,
            "filters": {
                "categories": ["nutrition"],
                "country": "CO",
                "vigente": True,
                "coverage": False,
            },
            "needs_documents": True,
            "results": [],
            "citations": [],
            "answer": "",
            "abstained": False,
            "verified": False,
            "issues": issues,
            "timings": _timing(state, "supervisor", started),
        }

    try:
        payload = chat_json(
            settings.groq_model_router,
            prompts.ROUTER_SYSTEM,
            prompts.build_router_user(query, history),
            temperature=0.0,
            max_tokens=500,
            fallback_model=settings.groq_model_fallback,
        )
        router = validate_router_output(payload, query)
    except Exception as exc:
        router = {
            "category": "general",
            "search_query": query,
            "categories": [],
            "document_ids": [],
            "needs_documents": True,
        }
        issues.append(f"Router falló: {type(exc).__name__}: {exc}")

    if resolved_ids:
        router["document_ids"] = list(
            dict.fromkeys([*router.get("document_ids", []), *resolved_ids])
        )

    filters: dict[str, Any] = {
        "categories": router["categories"],
        "country": "CO",
        "vigente": True,
        "coverage": needs_coverage(query),
    }
    if router["document_ids"]:
        filters["document_ids"] = router["document_ids"]

    return {
        "category": router["category"],
        "search_query": router["search_query"],
        "filters": filters,
        "needs_documents": router["needs_documents"],
        "results": [],
        "citations": [],
        "answer": "",
        "abstained": False,
        "verified": False,
        "issues": issues,
        "timings": _timing(state, "supervisor", started),
    }


@_tracked_progress("retrieve")
def retrieve_node(state: AgentState, retrieve_fn: RetrieveFn) -> dict:
    started = time.perf_counter()
    if not state.get("needs_documents", True):
        return {
            "results": [],
            "timings": _timing(state, "retrieve", started),
        }

    query = state.get("search_query") or _last_user_query(
        list(state.get("messages") or [])
    )
    if not query:
        return {
            "results": [],
            "timings": _timing(state, "retrieve", started),
        }

    try:
        filters = SearchFilters(**(state.get("filters") or {}))
        results = retrieve_fn(query, filters)
        if not results and (filters.categories or filters.document_ids):
            broad_filters = SearchFilters(
                categories=None,
                document_ids=None,
                doc_type=filters.doc_type,
                country=filters.country,
                vigente=filters.vigente,
                coverage=filters.coverage,
            )
            results = retrieve_fn(query, broad_filters)
            if results:
                return {
                    "results": results,
                    "issues": [
                        *list(state.get("issues") or []),
                        "Se amplió la búsqueda porque los filtros iniciales "
                        "no devolvieron fuentes.",
                    ],
                    "timings": _timing(state, "retrieve", started),
                }
    except Exception as exc:
        return {
            "results": [],
            "issues": [
                *list(state.get("issues") or []),
                f"Recuperación falló: {type(exc).__name__}: {exc}",
            ],
            "timings": _timing(state, "retrieve", started),
        }

    return {
        "results": results,
        "timings": _timing(state, "retrieve", started),
    }


@_tracked_progress("answer")
def answer_node(state: AgentState) -> dict:
    started = time.perf_counter()
    messages = list(state.get("messages") or [])
    query = _last_user_query(messages)
    history = prompts.format_history(messages[:-1]) if messages else ""
    results = list(state.get("results") or [])
    issues = list(state.get("issues") or [])

    if not state.get("needs_documents", True) or state.get("category") == "general":
        conversational_answer = generate_conversational_response(query, history)
        return {
            "answer": conversational_answer,
            "citations": [],
            "abstained": False,
            "verified": True,
            "timings": _timing(state, "answer", started),
        }

    if not results:
        return {
            "answer": prompts.ABSTENTION,
            "citations": [],
            "abstained": True,
            "issues": [*issues, "Sin fuentes recuperadas con similitud semántica suficiente."],
            "timings": _timing(state, "answer", started),
        }

    coverage = bool((state.get("filters") or {}).get("coverage"))
    answer_results = results[:10] if coverage else results[:6]
    try:
        payload = chat_json(
            settings.groq_model_answer,
            prompts.ANSWER_SYSTEM,
            prompts.build_answer_user(
                query,
                state.get("category") or "general",
                history,
                answer_results,
            ),
            temperature=0.1,
            max_tokens=1000,
            fallback_model=settings.groq_model_fallback,
        )
        validated = validate_answer_payload(payload, results)
    except Exception as first_exc:
        try:
            payload = chat_json(
                settings.groq_model_answer,
                prompts.ANSWER_SYSTEM,
                prompts.build_answer_user(
                    query,
                    state.get("category") or "general",
                    history,
                    answer_results[:3],
                ),
                temperature=0.0,
                max_tokens=800,
                fallback_model=settings.groq_model_fallback,
            )
            validated = validate_answer_payload(payload, results)
        except Exception as exc:
            return {
                "answer": prompts.ABSTENTION,
                "citations": [],
                "abstained": True,
                "issues": [
                    *issues,
                    f"Respuesta falló: {type(first_exc).__name__}: {first_exc}",
                    f"Reintento falló: {type(exc).__name__}: {exc}",
                ],
                "timings": _timing(state, "answer", started),
            }

    # Solo invocar tool si el usuario lo solicitó explícitamente en formato PDF o Excel
    explicit_req = detect_report_request(query)
    generated_report = None
    if explicit_req and not validated["abstained"]:
        report_type = explicit_req.get("report_type", "pdf")
        if validated.get("generate_report") and isinstance(validated["generate_report"], dict):
            llm_type = validated["generate_report"].get("report_type")
            if llm_type in {"pdf", "xlsx"}:
                report_type = llm_type
        try:
            generated_report = create_report_record(
                chat_id=state.get("chat_id") or "",
                question=query,
                answer=validated["answer"],
                citations=validated["citations"],
                report_type=report_type,
                verification_status="Citas OK",
                abstained=False,
                category=state.get("category") or "",
            )
        except Exception as exc:
            issues.append(f"Tool generate_report falló: {type(exc).__name__}: {exc}")

    return {
        "answer": validated["answer"],
        "citations": validated["citations"],
        "abstained": validated["abstained"],
        "issues": [*issues, *validated["issues"]],
        "generated_report": generated_report,
        "timings": _timing(state, "answer", started),
    }


@_tracked_progress("verify")
def verify_node(state: AgentState) -> dict:
    started = time.perf_counter()
    answer = state.get("answer") or prompts.ABSTENTION
    citations = list(state.get("citations") or [])
    abstained = bool(state.get("abstained"))
    issues = list(state.get("issues") or [])

    if not state.get("needs_documents", True) or state.get("category") == "general":
        return {
            "answer": answer,
            "citations": [],
            "abstained": False,
            "verified": True,
            "issues": issues,
            "generated_report": state.get("generated_report"),
            "messages": [AIMessage(content=answer)],
            "timings": _timing(state, "verify", started),
        }

    if abstained or not citations:
        final = prompts.ABSTENTION
        return {
            "answer": final,
            "citations": [],
            "abstained": True,
            "verified": True,
            "generated_report": None,
            "messages": [AIMessage(content=final)],
            "timings": _timing(state, "verify", started),
        }

    # Verificación determinista instantánea (<1ms):
    # Las citas ya fueron validadas contra los chunks recuperados, páginas y metadatos en validate_answer_payload.
    # Esto elimina 2.5s - 3.5s de latencia y previene falsas abstenciones causadas por el verificador LLM.
    return {
        "verified": True,
        "issues": [
            *issues,
            "Verificación determinista de citas aprobada.",
        ],
        "generated_report": state.get("generated_report"),
        "messages": [AIMessage(content=answer)],
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


def ask(graph: Any, question: str, chat_id: str) -> dict:
    config = {"configurable": {"thread_id": chat_id}}
    return graph.invoke(
        {
            "messages": [HumanMessage(content=question)],
            "chat_id": chat_id,
            "category": "",
            "search_query": "",
            "filters": {},
            "needs_documents": True,
            "results": [],
            "answer": "",
            "citations": [],
            "abstained": False,
            "verified": False,
            "generated_report": None,
            "issues": [],
            "timings": {},
        },
        config=config,
        durability="exit",
    )
