from __future__ import annotations

import io
import uuid
import openpyxl
import docx
from pypdfium2 import PdfDocument
from fastapi.testclient import TestClient

from app.main import app
from app.api.deps import SESSION_COOKIE, derive_owner_id
from app.core.crypto import encrypt_text
from app.db.connection import connect
from psycopg.types.json import Jsonb


def test_r12_e2e_synthetic_flow_chat_citation_and_downloads():
    """R12: Recorrido E2E determinista con corpus sintético desde el chat hasta la cita y la descarga de los 3 formatos."""
    client = TestClient(app, base_url="http://localhost")
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

    with connect(session_id=derive_owner_id(sess_id)) as conn:
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
    with PdfDocument(pdf_bytes) as pdf:
        pdf_text = " ".join(page.get_textpage().get_text_range() for page in pdf)

    # B. XLSX
    xlsx_bytes = downloaded_artifacts["xlsx"]
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    assert wb.sheetnames == ["Resumen"]
    xlsx_text = " ".join(str(value) for sheet in wb for row in sheet.values for value in row)
    wb.close()

    # C. DOCX
    docx_bytes = downloaded_artifacts["docx"]
    doc = docx.Document(io.BytesIO(docx_bytes))
    doc_text = " ".join(p.text for p in doc.paragraphs)
    for text in (pdf_text, xlsx_text, doc_text):
        assert "ganancia neta" in text
        assert "$120.000" in text
        assert synthetic_citations[0]["title"] not in text


