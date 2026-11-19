from __future__ import annotations

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


def get_current_session_id(request: Request) -> str:
    """Extrae el identificador de sesión anónima validado del estado de la petición o cabecera/cookie."""
    session_id = getattr(request.state, "session_id", None)
    if session_id:
        return session_id

    # Fallback si no fue procesado por middleware (ej. llamadas internas o tests directos)
    raw = request.headers.get("x-session-id") or request.cookies.get("alpina_session_id")
    if raw and raw.strip().lower() not in {"default", "null", "undefined"}:
        clean = "".join(c for c in raw.strip() if c.isalnum() or c in "-_.")[:64]
        if len(clean) >= 8:
            request.state.session_id = clean
            return clean

    new_sess = f"sess-{uuid.uuid4().hex}"
    request.state.session_id = new_sess
    return new_sess


def get_current_user_id(request: Request) -> str:
    """Extrae y normaliza el identificador de usuario o sesión para compatibilidad retroactiva."""
    return get_current_session_id(request)


def get_checkpointer(request: Request) -> Any:
    """Obtiene el checkpointer de LangGraph si está disponible."""
    return getattr(request.app.state, "checkpointer", None)
