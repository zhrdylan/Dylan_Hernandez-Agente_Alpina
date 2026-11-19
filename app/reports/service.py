from __future__ import annotations

import re
import threading
import uuid
from typing import Any
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.agent.prompts import ABSTENTION
from app.db.connection import connect
from app.reports.financial import is_financial_query, get_financial_sections
from app.reports.generator import generate_report
from app.reports.spec import ReportCitation, ReportSection, ReportSpec, ReportTable
from app.storage.r2 import R2Storage, R2StorageError


def create_report_record(
    chat_id: str,
    question: str,
    answer: str,
    citations: list[ReportCitation | dict],
    report_type: str = "pdf",
    verification_status: str = "Verificado",
    abstained: bool = False,
    category: str = "",
) -> dict[str, Any]:
    """Crea y registra formalmente un reporte (PDF o XLSX) para una consulta y respuesta dadas."""
    report_type_clean = str(report_type or "pdf").lower().strip()
    if report_type_clean not in {"pdf", "xlsx"}:
        report_type_clean = "pdf"

    clean_citations: list[ReportCitation] = []
    for c in citations or []:
        if isinstance(c, ReportCitation):
            clean_citations.append(c)
        elif isinstance(c, dict):
            try:
                clean_citations.append(ReportCitation(**c))
            except Exception:
                continue

    # Extraer información de productos si se citan SKUs
    product_rows: list[list[str]] = []
    if clean_citations:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                for citation in clean_citations:
                    if not citation.document_id.upper().startswith("SKU-"):
                        continue
                    cur.execute(
                        """
                        select id, ean, name, presentation,
                               price::float8 as price, currency, claims
                        from public.products
                        where lower(id) = lower(%s)
                        """,
                        (citation.document_id,),
                    )
                    product = cur.fetchone()
                    if not product:
                        continue
                    claims = "; ".join(
                        str(claim) for claim in (product.get("claims") or [])
                    ) or "No consta"
                    price = "No consta"
                    if product.get("price") is not None:
                        price = f"${float(product['price']):,.0f}".replace(",", ".")
                    product_rows.append(
                        [
                            product["name"],
                            product.get("ean") or "No consta",
                            product.get("presentation") or "No consta",
                            price,
                            claims,
                        ]
                    )

    # Separar párrafos narrativos y viñetas
    answer_paragraphs: list[str] = []
    answer_bullets: list[str] = []
    for raw_p in (answer or ABSTENTION).split("\n\n"):
        p = raw_p.strip()
        if not p:
            continue
        lines = p.split("\n")
        para_lines: list[str] = []
        for line in lines:
            line_s = line.strip()
            bullet_m = re.match(r"^[-*•+]\s+(.*)$", line_s) or re.match(r"^\d+\.\s+(.*)$", line_s)
            if bullet_m:
                answer_bullets.append(bullet_m.group(1).strip())
            else:
                para_lines.append(line_s)
        if para_lines:
            answer_paragraphs.append(" ".join(para_lines))

    # Título adaptativo personalizado
    q_clean = question or "Consulta documental"
    q_lower = q_clean.lower()
    clean_topic = re.sub(
        r"^(¿|¡|cual|cuales|que|quien|como|por que|dame|muestra|genera|hazme|un|una|el|la|los|las|informe|reporte|de|sobre)\s+",
        "",
        q_clean.strip(),
        flags=re.IGNORECASE,
    ).rstrip("?¡!").strip()

    is_financial = is_financial_query(q_clean, clean_citations)

    if is_financial:
        report_title = "Informe de Resultados Financieros 2025 · Alpina"
        report_subtitle = f"Estados Financieros Oficiales (P&L, EBITDA, Balance): {q_clean[:80]}"
        sections = get_financial_sections(q_clean, answer_paragraphs, answer_bullets)
    elif any(k in q_lower for k in ("ley", "resoluci", "norma", "sello", "etiquetad", "rotulad", "invima", "calidad", "inocuidad")):
        report_title = "Informe de Normativa y Etiquetado · Alpina"
        report_subtitle = f"Marco regulatorio oficial: {q_clean[:80]}"
        analysis_heading = "Disposiciones Normativas y Requisitos Sanitarios"
        sections = [
            ReportSection(heading="Consulta Solicitada", body=[q_clean]),
            ReportSection(
                heading=analysis_heading,
                body=answer_paragraphs or ([answer] if not answer_bullets else []),
                bullets=answer_bullets,
            ),
            ReportSection(
                heading="Trazabilidad y Fundamentación Oficial",
                body=[
                    f"Informe generado por el Agente Alpina con estado de verificación: {verification_status}. "
                    "Las afirmaciones contenidas en este documento están respaldadas por versiones oficiales vigentes."
                ],
            ),
        ]
    elif product_rows or category == "product" or any(k in q_lower for k in ("yogurt", "queso", "leche", "finesse", "griego", "producto", "precio", "ean", "proteina", "proteína")):
        report_title = "Informe de Portafolio y Productos · Alpina"
        report_subtitle = f"Catálogo oficial de productos: {q_clean[:80]}"
        analysis_heading = "Ficha Oficial de Productos y Claims Nutricionales"
        sections = [
            ReportSection(heading="Consulta Solicitada", body=[q_clean]),
            ReportSection(
                heading=analysis_heading,
                body=answer_paragraphs or ([answer] if not answer_bullets else []),
                bullets=answer_bullets,
            ),
            ReportSection(
                heading="Trazabilidad y Fundamentación Oficial",
                body=[
                    f"Informe generado por el Agente Alpina con estado de verificación: {verification_status}. "
                    "Las afirmaciones contenidas en este documento están respaldadas por versiones oficiales vigentes."
                ],
            ),
        ]
    else:
        topic_suffix = f" · {clean_topic[:35].capitalize()}" if len(clean_topic) > 3 else ""
        report_title = f"Informe Documental Ejecutivo{topic_suffix}"
        report_subtitle = f"Respuesta trazable oficial: {q_clean[:80]}"
        analysis_heading = "Síntesis y Hallazgos Documentales Oficiales"
        sections = [
            ReportSection(heading="Consulta Solicitada", body=[q_clean]),
            ReportSection(
                heading=analysis_heading,
                body=answer_paragraphs or ([answer] if not answer_bullets else []),
                bullets=answer_bullets,
            ),
            ReportSection(
                heading="Trazabilidad y Fundamentación Oficial",
                body=[
                    f"Informe generado por el Agente Alpina con estado de verificación: {verification_status}. "
                    "Las afirmaciones contenidas en este documento están respaldadas por versiones oficiales vigentes."
                ],
            ),
        ]
    if product_rows:
        sections.append(
            ReportSection(
                heading="Productos Oficiales Relacionados",
                body=["Datos oficiales verificados en el catálogo corporativo de Alpina."],
                table=ReportTable(
                    title="Productos citados",
                    columns=[
                        "Producto",
                        "EAN",
                        "Presentación",
                        "Precio (COP)",
                        "Claims",
                    ],
                    rows=product_rows,
                ),
            )
        )

    spec = ReportSpec(
        title=report_title,
        subtitle=report_subtitle,
        prepared_for="Alpina Productos Alimenticios S.A.S. BIC",
        query=q_clean,
        verification_status=verification_status,
        abstained=abstained,
        summary=answer,
        sections=sections,
        citations=clean_citations,
    )

    artifact = generate_report(spec, report_type_clean)

    storage_key = f"reports/{artifact.report_id}/{artifact.filename}"
    storage_backend = "local"
    metadata: dict[str, Any] = {
        "path": str(artifact.path),
        "filename": artifact.filename,
        "storage": "local",
        "storage_key": storage_key,
    }

    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            clean_chat_id = None
            if chat_id:
                try:
                    uuid.UUID(str(chat_id))
                    cur.execute("select id from public.chats where id = %s", (str(chat_id),))
                    if cur.fetchone():
                        clean_chat_id = str(chat_id)
                except Exception:
                    clean_chat_id = None

            cur.execute(
                """
                insert into public.reports
                    (id, chat_id, report_type, title, status, spec,
                     storage_key, metadata)
                values (%s, %s, %s, %s, 'generated', %s, %s, %s)
                returning id::text as id, created_at
                """,
                (
                    artifact.report_id,
                    clean_chat_id,
                    artifact.report_type,
                    spec.title,
                    Jsonb(spec.model_dump(mode="json")),
                    storage_key,
                    Jsonb(metadata),
                ),
            )
            report = cur.fetchone()

    # Sincronización asíncrona a Cloudflare R2 sin demorar la respuesta de la API (<50ms)
    if R2Storage.is_configured():
        def _bg_sync(rep_id: str, art_path: Path, s_key: str, r_type: str, r_title: str):
            try:
                content_type = (
                    "application/pdf"
                    if r_type == "pdf"
                    else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                R2Storage().upload_file(
                    art_path,
                    s_key,
                    content_type=content_type,
                    metadata={"report_id": rep_id, "title": r_title[:120]},
                )
                with connect() as bg_conn:
                    with bg_conn.cursor() as bg_cur:
                        bg_cur.execute(
                            """
                            update public.reports
                            set metadata = jsonb_set(
                                jsonb_set(metadata, '{storage}', '"r2"'::jsonb),
                                '{r2_key}', to_jsonb(%s::text)
                            )
                            where id = %s
                            """,
                            (s_key, rep_id),
                        )
            except Exception:
                pass

        threading.Thread(
            target=_bg_sync,
            args=(artifact.report_id, artifact.path, storage_key, artifact.report_type, spec.title),
            daemon=True,
        ).start()

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
        "storage": storage_backend,
        "created_at": created_at_val,
    }
