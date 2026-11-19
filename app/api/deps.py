from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Any
from fastapi import HTTPException, Request


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
    if not session_token:
        return ""
    clean = session_token.strip()
    if clean.startswith("owner-") or clean.startswith("owner_"):
        return clean
    digest = hashlib.sha256(f"alpina_owner_salt_v1:{clean}".encode("utf-8")).hexdigest()[:32]
    return f"owner_{digest}"


def get_current_session_token(request: Request) -> str:
    """Extrae o genera el secreto de sesión privado emitido por el servidor."""
    token = getattr(request.state, "session_token", None)
    if token:
        return token

    cookie_sess = request.cookies.get("alpina_session_id")
    header_sess = request.headers.get("x-session-id")
    raw = cookie_sess or header_sess
    if raw and raw.strip().lower() not in {"default", "null", "undefined"}:
        clean = "".join(c for c in raw.strip() if c.isalnum() or c in "-_.")[:64]
        if len(clean) >= 8:
            request.state.session_token = clean
            return clean

    new_token = f"sess-{secrets.token_urlsafe(24)}"
    request.state.session_token = new_token
    return new_token


def get_current_session_id(request: Request) -> str:
    """Obtiene el identificador de propietario interno para aislamiento y consultas en base de datos."""
    owner_id = getattr(request.state, "session_id", None)
    if owner_id:
        return owner_id
    token = get_current_session_token(request)
    owner = derive_owner_id(token)
    request.state.session_id = owner
    return owner


def get_current_user_id(request: Request) -> str:
    """Extrae y normaliza el identificador de usuario o sesión para compatibilidad retroactiva."""
    return get_current_session_id(request)


def get_checkpointer(request: Request) -> Any:
    """Obtiene el checkpointer de LangGraph si está disponible."""
    return getattr(request.app.state, "checkpointer", None)
