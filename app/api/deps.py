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
    """Extrae, valida y sanitiza el identificador de sesión anónima (X-Session-Id o alpina_session_id)."""
    session_id = (
        request.headers.get("x-session-id")
        or request.cookies.get("alpina_session_id")
        or request.headers.get("x-user-id")
        or request.cookies.get("alpina_user_id")
        or request.cookies.get("alpina_device_id")
        or request.query_params.get("session_id")
        or request.query_params.get("user_id")
    )
    clean = str(session_id or "default").strip()
    clean = "".join(c for c in clean if c.isalnum() or c in "-_.")[:64]
    return clean or "default"


def get_current_user_id(request: Request) -> str:
    """Extrae y normaliza el identificador de usuario o sesión para compatibilidad retroactiva."""
    return get_current_session_id(request)


def get_checkpointer(request: Request) -> Any:
    """Obtiene el checkpointer de LangGraph si está disponible."""
    return getattr(request.app.state, "checkpointer", None)
