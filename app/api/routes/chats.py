from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.agent.checkpoints import delete_chat_checkpoints
from app.agent.graph import ask
from app.agent.progress import clear_progress, get_progress
from app.agent.prompts import ABSTENTION
from app.agent.trace import build_retrieval_items, summarize_retrieval
from app.api.deps import (
    OwnedChat,
    get_agent_graph,
    get_current_session_id,
    get_owned_chat,
)
from app.api.schemas.chats import ChatCreate, MessageCreate
from app.config import settings
from app.core.crypto import decrypt_text, encrypt_text
from app.core.markdown import render_markdown, unwrap_markdown
from app.db.connection import connect
from app.reports.service import remove_report_files

router = APIRouter(prefix="/api/chats", tags=["chats"])
logger = logging.getLogger(__name__)


def _json_safe(val: Any) -> Any:
    """Convierte recursivamente tipos no soportados por json.dumps a formatos serializables."""
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, dict):
        return {str(k): _json_safe(v) for k, v in val.items()}
    if isinstance(val, (list, tuple, set)):
        return [_json_safe(v) for v in val]
    return val


@router.get("")
def list_chats(session_id: str = Depends(get_current_session_id)) -> list[dict]:
    """Lista las conversaciones activas de la sesión actual ordenadas por actualización reciente."""
    with connect(session_id=session_id) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                select id::text as id, title, created_at, updated_at
                from public.chats
                where session_id = %s
                order by updated_at desc
                """,
                (session_id,),
            )
            rows = list(cur.fetchall())
            for row in rows:
                if row.get("title"):
                    row["title"] = decrypt_text(row["title"])
            return rows


@router.post("")
def create_chat(
    payload: ChatCreate | None = None,
    session_id: str = Depends(get_current_session_id),
) -> dict:
    """Crea una nueva conversación vinculada a la sesión actual."""
    target_user = session_id
    plain_title = (payload.title if payload and payload.title else "Nuevo chat").strip()
    plain_title = " ".join(plain_title.split())[:120] or "Nuevo chat"
    enc_title = encrypt_text(plain_title)

    with connect(session_id=session_id) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                insert into public.chats (title, user_id, session_id)
                values (%s, %s, %s)
                returning id::text as id, title, created_at, updated_at
                """,
                (enc_title, target_user, session_id),
            )
            row = cur.fetchone()
            if row:
                row["title"] = plain_title
            return row


@router.get("/{chat_id}/progress")
def chat_progress(chat: OwnedChat = Depends(get_owned_chat)) -> dict:
    """Consulta el nodo activo y progreso en streaming del agente para un chat."""
    return get_progress(chat.id) or {"node": None, "status": "idle"}


