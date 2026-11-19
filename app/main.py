from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agent.graph import build_graph, create_postgres_checkpointer
from app.api.router import api_router
from app.api.schemas.chats import ChatCreate, MessageCreate
from app.api.schemas.reports import ReportRequest
from app.config import BASE_DIR, ensure_project_dirs, settings
from app.core.security import setup_security_middlewares
from app.db.connection import close_pool, warm_pool
from app.db.migrate import check_database_ready

ensure_project_dirs()

STATIC_DIR = BASE_DIR / "app" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.checkpointer = None
    app.state.pool = None
    app.state.graph = None
    app.state.startup_error = None
    app.state.ready = False
    pool = None
    try:
        ready, status = check_database_ready()
        if not ready:
            app.state.startup_error = "Database schema not ready or pending migrations."
            app.state.ready = False
        else:
            app.state.ready = True
            checkpointer, pool = create_postgres_checkpointer()
            app.state.checkpointer = checkpointer
            app.state.pool = pool
            app.state.graph = build_graph(checkpointer)
            warm_pool()
    except Exception as exc:
        app.state.startup_error = f"{type(exc).__name__}: {exc}"
        app.state.ready = False
    yield
    if pool is not None:
        pool.close()
    close_pool()


app = FastAPI(
    title="Agente Alpina",
    description="Respuestas trazables sobre documentos oficiales de Alpina.",
    version="0.2.0",
    lifespan=lifespan,
)

setup_security_middlewares(app, allow_all_origins=settings.cors_allow_all)

app.include_router(api_router)


@app.get("/")
def index() -> FileResponse:
    """Página principal de la interfaz de usuario web."""
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

__all__ = ["app", "ChatCreate", "MessageCreate", "ReportRequest"]
