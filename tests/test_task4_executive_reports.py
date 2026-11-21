import uuid
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.reports.generator import generate_report
from app.reports.spec import ReportCitation, ReportSection, ReportSpec, ReportTable
from app.reports.word import generate_word_report, render_docx


def test_generate_word_report_function():
    sections = [
        {"heading": "Diagnóstico Ejecutivo", "body": ["Crecimiento sostenido en 2025."], "bullets": ["Aumento en ventas +6,3%"]},
        {"heading": "Desempeño Operacional", "body": ["Control de gastos en distribución."]},
    ]
    recommendations = [
        "Consolidar la distribución en canal tradicional",
        "Optimizar el portafolio bajo la Resolución 2492 de 2022",
    ]
    data = generate_word_report(
        title="Informe Estratégico Alpina 2026",
        topic="Resultados Financieros y Portafolio",
        sections=sections,
        recommendations=recommendations,
    )
    assert isinstance(data, bytes)
    assert len(data) > 5000
    # DOCX is a zip file, starts with PK\x03\x04
    assert data.startswith(b"PK\x03\x04")


def test_generate_all_three_report_formats(tmp_path):
    spec = ReportSpec(
        title="Informe Ejecutivo Integral Alpina",
        subtitle="Auditoría Financiera y Normativa",
        prepared_for="Comité Directivo",
        query="Resultados y cumplimiento normativo",
        summary="Resumen de resultados financieros y normativos del periodo 2025.",
        sections=[
            ReportSection(
                heading="Análisis de Desempeño Financiero",
                body=["Los ingresos operacionales alcanzaron $2.458 B en 2025."],
                bullets=["EBITDA normalizado de $368 M (+5,6%)"],
                table=ReportTable(
                    title="Principales Cifras",
                    columns=["Métrica", "2025", "2024"],
                    rows=[["Ventas", "$2.458 B", "$2.312 B"], ["Margen", "39,7%", "39,5%"]],
                ),
            )
        ],
        citations=[
            ReportCitation(document_id="C4", title="Estados Financieros Separados 2025", page=2, quote="Ganancia neta"),
        ],
    )

    # Test PDF
    art_pdf = generate_report(spec, "pdf", output_root=tmp_path)
    assert art_pdf.report_type == "pdf"
    assert art_pdf.path.is_file()
    assert art_pdf.path.stat().st_size > 1000

    # Test XLSX
    art_xlsx = generate_report(spec, "xlsx", output_root=tmp_path)
    assert art_xlsx.report_type == "xlsx"
    assert art_xlsx.path.is_file()
    assert art_xlsx.path.stat().st_size > 1000

    # Test DOCX
    art_docx = generate_report(spec, "docx", output_root=tmp_path)
    assert art_docx.report_type == "docx"
    assert art_docx.path.is_file()
    assert art_docx.path.stat().st_size > 1000


def test_api_generate_and_download_docx_report():
    from app.core.crypto import encrypt_text
    from app.db.connection import connect
    from app.api.deps import derive_owner_id
    from psycopg.types.json import Jsonb

    client = TestClient(app, base_url="http://localhost")
    sess_id = f"sess-test-{uuid.uuid4().hex[:8]}"

    # Create chat
    c_resp = client.post("/api/chats", json={"title": "Chat para reporte"}, headers={"X-Session-Id": sess_id})
    assert c_resp.status_code == 200
    chat_id = c_resp.json()["id"]

    try:
        # Insert messages into DB (encrypted)
        with connect(session_id=derive_owner_id(sess_id)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.messages (chat_id, role, content, metadata)
                    VALUES (%s, 'user', %s, %s)
                    """,
                    (chat_id, encrypt_text("Resume los resultados financieros de 2025"), Jsonb({})),
                )
                cur.execute(
                    """
                    INSERT INTO public.messages (chat_id, role, content, citations, metadata)
                    VALUES (%s, 'assistant', %s, %s, %s)
                    """,
                    (
                        chat_id,
                        encrypt_text(
                            "Los ingresos de Alpina en 2025 alcanzaron $2.458 B (+6,3%). "
                            "El EBITDA fue de $368 M con margen del 15,0%."
                        ),
                        Jsonb([{"document_id": "C4", "title": "Estados Financieros Separados 2025", "page": 2, "quote": "Ingresos ordinarios"}]),
                        Jsonb({"verified": True}),
                    ),
                )

        # Request Word report
        rep_resp = client.post(
            f"/api/chats/{chat_id}/reports",
            json={"report_type": "docx"},
            headers={"X-Session-Id": sess_id},
        )
        assert rep_resp.status_code == 200
        report_data = rep_resp.json()
        assert report_data["report_type"] == "docx"
        report_id = report_data["report_id"]

        # Download report with valid session
        dl_resp = client.get(f"/api/reports/{report_id}/download", headers={"X-Session-Id": sess_id})
        assert dl_resp.status_code == 200
        assert dl_resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert len(dl_resp.content) > 1000
        assert dl_resp.content.startswith(b"PK\x03\x04")

        # Download report with different session must be rejected (404)
        dl_other = client.get(f"/api/reports/{report_id}/download", headers={"X-Session-Id": f"other-{sess_id}"})
        assert dl_other.status_code == 404

    finally:
        client.delete(f"/api/chats/{chat_id}", headers={"X-Session-Id": sess_id})
