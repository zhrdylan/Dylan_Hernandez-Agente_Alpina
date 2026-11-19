from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.agent.graph import ask
from app.agent.progress import clear_progress, get_progress
from app.agent.prompts import ABSTENTION
from app.agent.trace import build_retrieval_items, summarize_retrieval
from app.api.deps import (
    chat_uuid as validate_chat_uuid,
    get_agent_graph,
    get_checkpointer,
    get_current_session_id,
    get_current_user_id,
)
from app.api.schemas.chats import ChatCreate, MessageCreate
from app.config import settings
from app.core.crypto import decrypt_text, encrypt_text
from app.db.connection import connect

router = APIRouter(prefix="/api/chats", tags=["chats"])


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
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                select id::text as id, title, user_id, session_id, created_at, updated_at
                from public.chats
                where session_id = %s or user_id = %s
                order by updated_at desc
                """,
                (session_id, session_id),
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
    target_user = (payload.user_id if payload and payload.user_id else None) or session_id
    plain_title = (payload.title if payload and payload.title else "Nuevo chat").strip()
    plain_title = " ".join(plain_title.split())[:120] or "Nuevo chat"
    enc_title = encrypt_text(plain_title)

    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                insert into public.chats (title, user_id, session_id)
                values (%s, %s, %s)
                returning id::text as id, title, user_id, session_id, created_at, updated_at
                """,
                (enc_title, target_user, session_id),
            )
            row = cur.fetchone()
            if row:
                row["title"] = plain_title
            return row


@router.get("/{chat_id}/progress")
def chat_progress(
    chat_id: str,
    session_id: str = Depends(get_current_session_id),
) -> dict:
    """Consulta el nodo activo y progreso en streaming del agente para un chat."""
    chat_id_clean = validate_chat_uuid(chat_id)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select 1 from public.chats where id = %s and (session_id = %s or user_id = %s)",
                (chat_id_clean, session_id, session_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Chat no encontrado.")
    return get_progress(chat_id_clean) or {"node": None, "status": "idle"}


@router.get("/{chat_id}/messages")
def list_messages(
    chat_id: str,
    session_id: str = Depends(get_current_session_id),
) -> list[dict]:
    """Obtiene el historial cronológico de mensajes descifrados de un chat."""
    chat_id_clean = validate_chat_uuid(chat_id)
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select id from public.chats where id = %s and (session_id = %s or user_id = %s)",
                (chat_id_clean, session_id, session_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Chat no encontrado.")

            cur.execute(
                """
                select id::text as id, role, content, citations, model,
                       metadata, created_at
                from public.messages
                where chat_id = %s
                order by created_at asc, id asc
                """,
                (chat_id_clean,),
            )
            messages = list(cur.fetchall())
            for msg in messages:
                if msg.get("content"):
                    msg["content"] = decrypt_text(msg["content"])
            return messages


@router.post("/{chat_id}/messages")
def send_message(
    chat_id: str,
    payload: MessageCreate,
    request: Request,
    session_id: str = Depends(get_current_session_id),
) -> dict:
    """Envía un mensaje al agente RAG, ejecuta el grafo y guarda la respuesta cifrada en reposo."""
    chat_id_clean = validate_chat_uuid(chat_id)
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="El mensaje está vacío.")

    graph = get_agent_graph(request)

    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select id, title from public.chats where id = %s and (session_id = %s or user_id = %s)",
                (chat_id_clean, session_id, session_id),
            )
            chat = cur.fetchone()
            if not chat:
                raise HTTPException(status_code=404, detail="Chat no encontrado.")

            enc_user_content = encrypt_text(content)
            cur.execute(
                """
                insert into public.messages (chat_id, role, content, metadata)
                values (%s, 'user', %s, %s)
                returning id::text as id, created_at
                """,
                (chat_id_clean, enc_user_content, Jsonb({"source": "web"})),
            )
            user_message = cur.fetchone()
            if user_message:
                user_message["content"] = content

            raw_title = chat.get("title")
            current_title = decrypt_text(raw_title) if raw_title else ""
            if not current_title or current_title == "Nuevo chat":
                current_title = " ".join(content.split())[:60]
                enc_title = encrypt_text(current_title)
                cur.execute(
                    "update public.chats set title = %s, updated_at = now() where id = %s",
                    (enc_title, chat_id_clean),
                )

    clear_progress(chat_id_clean)
    try:
        result = ask(graph, content, chat_id_clean)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"El agente falló: {type(exc).__name__}: {exc}",
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
    verification_mode = (
        "citas"
        if any(
            "Verificador no disponible" in str(issue)
            or "Verificación determinista de citas" in str(issue)
            for issue in issues
        )
        else "llm"
    )
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
                else "Sin fuentes recuperadas"
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
        "search_query": result.get("search_query"),
        "graph_trace": graph_trace,
        "timings": timings,
        "retrieved_items": retrieval_items,
        "retrieved_count": len(retrieved),
        "retrieved_chunks": retrieved_chunks,
        "document_count": unique_documents,
        "unique_documents": unique_documents,
        "product_count": product_count,
        "citation_count": len(citations),
        "generated_report": result.get("generated_report"),
    }

    answer_text = result.get("answer") or ABSTENTION
    enc_assistant_content = encrypt_text(answer_text)

    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
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
                    Jsonb(_json_safe(metadata)),
                ),
            )
            assistant_message = cur.fetchone()
            if assistant_message:
                assistant_message["content"] = answer_text
            cur.execute(
                "update public.chats set updated_at = now() where id = %s",
                (chat_id_clean,),
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


@router.delete("", status_code=204)
def delete_all_chats(
    request: Request,
    session_id: str = Depends(get_current_session_id),
) -> Response:
    """Elimina todas las conversaciones de la sesión activa y vacía sus hilos en el checkpointer."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select id::text as id from public.chats where session_id = %s or user_id = %s",
                (session_id, session_id),
            )
            chat_ids = [row["id"] for row in cur.fetchall()]
            if chat_ids:
                cur.execute(
                    "delete from public.messages where chat_id = any(%s::uuid[])",
                    (chat_ids,),
                )
                cur.execute(
                    "delete from public.chats where id = any(%s::uuid[])",
                    (chat_ids,),
                )

    checkpointer = get_checkpointer(request)
    if checkpointer is not None and hasattr(checkpointer, "delete_thread"):
        for chat_id in chat_ids:
            try:
                checkpointer.delete_thread(chat_id)
            except Exception:
                continue
    return Response(status_code=204)


@router.delete("/{chat_id}", status_code=204)
def delete_chat(
    chat_id: str,
    request: Request,
    session_id: str = Depends(get_current_session_id),
) -> Response:
    """Elimina una conversación específica perteneciente a la sesión activa."""
    chat_id_clean = validate_chat_uuid(chat_id)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                delete from public.messages 
                where chat_id = %s and exists (
                    select 1 from public.chats 
                    where id = %s and (session_id = %s or user_id = %s)
                )
                """,
                (chat_id_clean, chat_id_clean, session_id, session_id),
            )
            cur.execute(
                "delete from public.chats where id = %s and (session_id = %s or user_id = %s)",
                (chat_id_clean, session_id, session_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Chat no encontrado.")

    checkpointer = get_checkpointer(request)
    if checkpointer is not None and hasattr(checkpointer, "delete_thread"):
        try:
            checkpointer.delete_thread(chat_id_clean)
        except Exception:
            pass

    return Response(status_code=204)