def test_agent_exports_supplied_data_and_reuses_it_from_chat(monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver

    from app.agent import graph

    def unexpected_lookup(*args, **kwargs):
        raise AssertionError("La exportación de datos pegados funciona sin servicios externos.")

    monkeypatch.setattr(graph, "chat_json", unexpected_lookup)
    monkeypatch.setattr(app.state, "graph", graph.build_graph(InMemorySaver(), retrieve_fn=unexpected_lookup), raising=False)
    client = TestClient(app, base_url="http://localhost")
    chat_id = client.post("/api/chats", json={"title": "Inventario de prueba"}).json()["id"]
    message_url = f"/api/chats/{chat_id}/messages"
    try:
        supplied = client.post(message_url, json={
            "content": "Hazme un Excel con estos datos:\n## Inventario\n\n"
                       "| Producto | Unidades |\n| --- | ---: |\n| Avena | **12** |",
        })
        assert supplied.status_code == 200
        data = supplied.json()
        assert data["metadata"]["report_user_provided"]
        assert not data["verified"] and not data["citations"]
        assert "<strong>12</strong>" in data["assistant_message"]["content_html"]
        report = data["generated_report"]
        assert report["report_type"] == "xlsx"
        response = client.get(report["download_url"])
        assert response.status_code == 200
        workbook = openpyxl.load_workbook(io.BytesIO(response.content))
        assert workbook["Datos"]["B3"].value == 12
        workbook.close()

        client.post(message_url, json={"content": "Gracias"})
        converted = client.post(message_url, json={"content": "Convierte la tabla a Word"}).json()
        assert converted["generated_report"]["report_type"] == "docx"
        response = client.get(converted["generated_report"]["download_url"])
        assert response.status_code == 200
        document = docx.Document(io.BytesIO(response.content))
        assert document.tables[1].cell(1, 1).text == "12"
        assert TestClient(app, base_url="http://localhost").get(converted["generated_report"]["download_url"]).status_code == 404

        history = client.get(message_url).json()
        assert "<table>" in next(msg["content_html"] for msg in history if msg["id"] == data["assistant_message"]["id"])
        pdf = client.post(f"/api/chats/{chat_id}/reports", json={
            "report_type": "pdf", "message_id": data["assistant_message"]["id"],
        })
        assert pdf.status_code == 200
        response = client.get(pdf.json()["download_url"])
        with PdfDocument(response.content) as report:
            assert "Avena" in report[0].get_textpage().get_text_range()
    finally:
        client.delete(f"/api/chats/{chat_id}")


def test_agent_creates_downloadable_report_from_retrieved_information(monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver

    from app.agent import graph

    evidence = {
        "document_id": "N11",
        "document_title": "Matriz interna de inspecciones",
        "page_start": 1,
        "page_end": 1,
        "version": "prueba",
        "content": "La inspección se realiza cada mes.",
    }
    answer = {
        "answer": "~~~markdown\n## Inocuidad\n\nLa inspección se realiza cada mes. [FUENTE 1]\n\n"
                  "**Fuentes oficiales:**\n- Matriz interna de inspecciones.pdf\n~~~",
        "citations": [{"source": 1, "quote": evidence["content"]}],
        "abstained": False,
    }
    monkeypatch.setattr(graph, "chat_json", lambda *args, **kwargs: answer)
    monkeypatch.setattr(
        app.state, "graph", graph.build_graph(InMemorySaver(), retrieve_fn=lambda *_: [evidence]), raising=False,
    )
    client = TestClient(app, base_url="http://localhost")
    chat_id = client.post("/api/chats", json={"title": "Reporte con evidencia"}).json()["id"]
    try:
        turn = client.post(f"/api/chats/{chat_id}/messages", json={
            "content": "Genérame un PDF sobre la política de calidad",
        })
        assert turn.status_code == 200
        data = turn.json()
        assert data["verified"] and data["citations"][0]["title"] == evidence["document_title"]
        assert data["metadata"]["graph_trace"][-1]["detail"] == "generar_pdf"
        assert "<h2>Inocuidad</h2>" in data["assistant_message"]["content_html"]
        report = data["generated_report"]
        assert report["report_type"] == "pdf"
        download = client.get(report["download_url"])
        assert download.status_code == 200
        with PdfDocument(download.content) as document:
            text = " ".join(page.get_textpage().get_text_range() for page in document)
        assert "La inspección se realiza cada mes." in text
        assert evidence["document_title"] not in text and "Fuentes oficiales" not in text
    finally:
        client.delete(f"/api/chats/{chat_id}")


def test_saved_context_and_single_chat_deletion(monkeypatch):
    from app.agent import graph
    from app.reports.generator import local_report_path
    from app.storage.r2 import R2Storage

    monkeypatch.setattr(R2Storage, "is_configured", staticmethod(lambda: False))
    checkpointer, pool = graph.create_postgres_checkpointer()
    monkeypatch.setattr(app.state, "graph", graph.build_graph(checkpointer), raising=False)
    client = TestClient(app, base_url="http://localhost")
    chat_id = client.post("/api/chats", json={"title": "Inventario interno"}).json()["id"]
    other_id = client.post("/api/chats", json={"title": "Otro chat"}).json()["id"]
    marker = "Inventario de control privadamente registrado"
    messages_url = f"/api/chats/{chat_id}/messages"
    try:
        memory = client.post(messages_url, json={"content": f"Estos son los datos:\n{marker}"})
        assert memory.status_code == 200 and memory.json()["generated_report"] is None

        response = client.post(messages_url, json={"content": "Dame un Word"})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["answer"] == marker
        assert data["metadata"]["graph_trace"][-1]["detail"] == "generar_word"
        report = data["generated_report"]
        path = local_report_path(report["report_id"], "docx")
        assert path.is_file()
        assert client.get(report["download_url"]).headers["cache-control"] == "private, no-store"

        owner = derive_owner_id(client.cookies[SESSION_COOKIE])
        with connect(session_id=owner) as conn:
            rows = conn.execute("select checkpoint::text from checkpoints where thread_id = %s", (chat_id,)).fetchall()
            assert rows and all(marker not in row[0] for row in rows)
            blobs = conn.execute("select type, blob from checkpoint_blobs where thread_id = %s", (chat_id,)).fetchall()
            assert any(kind.endswith("+fernet") for kind, _ in blobs)
            assert all(not blob or marker.encode() not in blob for _, blob in blobs)
        with connect() as conn:
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                assert conn.execute(f"select count(*) from {table} where thread_id = %s", (chat_id,)).fetchone() == (0,)

        assert client.delete("/api/chats").status_code == 405
        assert client.delete(f"/api/chats/{chat_id}").status_code == 204
        assert client.get(report["download_url"]).status_code == 404
        assert not path.is_file()
        assert {chat["id"] for chat in client.get("/api/chats").json()} == {other_id}
        assert checkpointer.get_tuple({"configurable": {"thread_id": chat_id}}) is None
    finally:
        for chat in (chat_id, other_id):
            client.delete(f"/api/chats/{chat}")
        pool.close()
