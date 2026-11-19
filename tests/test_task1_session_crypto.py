import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.crypto import encrypt_text, decrypt_text, get_fernet
from app.db.connection import connect


def test_crypto_fernet_roundtrip():
    original = "Reporte Confidencial Alpina 2026: Ventas +15%"
    cipher = encrypt_text(original)
    assert cipher != original
    # Fernet tokens start with gAAAAA
    assert cipher.startswith("gAAAAA")
    decrypted = decrypt_text(cipher)
    assert decrypted == original


def test_crypto_legacy_plaintext_passthrough():
    legacy = "Mensaje plano preexistente"
    assert decrypt_text(legacy) == legacy
    assert decrypt_text("") == ""
    assert decrypt_text(None) == ""


def test_session_isolation_and_encryption():
    client = TestClient(app)
    session_a = f"sess-test-{uuid.uuid4().hex[:8]}"
    session_b = f"sess-test-{uuid.uuid4().hex[:8]}"

    # 1. Session A creates a chat
    title_a = "Análisis Financiero Alpina A"
    resp = client.post(
        "/api/chats",
        json={"title": title_a},
        headers={"X-Session-Id": session_a},
    )
    assert resp.status_code == 200
    chat_a = resp.json()
    chat_a_id = chat_a["id"]
    assert chat_a["title"] == title_a

    try:
        # Check raw DB row to confirm title is encrypted
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT title, session_id FROM public.chats WHERE id = %s", (chat_a_id,))
                raw_row = cur.fetchone()
                raw_title, raw_session_id = raw_row[0], raw_row[1]
                assert raw_session_id == session_a
                assert raw_title != title_a
                assert raw_title.startswith("gAAAAA")
                assert decrypt_text(raw_title) == title_a

        # 2. Session A lists chats -> sees chat A decrypted
        resp_list_a = client.get("/api/chats", headers={"X-Session-Id": session_a})
        assert resp_list_a.status_code == 200
        chats_a = resp_list_a.json()
        assert any(c["id"] == chat_a_id and c["title"] == title_a for c in chats_a)

        # 3. Session B lists chats -> does NOT see chat A
        resp_list_b = client.get("/api/chats", headers={"X-Session-Id": session_b})
        assert resp_list_b.status_code == 200
        chats_b = resp_list_b.json()
        assert not any(c["id"] == chat_a_id for c in chats_b)

        # 4. Session B tries to read messages of chat A -> 404 Forbidden/NotFound
        resp_msg_b = client.get(f"/api/chats/{chat_a_id}/messages", headers={"X-Session-Id": session_b})
        assert resp_msg_b.status_code == 404

        # 5. Session B tries to delete chat A -> 404 Forbidden/NotFound
        resp_del_b = client.delete(f"/api/chats/{chat_a_id}", headers={"X-Session-Id": session_b})
        assert resp_del_b.status_code == 404

    finally:
        # Clean up chat_a
        client.delete(f"/api/chats/{chat_a_id}", headers={"X-Session-Id": session_a})
