from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.agent.prompts import ABSTENTION
from app.api.deps import (
    chat_uuid as validate_chat_uuid,
    get_current_session_id,
    report_uuid as validate_report_uuid,
)
from app.api.schemas.reports import ReportRequest
from app.config import REPORTS_DIR
from app.core.crypto import decrypt_text
from app.db.connection import connect
from app.reports.service import create_report_record
from app.reports.spec import ReportCitation
from app.storage.r2 import R2Storage, R2StorageError

router = APIRouter(tags=["reports"])
logger = logging.getLogger(__name__)


@router.post("/api/chats/{chat_id}/reports")
def create_report(
    chat_id: str,
    payload: ReportRequest,
    session_id: str = Depends(get_current_session_id),
) -> dict:
    """Genera un informe documental trazable en PDF, XLSX o DOCX para la última respuesta."""
    chat_id_clean = validate_chat_uuid(chat_id)

    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select id, title from public.chats where id = %s and session_id = %s",
                (chat_id_clean, session_id),
            )
            chat = cur.fetchone()
            if not chat:
                raise HTTPException(status_code=404, detail="Chat no encontrado.")

            if payload.message_id:
                cur.execute(
                    """
                    select id, content, citations, metadata, created_at
                    from public.messages
                    where id = %s and chat_id = %s and role = 'assistant'
                    """,
                    (payload.message_id, chat_id_clean),
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
            user_message = cur.fetchone()

    citations: list[ReportCitation] = []
    for citation in assistant.get("citations") or []:
        try:
            citations.append(ReportCitation(**citation))
        except Exception:
            continue

    assistant_metadata = assistant.get("metadata")
    if not isinstance(assistant_metadata, dict):
        assistant_metadata = {}
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
        "Abstención"
        if abstained
        else (
            "Citas OK"
            if verification_mode == "citas"
            else ("Verificado" if verified else "Sin verificar")
        )
    )

    raw_answer = assistant.get("content") or ABSTENTION
    raw_question = (user_message or {}).get("content") or "Consulta documental"
    clean_answer = decrypt_text(raw_answer)
    clean_question = decrypt_text(raw_question)

    # R04: Una abstención o respuesta sin respaldo documental NO debe publicar un archivo
    if not verified or abstained or not citations or clean_answer.strip() == ABSTENTION:
        raise HTTPException(
            status_code=400,
            detail="No se puede exportar un reporte para una respuesta con abstención o sin evidencia documental verificada.",
        )

    try:
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
        )
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
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                select report_type, storage_key, metadata, status, title, session_id
                from public.reports
                where id = %s and (
                    session_id = %s
                    or (session_id is null and exists (
                        select 1 from public.chats c where c.id = reports.chat_id and c.session_id = %s
                    ))
                )
                """,
                (report_id_clean, session_id, session_id),
            )
            report = cur.fetchone()

    if not report or report.get("status") != "generated":
        raise HTTPException(status_code=404, detail="Reporte no encontrado.")

    metadata = report.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    report_type = str(report.get("report_type") or "pdf").lower()
    if report_type == "docx":
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif report_type == "xlsx":
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        media_type = "application/pdf"
    filename = Path(str(metadata.get("filename") or "reporte")).name
    disposition = "inline" if inline else "attachment"

    # Prioridad 1: Si el archivo existe en el disco local del servidor, servirlo de inmediato (0ms latencia)
    path = Path(str(metadata.get("path") or "")).resolve()
    reports_root = REPORTS_DIR.resolve()
    if path.is_file() and path.is_relative_to(reports_root):
        return FileResponse(
            path,
            media_type=media_type,
            filename=filename,
            content_disposition_type=disposition,
        )

    # Prioridad 2: Fallback a Cloudflare R2 si no está en disco local (despliegues distribuidos/efímeros)
    if metadata.get("storage") == "r2" or report.get("storage_key"):
        r2_key = metadata.get("r2_key") or report.get("storage_key")
        if r2_key and R2Storage.is_configured():
            try:
                data = R2Storage().get_bytes(str(r2_key))
                return Response(
                    content=data,
                    media_type=media_type,
                    headers={
                        "Content-Disposition": f'{disposition}; filename="{filename}"'
                    },
                )
            except R2StorageError:
                pass

    raise HTTPException(status_code=404, detail="Archivo de reporte no encontrado.")
