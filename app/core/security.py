from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from math import ceil

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from limits import parse
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import HTMLResponse, JSONResponse
from starlette.types import ASGIApp

from app.api.deps import SESSION_COOKIE, derive_owner_id, validated_session_token
from app.config import Settings, settings

_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; "
    "img-src 'self' https:; font-src 'self'; connect-src 'self'; frame-src 'self'; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'"
)


def api_docs_csp(response: HTMLResponse) -> HTMLResponse:
    """Autoriza los scripts de inicialización y recursos de la documentación de FastAPI."""
    hashes = [
        " 'sha256-" + base64.b64encode(hashlib.sha256(script).digest()).decode("ascii") + "'"
        for script in re.findall(rb"<script>(.*?)</script>", response.body, re.DOTALL)
    ]
    response.headers["Content-Security-Policy"] = _CONTENT_SECURITY_POLICY.replace(
        "script-src 'self'", "script-src 'self' https://cdn.jsdelivr.net" + "".join(hashes),
    ).replace(
        "style-src 'self'", "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    ).replace("img-src 'self' https:", "img-src 'self' https: data:")
    return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Agrega cabeceras HTTP de seguridad recomendadas a todas las respuestas."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            _CONTENT_SECURITY_POLICY,
        )
        path = request.url.path
        if path.startswith(("/api/chats", "/api/reports")):
            response.headers["Cache-Control"] = "private, no-store"
        elif path == "/" or path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response


class AnonymousSessionMiddleware(BaseHTTPMiddleware):
    """Garantiza que toda solicitud HTTP tenga una sesión anónima aislada y segura en cookie HttpOnly."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        cookie_session = validated_session_token(request.cookies.get(SESSION_COOKIE))
        api_token = validated_session_token(request.headers.get("x-session-id"))
        token = api_token or cookie_session or f"sess-{secrets.token_urlsafe(24)}"
        request.state.session_id = derive_owner_id(token)

        response = await call_next(request)

        if not api_token and not cookie_session:
            response.set_cookie(
                key=SESSION_COOKIE,
                value=token,
                httponly=True,
                samesite="lax",
                secure=settings.is_production or request.url.scheme == "https",
                max_age=86400 * 30,  # 30 días
                path="/",
            )

        return response


class ApiRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, config: Settings) -> None:
        super().__init__(app)
        self.limiter = Limiter(key_func=get_remote_address, storage_uri=config.rate_limit_storage_uri).limiter
        self.ip_limit = parse(config.rate_limit_ip)
        self.session_limit = parse(config.rate_limit_session)

    def _retry_after(self, request: Request) -> int | None:
        keys = (
            (self.ip_limit, "ip", get_remote_address(request)),
            (self.session_limit, "session", request.state.session_id),
        )
        for limit, scope, key in keys:
            if not self.limiter.hit(limit, "alpina", scope, key):
                window = self.limiter.get_window_stats(limit, "alpina", scope, key)
                return max(1, ceil(window.reset_time - time.time()))
        return None

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method != "OPTIONS" and request.url.path.startswith("/api/"):
            retry = await run_in_threadpool(self._retry_after, request)
            if retry is not None:
                return JSONResponse(
                    {"detail": "Se alcanzó el límite de solicitudes. Vuelve a intentarlo en unos instantes."},
                    status_code=429,
                    headers={"Retry-After": str(retry), "Cache-Control": "no-store"},
                )
        return await call_next(request)


def setup_security_middlewares(app: FastAPI, *, allow_all_origins: bool = False) -> None:
    """Configura cabeceras seguras, aislamiento de sesión anónima y CORS para la aplicación."""
    app.add_middleware(ApiRateLimitMiddleware, config=settings)
    app.add_middleware(AnonymousSessionMiddleware)

    origins = ["*"] if allow_all_origins else settings.cors_allowed_origins

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=not allow_all_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS", "HEAD"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "Retry-After", "X-Highlight-Status"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts, www_redirect=False)
    app.add_middleware(SecurityHeadersMiddleware)
