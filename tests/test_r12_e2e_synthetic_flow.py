from __future__ import annotations

import io
import uuid
import openpyxl
import docx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.crypto import encrypt_text
from app.db.connection import connect
from psycopg.types.json import Jsonb


def test_r12_e2e_synthetic_flow_chat_citation_and_downloads():
    """R12: Recorrido E2E determinista con corpus sintético desde el chat hasta la cita y la descarga de los 3 formatos."""
    client = TestClient(app)
    sess_id = f"sess-e2e-{uuid.uuid4().hex[:12]}"

    # 1. Crear nuevo chat (sesión anónima)
    create_res = client.post(
        "/api/chats",
        json={"title": "Consulta E2E Estados Financieros"},
        headers={"X-Session-Id": sess_id},
    )
    assert create_res.status_code == 200
    chat_data = create_res.json()
    chat_id = chat_data["id"]
    assert chat_id is not None

    # 2. Registrar turno verificado con citas sintéticas en la base de datos
    synthetic_query = "¿Cuál fue la ganancia neta y el desempeño financiero en 2025?"
    synthetic_answer = (
        "La ganancia neta consolidada de Alpina en 2025 alcanzó $120.000 millones de pesos, "
        "con ventas totales de $2.458 billones (+6,3%)."
    )
    synthetic_citations = [
        {
            "document_id": "C4",
            "title": "Estados Financieros Separados 2025 · Alpina S.A.S. BIC",
            "page": 1,
            "version": "2025",
            "quote": "Estados Financieros",
        }
    ]
    synthetic_metadata = {
        "verified": True,
        "abstained": False,
        "verification_mode": "citas",
        "category": "corporate",
    }

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into public.messages (chat_id, role, content, metadata)
                values (%s, 'user', %s, %s)
                """,
                (chat_id, encrypt_text(synthetic_query), Jsonb({})),
            )
            cur.execute(
                """
                insert into public.messages (chat_id, role, content, citations, metadata)
                values (%s, 'assistant', %s, %s, %s)
                returning id::text as id
                """,
                (
                    chat_id,
                    encrypt_text(synthetic_answer),
                    Jsonb(synthetic_citations),
                    Jsonb(synthetic_metadata),
                ),
            )
            assistant_msg_id = cur.fetchone()[0]

    # 3. Consultar historial de mensajes y comprobar descifrado transparente
    history_res = client.get(
        f"/api/chats/{chat_id}/messages",
        headers={"X-Session-Id": sess_id},
    )
    assert history_res.status_code == 200
    messages = history_res.json()
    assert len(messages) >= 2
    assert messages[0]["content"] == synthetic_query
    assert "ganancia neta" in messages[1]["content"].lower()
    assert len(messages[1]["citations"]) == 1
    citation = messages[1]["citations"][0]
    assert citation["document_id"] == "C4"

    # 4. Inspeccionar la cita en el visor documental (PNG y header de resaltado)
    page_res = client.get(
        f"/api/documents/{citation['document_id']}/pages/{citation['page']}?version={citation['version']}&quote={citation['quote']}",
        headers={"X-Session-Id": sess_id},
    )
    assert page_res.status_code == 200
    assert page_res.headers["content-type"] == "image/png"
    assert page_res.headers.get("X-Highlight-Status") in ("exact", "partial")
    assert len(page_res.content) > 1000

    # 5. Exportar y descargar el reporte en los 3 formatos (PDF, XLSX, DOCX) vinculados al mismo turno
    formats = ["pdf", "xlsx", "docx"]
    downloaded_artifacts = {}

    for fmt in formats:
        # Generar reporte explícito para el turno
        gen_res = client.post(
            f"/api/chats/{chat_id}/reports",
            json={
                "message_id": assistant_msg_id,
                "report_type": fmt,
            },
            headers={"X-Session-Id": sess_id},
        )
        assert gen_res.status_code == 200, f"Error al generar reporte {fmt}: {gen_res.text}"
        rep_info = gen_res.json()
        rep_id = rep_info.get("report_id") or rep_info.get("id")
        assert rep_id is not None
        assert rep_info["report_type"] == fmt
        assert rep_info["download_url"].startswith("/api/reports/")

        # Descargar reporte con la sesión autorizada
        dl_res = client.get(
            f"/api/reports/{rep_id}/download",
            headers={"X-Session-Id": sess_id},
        )
        assert dl_res.status_code == 200, f"Error al descargar {fmt}: {dl_res.text}"
        content = dl_res.content
        assert len(content) > 1000
        downloaded_artifacts[fmt] = content

    # 6. Validar integridad de cada formato descargado
    # A. PDF
    pdf_bytes = downloaded_artifacts["pdf"]
    assert pdf_bytes.startswith(b"%PDF")

    # B. XLSX
    xlsx_bytes = downloaded_artifacts["xlsx"]
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    sheet_names = wb.sheetnames
    assert "Resumen" in sheet_names and "Evidencias" in sheet_names
    wb.close()

    # C. DOCX
    docx_bytes = downloaded_artifacts["docx"]
    doc = docx.Document(io.BytesIO(docx_bytes))
    doc_text = " ".join(p.text for p in doc.paragraphs)
    assert "Alpina" in doc_text or "Informe" in doc_text
