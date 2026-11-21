from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request
from psycopg import Connection
from psycopg.rows import dict_row

from app.db.connection import connect

SESSION_COOKIE = "alpina_session_id"
_SESSION_TOKEN = re.compile(r"[A-Za-z0-9_.-]{8,64}")


def validate_uuid(value: str, label: str = "id") -> str:
    """Valida y normaliza un UUID como cadena canónica."""
    try:
        return str(uuid.UUID(str(value).strip()))
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail=f"{label} inválido.") from exc


def chat_uuid(chat_id: str) -> str:
    return validate_uuid(chat_id, "chat_id")


def report_uuid(report_id: str) -> str:
    return validate_uuid(report_id, "report_id")


def get_agent_graph(request: Request) -> Any:
    """Obtiene la instancia compilada del grafo del agente desde app.state."""
    graph = getattr(request.app.state, "graph", None)
    if graph is None:
        raise HTTPException(
            status_code=503,
            detail="El agente no está inicializado. Revisa /health.",
        )
    return graph


def derive_owner_id(session_token: str) -> str:
    """Deriva un identificador de propietario interno determinista a partir del secreto de sesión.

    Mantiene el secreto privado fuera del almacenamiento y de las respuestas JSON (R05).
    """
    digest = hashlib.sha256(f"alpina_owner_salt_v1:{session_token.strip()}".encode("utf-8")).hexdigest()[:32]
    return f"owner_{digest}"


def validated_session_token(token: str | None) -> str | None:
    candidate = (token or "").strip()
    return candidate if _SESSION_TOKEN.fullmatch(candidate) and candidate.lower() != "undefined" else None


def get_current_session_id(request: Request) -> str:
    """Obtiene el identificador de propietario interno para aislamiento y consultas en base de datos."""
    owner_id = getattr(request.state, "session_id", None)
    if not owner_id:
        raise HTTPException(status_code=401, detail="No se pudo establecer la sesión.")
    return owner_id


@dataclass(frozen=True)
class OwnedChat:
    id: str
    session_id: str

    def require(self, conn: Connection, *, lock: bool = False) -> dict:
        query = "select title from public.chats where id = %s and session_id = %s"
        if lock:
            query += " for update"
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, (self.id, self.session_id))
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Chat no encontrado.")
        return row


def get_owned_chat(
    chat_id: str = Depends(chat_uuid),
    session_id: str = Depends(get_current_session_id),
) -> OwnedChat:
    chat = OwnedChat(chat_id, session_id)
    with connect(session_id=session_id) as conn:
        chat.require(conn)
    return chat
