from __future__ import annotations

import logging
import re
import threading
import uuid
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from app.agent.prompts import ABSTENTION
from app.core.crypto import encrypt_text
from app.db.connection import connect
from app.reports.content import report_sections
from app.reports.financial import is_financial_query
from app.reports.generator import REPORT_MEDIA_TYPES, ReportArtifact, generate_report, local_report_path, report_storage_key
from app.reports.spec import ReportCitation, ReportSpec
from app.storage.r2 import R2Storage

logger = logging.getLogger(__name__)


def _sync_report(artifact: ReportArtifact, storage_key: str, session_id: str) -> None:
    storage = None
    published = False
    try:
        storage = R2Storage()
        storage.upload_file(
            artifact.path, storage_key, content_type=REPORT_MEDIA_TYPES[artifact.report_type],
        )
        with connect(session_id=session_id) as conn, conn.cursor() as cur:
            cur.execute(
                """
                update public.reports
                set metadata = jsonb_set(metadata, '{storage}', '"r2"'::jsonb)
                where id = %s and session_id = %s and status = 'generated'
                """,
                (artifact.report_id, session_id),
            )
            updated = cur.rowcount == 1
        published = updated
    except Exception:
        logger.exception("No se pudo sincronizar el informe en R2")
    finally:
        if storage and not published:
            try:
                storage.delete(storage_key)
            except Exception:
                logger.exception("No se pudo limpiar la copia remota del informe %s", artifact.report_id)


def remove_report_files(report_id: str, report_type: str, stored_key: str | None) -> None:
    if report_type not in REPORT_MEDIA_TYPES:
        return
    try:
        path = local_report_path(report_id, report_type)
        if path and path.is_file():
            path.unlink(missing_ok=True)
            path.parent.rmdir()
    except OSError:
        logger.exception("No se pudo limpiar el archivo local del informe %s", report_id)

    key = report_storage_key(report_id, report_type)
    if stored_key == key and R2Storage.is_configured():
        try:
            R2Storage().delete(key)
        except Exception:
            logger.exception("No se pudo limpiar la copia remota del informe %s", report_id)


def _report_spec(
    question: str,
    answer: str,
    citations: list[ReportCitation],
    category: str,
    verification_status: str,
    user_provided: bool,
) -> ReportSpec:
    sections = report_sections(answer, citations)
    if not any(section.body or section.bullets or section.table for section in sections):
        raise ValueError("La respuesta no contiene información para el informe.")

    subtitle = ""
    if user_provided:
        title = "Informe de datos"
        subtitle = "Datos proporcionados por el usuario"
    elif is_financial_query(question, citations):
        years = list(dict.fromkeys(re.findall(r"\b(?:19|20)\d{2}\b", question)))
        period = " · " + ", ".join(years) if years else ""
        title = f"Resultados financieros de Alpina{period}"[:200]
    elif {citation.document_id.upper() for citation in citations} == {"N11"}:
        title = "Informe de calidad e inocuidad"
    elif category == "regulatory":
        title = "Informe de normativa y etiquetado"
    elif category == "product":
        title = "Informe de productos de Alpina"
    else:
        title = "Informe sobre Alpina"

    if sections[0].heading:
        title = sections[0].heading
        sections[0].heading = ""
        if not (sections[0].body or sections[0].bullets or sections[0].table):
            sections.pop(0)

    return ReportSpec(
        title=title,
        subtitle=subtitle,
        prepared_for="Alpina Productos Alimenticios S.A.S. BIC",
        query=question,
        verification_status=verification_status,
        sections=sections,
        citations=citations,
    )


def _verify_report_chat(conn: Connection, chat_id: str, session_id: str, *, lock: bool = False) -> None:
    query = "select 1 from public.chats where id = %s and session_id = %s"
    if lock:
        query += " for key share"
    if not conn.execute(query, (chat_id, session_id)).fetchone():
        raise ValueError("El chat del reporte no está disponible para esta sesión.")


def create_report_record(
    chat_id: str | None,
    question: str,
    answer: str,
    citations: list[ReportCitation | dict],
    report_type: str = "pdf",
    verification_status: str = "Verificado",
    abstained: bool = False,
    category: str = "",
    session_id: str | None = None,
    *,
    user_provided: bool = False,
) -> dict[str, Any]:
    """Crea y registra formalmente un reporte (PDF, XLSX o DOCX) para una consulta y respuesta dadas."""
    if abstained or not answer.strip() or (not user_provided and answer.strip() == ABSTENTION):
        raise ValueError("No se puede generar un reporte para una respuesta vacía o con abstención.")
    if not session_id:
        raise ValueError("Se requiere una sesión para generar el reporte.")

    clean_citations: list[ReportCitation] = []
    if not user_provided:
        for citation in citations or []:
            try:
                clean_citations.append(ReportCitation.model_validate(citation))
            except ValidationError:
                continue
        if not clean_citations:
            raise ValueError("No se puede generar un reporte para una respuesta sin respaldo documental.")

    spec = _report_spec(
        question, answer, clean_citations, category, verification_status, user_provided,
    )

    clean_chat_id = str(uuid.UUID(chat_id)) if chat_id else None
    if clean_chat_id:
        with connect(session_id=session_id) as conn:
            _verify_report_chat(conn, clean_chat_id, session_id)

    # El contenido completo ya está en el archivo y en el historial cifrado.
    # El registro conserva las citas como metadatos internos de la generación.
    spec_dict = spec.model_dump(mode="json", exclude={"sections"})
    if spec.query:
        spec_dict["query"] = encrypt_text(spec.query)

    artifact = generate_report(spec, report_type)
    try:
        storage_key = report_storage_key(artifact.report_id, artifact.report_type)
        with connect(session_id=session_id) as conn, conn.cursor(row_factory=dict_row) as cur:
            if clean_chat_id:
                _verify_report_chat(conn, clean_chat_id, session_id, lock=True)
            cur.execute(
                """
                insert into public.reports
                    (id, chat_id, session_id, report_type, title, status, spec,
                     storage_key, metadata)
                values (%s, %s, %s, %s, %s, 'generated', %s, %s, %s)
                returning id::text as id, created_at
                """,
                (
                    artifact.report_id,
                    clean_chat_id,
                    session_id,
                    artifact.report_type,
                    spec.title,
                    Jsonb(spec_dict),
                    storage_key,
                    Jsonb({"storage": "local"}),
                ),
            )
            report = cur.fetchone()
    except Exception:
        artifact.discard()
        raise

    if R2Storage.is_configured():
        try:
            threading.Thread(
                target=_sync_report,
                args=(artifact, storage_key, session_id),
                daemon=True,
            ).start()
        except RuntimeError:
            logger.exception("No se pudo iniciar la sincronización del informe %s", artifact.report_id)

    created_at_val = report.get("created_at") if report else None
    if hasattr(created_at_val, "isoformat"):
        created_at_val = created_at_val.isoformat()
    elif created_at_val is not None:
        created_at_val = str(created_at_val)

    return {
        "report_id": artifact.report_id,
        "report_type": artifact.report_type,
        "title": spec.title,
        "filename": artifact.filename,
        "download_url": f"/api/reports/{artifact.report_id}/download",
        "user_provided": user_provided,
        "storage": "local",
        "created_at": created_at_val,
    }