@router.get("/{chat_id}/messages")
def list_messages(chat: OwnedChat = Depends(get_owned_chat)) -> list[dict]:
    """Obtiene el historial cronológico de mensajes descifrados de un chat."""
    with connect(session_id=chat.session_id) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                select id::text as id, role, content, citations, model,
                       metadata, created_at
                from public.messages
                where chat_id = %s
                order by created_at asc, case when role = 'user' then 0 else 1 end, id asc
                """,
                (chat.id,),
            )
            messages = list(cur.fetchall())
    for msg in messages:
        msg["content"] = decrypt_text(msg.get("content"))
        text = unwrap_markdown(msg["content"]) if msg["role"] == "assistant" else msg["content"]
        msg["content_html"] = render_markdown(text)
        if isinstance(msg.get("metadata"), dict):
            msg["metadata"].pop("report_question", None)
    return messages


@router.post("/{chat_id}/messages")
def send_message(
    payload: MessageCreate,
    request: Request,
    chat: OwnedChat = Depends(get_owned_chat),
) -> dict:
    """Envía un mensaje al agente RAG, ejecuta el grafo y guarda la respuesta cifrada en reposo."""
    chat_id_clean = chat.id
    session_id = chat.session_id
    content = payload.content.strip(" \r\n")
    if not content.strip():
        raise HTTPException(status_code=422, detail="El mensaje está vacío.")

    graph = get_agent_graph(request)

    enc_user_content = encrypt_text(content)
    clear_progress(chat_id_clean)
    try:
        result = ask(graph, content, chat_id_clean, session_id=session_id)
    except Exception as exc:
        logger.exception("Fallo al procesar el mensaje con el agente para el chat %s", chat_id_clean)
        raise HTTPException(
            status_code=500,
            detail="Error al procesar la consulta con el agente. Por favor intente nuevamente.",
        ) from exc

    citations = result.get("citations") or []
    issues = result.get("issues") or []
    retrieved = result.get("results") or []
    retrieval_items = build_retrieval_items(retrieved, citations)
    retrieval_summary = summarize_retrieval(retrieval_items)
    product_count = retrieval_summary["product_count"]
    retrieved_chunks = retrieval_summary["retrieved_chunks"]
    unique_documents = retrieval_summary["unique_documents"]
    abstained = bool(result.get("abstained"))
    verified = bool(result.get("verified"))
    category = result.get("category")
    report_request = result.get("report_request") or {}
    report_user_provided = bool(report_request.get("content")) and not abstained
    verification_mode = "citas" if verified else None
    graph_trace = [
        {
            "node": "supervisor",
            "status": "ok",
            "detail": f"Categoría: {category or 'general'}",
        },
        {
            "node": "retrieve",
            "status": "ok" if retrieved else "warn",
            "detail": (
                f"{retrieved_chunks} fragmentos de {unique_documents} documentos "
                f"y {product_count} productos"
                if retrieved
                else ("Datos del usuario" if report_user_provided else "Sin fuentes recuperadas")
            ),
        },
        {
            "node": "answer",
            "status": "ok" if not abstained else "warn",
            "detail": f"{len(citations)} citas",
        },
        {
            "node": "verify",
            "status": "warn" if abstained else ("ok" if verified else "warn"),
            "detail": (
                "Abstención"
                if abstained
                else (
                    "Citas validadas"
                    if verification_mode == "citas"
                    else ("Verificado" if verified else "Sin verificar")
                )
            ),
        },
    ]
    if tool_name := result.get("report_tool"):
        graph_trace.append({
            "node": "report",
            "status": "ok" if result.get("generated_report") else "warn",
            "detail": tool_name,
        })
    timings = result.get("timings") or {}
    for step in graph_trace:
        duration = timings.get(step["node"])
        if duration is not None:
            step["detail"] = f"{step['detail']} · {duration:.1f} s"

    metadata = {
        "abstained": abstained,
        "verified": verified,
        "verification_mode": verification_mode,
        "issues": issues,
        "category": category,
        "graph_trace": graph_trace,
        "timings": timings,
        "retrieved_count": len(retrieved),
        "retrieved_chunks": retrieved_chunks,
        "document_count": unique_documents,
        "unique_documents": unique_documents,
        "product_count": product_count,
        "citation_count": len(citations),
        "generated_report": result.get("generated_report"),
        "report_user_provided": report_user_provided,
    }
    report_question = (result.get("last_verified") or {}).get("question")
    stored_metadata = dict(metadata)
    if verified and report_question:
        stored_metadata["report_question"] = encrypt_text(report_question)

    answer_text = result.get("answer") or ABSTENTION
    enc_assistant_content = encrypt_text(answer_text)
    user_html = render_markdown(content)
    answer_html = render_markdown(unwrap_markdown(answer_text))

    with connect(session_id=session_id) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            try:
                chat_row = chat.require(conn, lock=True)
            except HTTPException:
                clear_progress(chat_id_clean)
                raise
            cur.execute(
                """
                insert into public.messages (chat_id, role, content, metadata)
                values (%s, 'user', %s, %s)
                returning id::text as id, created_at
                """,
                (chat_id_clean, enc_user_content, Jsonb({"source": "web"})),
            )
            user_message = {**cur.fetchone(), "content": content, "content_html": user_html}
            cur.execute(
                """
                insert into public.messages
                    (chat_id, role, content, citations, model,
                     token_usage, metadata)
                values (%s, 'assistant', %s, %s, %s, %s, %s)
                returning id::text as id, created_at
                """,
                (
                    chat_id_clean,
                    enc_assistant_content,
                    Jsonb(_json_safe(citations)),
                    settings.groq_model_answer,
                    Jsonb({}),
                    Jsonb(_json_safe(stored_metadata)),
                ),
            )
            assistant_message = {**cur.fetchone(), "content": answer_text, "content_html": answer_html}
            title = chat_row["title"]
            if not title or decrypt_text(title) == "Nuevo chat":
                title = encrypt_text(" ".join(content.split())[:60])
            cur.execute(
                "update public.chats set title = %s, updated_at = now() where id = %s",
                (title, chat_id_clean),
            )

    return {
        "chat_id": chat_id_clean,
        "user_message": user_message,
        "assistant_message": assistant_message,
        "answer": answer_text,
        "citations": citations,
        "abstained": abstained,
        "verified": verified,
        "issues": issues,
        "category": category,
        "search_query": result.get("search_query"),
        "generated_report": result.get("generated_report"),
        "metadata": metadata,
    }


@router.delete("/{chat_id}", status_code=204)
def delete_chat(chat: OwnedChat = Depends(get_owned_chat)) -> Response:
    """Elimina una conversación específica perteneciente a la sesión activa."""
    with connect(session_id=chat.session_id) as conn, conn.cursor(row_factory=dict_row) as cur:
        chat.require(conn, lock=True)
        cur.execute(
            "delete from public.reports where chat_id = %s returning id::text, report_type, storage_key",
            (chat.id,),
        )
        reports = cur.fetchall()
        delete_chat_checkpoints(conn, chat.id)
        cur.execute("delete from public.chats where id = %s and session_id = %s", (chat.id, chat.session_id))

    clear_progress(chat.id)
    for report in reports:
        remove_report_files(report["id"], report["report_type"], report["storage_key"])
    return Response(status_code=204)
