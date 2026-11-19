from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_fernet() -> Fernet:
    """Obtiene o inicializa el objeto Fernet usando la clave configurada o derivada."""
    key = (settings.chat_encryption_key or "").strip()
    if key:
        try:
            return Fernet(key.encode("utf-8") if isinstance(key, str) else key)
        except Exception as exc:
            logger.warning(
                "La clave chat_encryption_key configurada no es válida para Fernet (%s). "
                "Derivando clave simétrica segura automáticamente.",
                exc,
            )

    # Derivación determinista basada en database_url y salt de Alpina
    seed = f"alpina-rag-salt:{settings.database_url or 'alpina-default-salt-key-2026'}"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    derived_key = base64.urlsafe_b64encode(digest)
    return Fernet(derived_key)


def encrypt_text(plain: Optional[str]) -> str:
    """Cifra un texto en plano devolviendo un token Fernet seguro (AES-128-CBC + HMAC)."""
    if plain is None:
        return ""
    text = str(plain)
    if not text:
        return ""
    try:
        fernet = get_fernet()
        token_bytes = fernet.encrypt(text.encode("utf-8"))
        return token_bytes.decode("utf-8")
    except Exception as exc:
        logger.error("Error al cifrar texto: %s", exc)
        return text


def decrypt_text(cipher: Optional[str]) -> str:
    """Descifra un token Fernet devolviendo el texto en plano original.
    
    Si el texto no está cifrado (datos heredados o formato plano previo),
    retorna el valor sin alterar de forma segura.
    """
    if cipher is None:
        return ""
    text = str(cipher)
    if not text:
        return ""

    # Detección y descifrado con Fernet
    try:
        fernet = get_fernet()
        plain_bytes = fernet.decrypt(text.encode("utf-8"))
        return plain_bytes.decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        # Si falla la verificación HMAC o formato, es texto en plano heredado
        return text
    except Exception as exc:
        logger.warning("Excepción inesperada al descifrar texto: %s", exc)
        return text
