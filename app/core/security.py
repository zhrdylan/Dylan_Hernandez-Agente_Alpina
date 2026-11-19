from __future__ import annotations

from typing import Callable
import secrets
import uuid
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.deps import derive_owner_id


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Agrega cabeceras HTTP de seguridad recomendadas a todas las respuestas."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response


class AnonymousSessionMiddleware(BaseHTTPMiddleware):
    """Garantiza que toda solicitud HTTP tenga una sesión anónima aislada y segura en cookie HttpOnly."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        cookie_session = request.cookies.get("alpina_session_id")
        header_session = request.headers.get("x-session-id")
        # El navegador web no envía x-session-id (R05). Si se recibe x-session-id (pruebas multi-perfil o API),
        # tiene precedencia para permitir aislamiento entre peticiones del mismo cliente HTTP.
        raw_session = header_session or cookie_session
        is_new = False

        clean = ""
        if raw_session and raw_session.strip().lower() not in {"default", "null", "undefined"}:
            sanitized = "".join(c for c in raw_session.strip() if c.isalnum() or c in "-_.")[:64]
            if len(sanitized) >= 8:
                clean = sanitized

        if not clean:
            clean = f"sess-{secrets.token_urlsafe(24)}"
            is_new = True

        request.state.session_token = clean
        request.state.session_id = derive_owner_id(clean)

        response = await call_next(request)

        # Establecer cookie segura HttpOnly si es nueva sesión o si no tenía la cookie configurada
        if is_new or not cookie_session:
            secure = request.url.scheme == "https"
            response.set_cookie(
                key="alpina_session_id",
                value=clean,
                httponly=True,
                samesite="lax",
                secure=secure,
                max_age=86400 * 30,  # 30 días
                path="/",
            )
            # R05: Mantener el secreto solo en la cookie privada; no exponerlo en cabeceras de respuesta

        return response


def setup_security_middlewares(app: FastAPI, *, allow_all_origins: bool = True) -> None:
    """Configura cabeceras seguras, aislamiento de sesión anónima y CORS para la aplicación."""
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(AnonymousSessionMiddleware)

    origins = ["*"] if allow_all_origins else [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True if not allow_all_origins else False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS", "HEAD"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "X-Session-Id"],
    )
