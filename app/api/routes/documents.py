from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response
from psycopg.rows import dict_row

from app.db.connection import connect
from app.documents.preview import PagePreviewError, render_page_png

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("")
def list_documents() -> list[dict]:
    """Lista los documentos oficiales del corpus con sus versiones vigentes."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                select d.id, d.title, d.category, d.doc_type, d.country,
                       d.vigente, v.version, v.page_count,
                       v.extraction_status, v.is_current
                from public.documents d
                join public.document_versions v
                  on v.document_id = d.id and v.is_current
                order by d.id
                """
            )
            return list(cur.fetchall())


@router.get("/{document_id}/pages/{page_number}")
def document_page(
    document_id: str,
    page_number: int,
    quote: str | None = Query(default=None, max_length=500),
) -> Response:
    """Renderiza la imagen PNG de la página solicitada con resaltado de la cita citada."""
    try:
        image = render_page_png(document_id, page_number, quote=quote)
    except PagePreviewError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=image,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
