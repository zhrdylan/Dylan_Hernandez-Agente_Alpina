from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from psycopg.rows import dict_row

from app.api.deps import (
    OwnedChat,
    get_current_session_id,
    get_owned_chat,
    report_uuid as validate_report_uuid,
    validate_uuid,
)
from app.api.schemas.reports import ReportRequest
from app.core.crypto import DecryptionError, decrypt_text
from app.db.connection import connect
from app.reports.service import create_report_record
from app.reports.generator import REPORT_MEDIA_TYPES, local_report_path, report_filename, report_storage_key
from app.storage.r2 import R2Storage, R2StorageError

router = APIRouter(tags=["reports"])
logger = logging.getLogger(__name__)


@router.post("/api/chats/{chat_id}/reports")
def create_report(
    payload: ReportRequest,
    chat: OwnedChat = Depends(get_owned_chat),
) -> dict:
    """Genera un informe en PDF, XLSX o DOCX a partir de una respuesta del chat."""
    chat_id_clean = chat.id
    session_id = chat.session_id
    message_id = validate_uuid(payload.message_id, "message_id") if payload.message_id else None

    with connect(session_id=session_id) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if message_id:
                cur.execute(
                    """
                    select id, content, citations, metadata, created_at
                    from public.messages
                    where id = %s and chat_id = %s and role = 'assistant'
                    """,
                    (message_id, chat_id_clean),
                )
                assistant = cur.fetchone()
            else:
                cur.execute(
                    """
                    select id, content, citations, metadata, created_at
                    from public.messages
                    where chat_id = %s and role = 'assistant'
                    order by created_at desc, id desc
                    limit 1
                    """,
                    (chat_id_clean,),
                )
                assistant = cur.fetchone()

            if not assistant:
                raise HTTPException(
                    status_code=400,
                    detail="La conversación aún no tiene una respuesta para reportar.",
                )

            assistant_metadata = assistant.get("metadata")
            if not isinstance(assistant_metadata, dict):
                assistant_metadata = {}
            user_provided = assistant_metadata.get("report_user_provided") is True
            raw_question = assistant_metadata.get("report_question") or ""
            if not raw_question and not user_provided:
                cur.execute(
                    """
                    select content
                    from public.messages
                    where chat_id = %s and role = 'user' and created_at <= %s
                    order by created_at desc, id desc
                    limit 1
                    """,
                    (chat_id_clean, assistant["created_at"]),
                )
                raw_question = (cur.fetchone() or {}).get("content") or ""

    citations = assistant.get("citations") or []
    abstained = bool(assistant_metadata.get("abstained"))
    verified = bool(assistant_metadata.get("verified"))
    verification_mode = assistant_metadata.get("verification_mode")
    assistant_issues = assistant_metadata.get("issues") or []
    if not verification_mode and any(
        "Verificador no disponible" in str(issue)
        or "Verificación determinista de citas" in str(issue)
        for issue in assistant_issues
    ):
        verification_mode = "citas"
    verification_status = (
        "Datos del usuario" if user_provided else (
            "Citas OK" if verification_mode == "citas" else "Verificado"
        )
    )

    if abstained or (not user_provided and (not verified or not citations)):
        raise HTTPException(
            status_code=400,
            detail="No se puede exportar un reporte para una respuesta con abstención o sin evidencia documental verificada.",
        )

    try:
        clean_answer = decrypt_text(assistant.get("content"))
        clean_question = decrypt_text(raw_question)
        return create_report_record(
            chat_id=chat_id_clean,
            question=clean_question,
            answer=clean_answer,
            citations=citations,
            report_type=payload.report_type,
            verification_status=verification_status,
            abstained=abstained,
            category=str(assistant_metadata.get("category") or "").lower(),
            session_id=session_id,
            user_provided=user_provided,
        )
    except DecryptionError as exc:
        raise HTTPException(status_code=422, detail="No se pudo leer el contenido cifrado del informe.") from exc
    except ValueError as val_exc:
        raise HTTPException(status_code=400, detail=str(val_exc)) from val_exc
    except Exception as exc:
        logger.exception("No se pudo generar el reporte para el chat %s", chat_id_clean)
        raise HTTPException(
            status_code=500,
            detail="No se pudo generar el reporte. Vuelve a intentarlo en unos instantes.",
        ) from exc


@router.get("/api/reports/{report_id}/download")
def download_report(
    report_id: str,
    inline: bool = False,
    session_id: str = Depends(get_current_session_id),
) -> Response:
    """Descarga o previsualización segura de un informe generado desde Cloudflare R2 o almacenamiento local."""
    report_id_clean = validate_report_uuid(report_id)
    with connect(session_id=session_id) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                select report_type, storage_key, status
                from public.reports
                where id = %s and session_id = %s
                """,
                (report_id_clean, session_id),
            )
            report = cur.fetchone()

    if not report or report.get("status") != "generated":
        raise HTTPException(status_code=404, detail="Reporte no encontrado.")

    report_type = report["report_type"]
    media_type = REPORT_MEDIA_TYPES.get(report_type)
    if not media_type:
        raise HTTPException(status_code=404, detail="Reporte no encontrado.")

    filename = report_filename(report_id_clean, report_type)
    disposition = "inline" if inline and report_type == "pdf" else "attachment"
    path = local_report_path(report_id_clean, report_type)
    if path and path.is_file():
        return FileResponse(
            path,
            media_type=media_type,
            filename=filename,
            content_disposition_type=disposition,
        )

    key = report_storage_key(report_id_clean, report_type)
    if report.get("storage_key") == key and R2Storage.is_configured():
        try:
            return Response(
                content=R2Storage().get_bytes(key),
                media_type=media_type,
                headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
            )
        except R2StorageError:
            logger.warning("No se pudo leer la copia remota del informe %s", report_id_clean)

    raise HTTPException(status_code=404, detail="Archivo de reporte no encontrado.")
