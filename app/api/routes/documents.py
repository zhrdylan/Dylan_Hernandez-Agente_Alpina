from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse
from psycopg.rows import dict_row

from app.db.connection import connect
from app.documents.preview import (
    PagePreviewError,
    get_document_page_count,
    render_page_png,
    resolve_document_pdf,
    resolve_document_title,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("")
def list_documents() -> list[dict]:
    """Lista los documentos oficiales del corpus con sus nombres oficiales y metadatos vigentes."""
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
            rows = list(cur.fetchall())
            for row in rows:
                official = resolve_document_title(row["id"])
                if official:
                    row["title"] = official
                if not row.get("page_count") or row["page_count"] <= 0:
                    real_pages = get_document_page_count(row["id"])
                    if real_pages > 0:
                        row["page_count"] = real_pages
            return rows


@router.get("/{document_id}/pdf")
def get_document_pdf(document_id: str) -> FileResponse:
    """Descarga o visualización directa del PDF íntegro vía FileResponse."""
    try:
        pdf_path = resolve_document_pdf(document_id)
    except PagePreviewError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    title = resolve_document_title(document_id)
    safe_title = "".join(c for c in title if c.isalnum() or c in " ._-·()")[:80]
    filename = f"{document_id}_{safe_title}.pdf" if safe_title else f"{document_id}.pdf"

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=filename,
    )


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
