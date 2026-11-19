from __future__ import annotations

import unittest.mock as mock
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_endpoint_healthy(client):
    """F17: /health must return ok when agent is ready and no startup errors exist."""
    app.state.graph = mock.MagicMock()
    app.state.startup_error = None
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["agent_ready"] is True
    assert data["startup_error"] is None


def test_health_endpoint_degraded_on_startup_error(client):
    """F17: /health must not return 'ok' when a startup error occurred."""
    app.state.graph = mock.MagicMock()
    app.state.startup_error = "DatabaseConnectionTimeout: failed"
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "degraded"
    assert data["startup_error"] == "DatabaseConnectionTimeout: failed"


def test_health_endpoint_error_when_graph_not_ready(client):
    """F17: /health must return 'error' when agent graph is not initialized."""
    app.state.graph = None
    app.state.startup_error = "Fatal error"
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "error"
    assert data["agent_ready"] is False


def test_chat_internal_error_redacted(client):
    """F17: Unhandled agent exceptions must be logged and return sanitized user messages."""
    import uuid
    dummy_chat_id = str(uuid.uuid4())

    with mock.patch("app.api.routes.chats.get_agent_graph", return_value=mock.MagicMock()), \
         mock.patch("app.api.routes.chats.connect") as mock_connect, \
         mock.patch("app.api.routes.chats.ask", side_effect=ValueError("Secret internal DB host: postgres://secret@aws")):
        
        mock_conn = mock.MagicMock()
        mock_cur = mock.MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.return_value = {"id": dummy_chat_id, "title": "Test Chat"}

        res = client.post(
            f"/api/chats/{dummy_chat_id}/messages",
            json={"content": "Mensaje de prueba"},
            cookies={"alpina_session_id": "sess-test1234567890"},
        )
        assert res.status_code == 500
        detail = res.json()["detail"]
        assert "postgres://secret@aws" not in detail
        assert "Error al procesar la consulta con el agente" in detail


def test_r11_ui_static_files_served_and_contract_guarantees(client):
    """R11: Static JS and UI entrypoints must be accessible and contain resilience logic."""
    res = client.get("/static/js/main.js")
    assert res.status_code == 200
    content = res.text
    # Check race condition guard
    assert "state.activeChatId !== chatId" in content
    # Check draft preservation on error
    assert "storage.session.setComposerDraft" in content
    assert "state.messages.pop()" in content
    # Check double submission guard
    assert "submitBtn.disabled = true" in content

