from __future__ import annotations

import unittest.mock as mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import settings
from app.core.security import setup_security_middlewares
from app.main import app


@pytest.fixture
def client():
    return TestClient(app, base_url="http://localhost")


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
    assert data["startup_error"] == "Error durante el arranque del servicio."


def test_health_endpoint_error_when_graph_not_ready(client):
    """F17: /health must return 'error' when agent graph is not initialized."""
    app.state.graph = None
    app.state.startup_error = "Fatal error"
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "error"
    assert data["agent_ready"] is False


def test_production_health_and_cookie(client, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(app.state, "graph", None, raising=False)
    response = client.get("/health")

    assert response.json() == {"status": "error"}
    assert "Secure" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]


def test_security_middleware_enforces_origins_hosts_and_separate_budgets(monkeypatch):
    monkeypatch.setattr(settings, "cors_allowed_origins", ["https://cliente.example"])
    monkeypatch.setattr(settings, "rate_limit_ip", "2/minute")
    monkeypatch.setattr(settings, "rate_limit_session", "1/minute")
    service = FastAPI()
    service.get("/api/ping")(lambda: {"ok": True})
    setup_security_middlewares(service)
    client = TestClient(service, base_url="http://localhost", client=("192.0.2.10", 50000))
    other_ip = TestClient(service, base_url="http://localhost", client=("192.0.2.11", 50000))
    path = "/api/ping"

    assert client.get(path, headers={"Host": "otro.example"}).status_code == 400
    allowed = client.options(path, headers={
        "Origin": "https://cliente.example", "Access-Control-Request-Method": "GET",
    })
    assert allowed.headers["access-control-allow-origin"] == "https://cliente.example"
    denied = client.options(path, headers={
        "Origin": "https://otro.example", "Access-Control-Request-Method": "GET",
    })
    assert "access-control-allow-origin" not in denied.headers

    first_session = {"X-Session-Id": "sess-probado-001"}
    assert client.get(path, headers=first_session).status_code == 200
    assert other_ip.get(path, headers=first_session).status_code == 429
    assert client.get(path, headers={"X-Session-Id": "sess-probado-002"}).status_code == 200
    limited = client.get(path, headers={"X-Session-Id": "sess-probado-003"})
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0


def test_cookie_uses_forwarded_scheme_from_the_trusted_proxy(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    service = FastAPI()
    service.get("/")(lambda: {})
    setup_security_middlewares(service)
    proxied = ProxyHeadersMiddleware(service, trusted_hosts=["127.0.0.1"])
    headers = {"X-Forwarded-Proto": "https"}

    trusted = TestClient(proxied, base_url="http://localhost", client=("127.0.0.1", 50000))
    untrusted = TestClient(proxied, base_url="http://localhost", client=("192.0.2.10", 50000))
    assert "Secure" in trusted.get("/", headers=headers).headers["set-cookie"]
    assert "Secure" not in untrusted.get("/", headers=headers).headers["set-cookie"]


def test_chat_internal_error_redacted(client):
    """F17: Unhandled agent exceptions must be logged and return sanitized user messages."""
    import uuid
    dummy_chat_id = str(uuid.uuid4())

    with mock.patch("app.api.routes.chats.get_agent_graph", return_value=mock.MagicMock()), \
         mock.patch("app.api.deps.connect") as mock_connect, \
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
    assert res.headers["cache-control"] == "no-cache"
    content = res.text
    # Check race condition guard
    assert "state.activeChatId !== chatId" in content
    # Check draft preservation on error
    assert "storage.session.setComposerDraft" in content
    assert "state.messages.indexOf(userMsg)" in content
    # Check double submission guard
    assert "submitBtn.disabled = busy" in content

    index = client.get("/")
    assert "clear-chats" not in index.text
    assert "delete-chat" in index.text
    assert "script-src 'self'" in index.headers["content-security-policy"]
    assert "msg-export" not in client.get("/static/js/components/chat.js").text


def test_failed_turn_does_not_leave_a_partial_message(client, monkeypatch):
    from app.api.routes import chats

    monkeypatch.setattr(chats, "get_agent_graph", lambda _: object())
    monkeypatch.setattr(chats, "ask", mock.Mock(side_effect=RuntimeError("Simulación de fallo interno")))
    chat_id = client.post("/api/chats", json={"title": "Conversación de prueba"}).json()["id"]
    messages = f"/api/chats/{chat_id}/messages"
    try:
        assert client.post(messages, json={"content": "Una pregunta de prueba"}).status_code == 500
        assert client.get(messages).json() == []
    finally:
        client.delete(f"/api/chats/{chat_id}")

