from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import DATA_DIR, settings

logger = logging.getLogger(__name__)


class CryptoError(RuntimeError):
    """Error base para operaciones criptográficas."""
    pass


class EncryptionError(CryptoError):
    """Error emitido cuando el cifrado falla (impide escrituras en texto plano inadvertidas)."""
    pass


class DecryptionError(CryptoError):
    """Error emitido cuando un token cifrado es inválido o su HMAC ha sido manipulado."""
    pass


@lru_cache(maxsize=1)
def get_fernet() -> Fernet:
    """Obtiene e inicializa la instancia Fernet con validación estricta de clave."""
    key = (settings.chat_encryption_key or "").strip()
    if key:
        try:
            key_bytes = key.encode("utf-8") if isinstance(key, str) else key
            return Fernet(key_bytes)
        except Exception as exc:
            raise CryptoError(
                f"La clave CHAT_ENCRYPTION_KEY configurada no es válida para Fernet: {exc}"
            ) from exc

    if settings.app_env.lower() == "production":
        raise CryptoError(
            "CHAT_ENCRYPTION_KEY es obligatoria en entornos de producción para asegurar los datos en reposo."
        )

    # Entorno de desarrollo / pruebas: persistir clave dedicada en disco para consistencia entre reinicios
    key_path = DATA_DIR / ".dev_chat_key"
    if key_path.is_file():
        try:
            persisted = key_path.read_text(encoding="utf-8").strip()
            return Fernet(persisted.encode("utf-8"))
        except Exception:
            pass

    new_key = Fernet.generate_key().decode("utf-8")
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        key_path.write_text(new_key, encoding="utf-8")
        logger.warning(
            "No se especificó CHAT_ENCRYPTION_KEY en .env. Se generó y guardó una clave de desarrollo en %s",
            key_path,
        )
    except Exception as exc:
        logger.warning("No se pudo persistir la clave de desarrollo en disco: %s", exc)

    return Fernet(new_key.encode("utf-8"))


def encrypt_text(plain: Optional[str]) -> str:
    """Cifra un texto en plano devolviendo un token Fernet seguro (AES-128-CBC + HMAC).
    
    Si el cifrado falla, LANZA EncryptionError para evitar escrituras en texto claro.
    """
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
        logger.error("Fallo crítico al cifrar texto: %s", exc)
        raise EncryptionError(f"Fallo en cifrado de texto: {exc}") from exc


def decrypt_text(cipher: Optional[str]) -> str:
    """Descifra un token Fernet devolviendo el texto en plano original.
    
    Si el texto no es un token Fernet (datos planos heredados), se retorna tal cual.
    Si es un token Fernet manipulado o corrupto, lanza DecryptionError.
    """
    if cipher is None:
        return ""
    text = str(cipher)
    if not text:
        return ""

    # Detección estricta de token Fernet (prefijo estándar base64 'gAAAAA')
    if text.startswith("gAAAAA"):
        try:
            fernet = get_fernet()
            plain_bytes = fernet.decrypt(text.encode("utf-8"))
            return plain_bytes.decode("utf-8")
        except InvalidToken as exc:
            logger.error("Token Fernet inválido o HMAC fallido: %s", exc)
            raise DecryptionError("Token cifrado corrupto o con firma inválida.") from exc
        except Exception as exc:
            logger.error("Error inesperado al descifrar token Fernet: %s", exc)
            raise DecryptionError(f"Error al descifrar token: {exc}") from exc

    # Texto en plano heredado (migración retroactiva segura)
    return text
