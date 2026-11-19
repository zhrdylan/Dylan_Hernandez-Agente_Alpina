from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Request, Query
from psycopg.rows import dict_row

from app.config import settings
from app.db.connection import connect

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    """Estado del servicio y del agente conversacional."""
    startup_error = getattr(request.app.state, "startup_error", None)
    agent_ready = getattr(request.app.state, "graph", None) is not None
    is_ready = bool(getattr(request.app.state, "ready", agent_ready)) and agent_ready and not startup_error
    if not is_ready:
        status = "degraded" if agent_ready else "error"
    else:
        status = "ok"
    
    # En desarrollo/pruebas expone la cadena técnica para depuración; en producción la redacta
    err_display = (
        str(startup_error)
        if startup_error and settings.app_env != "production"
        else ("Error durante el arranque del servicio." if startup_error else None)
    )

    return {
        "status": status,
        "environment": settings.app_env,
        "agent_ready": agent_ready,
        "database_ready": bool(getattr(request.app.state, "ready", False)),
        "startup_error": err_display,
        "error": "Error durante el arranque del servicio." if startup_error else None,
    }


@router.get("/api/suggestions")
def suggestions(limit: int = Query(default=6, ge=1, le=10)) -> dict:
    """Genera preguntas sugeridas de ejemplo a partir de documentos y productos."""
    items: list[str] = []
    try:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    select id, title
                    from public.documents
                    order by md5(id)
                    limit 3
                    """
                )
                for row in cur.fetchall():
                    items.append(f"¿Qué dice {row['title']}?")

                cur.execute(
                    """
                    select name
                    from public.products
                    where ean is not null
                    order by md5(id)
                    limit 3
                    """
                )
                for row in cur.fetchall():
                    name = " ".join(str(row["name"]).split())
                    if name:
                        items.append(f"¿Qué información oficial tienes de {name}?")
    except Exception:
        items = []

    unique: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = item.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(item)
        if len(unique) >= limit:
            break
    return {"items": unique, "total": len(unique)}


@router.get("/api/stats")
def stats() -> dict:
    """Métricas globales de la base de conocimiento oficial."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                select
                    (select count(*) from public.documents) as documents,
                    (select count(*) from public.products) as products,
                    (select count(*) from public.chunks) as chunks,
                    (select count(*) from public.chunk_embeddings) as embeddings,
                    (select coalesce(sum(page_count), 0)
                     from public.document_versions
                     where is_current) as pages
                """
            )
            return cur.fetchone() or {
                "documents": 0,
                "products": 0,
                "chunks": 0,
                "embeddings": 0,
                "pages": 0,
            }
