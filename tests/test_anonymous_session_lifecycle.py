import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.crypto import encrypt_text, decrypt_text, EncryptionError, DecryptionError


def test_anonymous_session_cookie_issuance():
    client = TestClient(app)
    # Request without session header or cookie
    resp = client.get("/api/chats")
    assert resp.status_code == 200
    # Response must set HttpOnly cookie alpina_session_id
    cookie = resp.cookies.get("alpina_session_id")
    assert cookie is not None
    assert cookie.startswith("sess-")
    # Response header X-Session-Id must not be exposed to the client (R05)
    assert resp.headers.get("X-Session-Id") is None


def test_cross_session_report_isolation():
    client = TestClient(app)
    sess1 = f"sess-{uuid.uuid4().hex}"
    sess2 = f"sess-{uuid.uuid4().hex}"

    # Session 1 creates a chat
    c_resp = client.post("/api/chats", json={"title": "Chat S1"}, headers={"X-Session-Id": sess1})
    assert c_resp.status_code == 200
    chat_id = c_resp.json()["id"]

    try:
        # Session 2 tries to create report on Session 1's chat -> 404
        r_resp = client.post(
            f"/api/chats/{chat_id}/reports",
            json={"report_type": "pdf"},
            headers={"X-Session-Id": sess2},
        )
        assert r_resp.status_code == 404
    finally:
        client.delete(f"/api/chats/{chat_id}", headers={"X-Session-Id": sess1})


def test_corrupt_fernet_token_raises_decryption_error():
    # Corrupt token that starts with gAAAAA but has tampered HMAC/payload
    tampered = "gAAAAABl-fake-tampered-token-that-fails-hmac-verification-12345"
    with pytest.raises(DecryptionError):
        decrypt_text(tampered)


def test_key_rotation_with_multifernet(monkeypatch):
    from cryptography.fernet import Fernet
    from app.config import settings
    from app.core.crypto import rotate_encrypted_text, get_fernet

    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()

    # Cifrar con clave antigua
    old_f = Fernet(old_key.encode())
    plain = "Información confidencial para rotación de claves Alpina"
    old_token = old_f.encrypt(plain.encode()).decode()

    # Configurar MultiFernet con new_key como primaria y old_key como secundaria
    monkeypatch.setattr(settings, "chat_encryption_key", f"{new_key},{old_key}")
    get_fernet.cache_clear()

    # Descifrado transparente usando la clave secundaria
    assert decrypt_text(old_token) == plain

    # Rotación re-cifra el token con la nueva clave primaria
    rotated = rotate_encrypted_text(old_token)
    assert rotated != old_token
    new_f = Fernet(new_key.encode())
    assert new_f.decrypt(rotated.encode()).decode() == plain
    get_fernet.cache_clear()
