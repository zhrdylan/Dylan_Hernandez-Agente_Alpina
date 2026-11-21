from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.agent.graph import build_graph, create_postgres_checkpointer
from app.api.router import api_router
from app.api.schemas.chats import ChatCreate, MessageCreate
from app.api.schemas.reports import ReportRequest
from app.config import BASE_DIR, ensure_project_dirs, settings
from app.core.security import api_docs_csp, setup_security_middlewares
from app.db.connection import close_pool, warm_pool
from app.db.migrate import check_database_ready

ensure_project_dirs()

STATIC_DIR = BASE_DIR / "app" / "static"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.graph = None
    app.state.startup_error = None
    app.state.ready = False
    pool = None
    try:
        ready, _ = check_database_ready()
        if not ready:
            app.state.startup_error = "Database schema not ready or pending migrations."
            app.state.ready = False
        else:
            checkpointer, pool = create_postgres_checkpointer()
            warm_pool()
            app.state.graph = build_graph(checkpointer)
            app.state.ready = True
    except Exception as exc:
        logger.exception("No se pudo iniciar el servicio")
        app.state.startup_error = type(exc).__name__
        app.state.ready = False
    try:
        yield
    finally:
        if pool is not None:
            pool.close()
        close_pool()


app = FastAPI(
    title="Agente Alpina",
    description="Respuestas trazables sobre documentos oficiales de Alpina.",
    version="0.2.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

setup_security_middlewares(app, allow_all_origins=settings.cors_allow_all)

app.include_router(api_router)


@app.get("/docs", include_in_schema=False)
def swagger_ui(request: Request) -> HTMLResponse:
    prefix = request.scope.get("root_path", "").rstrip("/")
    return api_docs_csp(get_swagger_ui_html(
        openapi_url=prefix + app.openapi_url,
        title=f"{app.title} - Swagger UI",
        oauth2_redirect_url=prefix + app.swagger_ui_oauth2_redirect_url,
        swagger_favicon_url=prefix + "/static/brand/favicon.png",
    ))


@app.get("/docs/oauth2-redirect", include_in_schema=False)
def swagger_oauth2_redirect() -> HTMLResponse:
    return api_docs_csp(get_swagger_ui_oauth2_redirect_html())


@app.get("/redoc", include_in_schema=False)
def redoc(request: Request) -> HTMLResponse:
    prefix = request.scope.get("root_path", "").rstrip("/")
    return api_docs_csp(get_redoc_html(
        openapi_url=prefix + app.openapi_url,
        title=f"{app.title} - ReDoc",
        redoc_favicon_url=prefix + "/static/brand/favicon.png",
        with_google_fonts=False,
    ))


@app.get("/")
def index() -> FileResponse:
    """Página principal de la interfaz de usuario web."""
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

__all__ = ["app", "ChatCreate", "MessageCreate", "ReportRequest"]
