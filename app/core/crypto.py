from __future__ import annotations

import logging
import os
import subprocess
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import DATA_DIR, settings

logger = logging.getLogger(__name__)
_dev_key_lock = Lock()


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
def _configured_fernet(raw_keys: str) -> MultiFernet:
    try:
        return MultiFernet([Fernet(key.strip().encode("ascii")) for key in raw_keys.split(",")])
    except ValueError as exc:
        raise CryptoError("CHAT_ENCRYPTION_KEY contiene una clave Fernet inválida.") from exc


def _restrict_key_file(path: Path) -> None:
    if path.is_symlink():
        raise CryptoError("El archivo de clave de desarrollo debe ser un archivo local regular.")
    if os.name != "nt":
        path.chmod(0o600)
        return

    # Windows restringe el acceso mediante la DACL del archivo.
    script = """
    $ErrorActionPreference = 'Stop'
    $path = $env:ALPINA_DEV_KEY_PATH
    $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $acl = [System.Security.AccessControl.FileSecurity]::new()
    $acl.SetSecurityDescriptorSddlForm("D:P(A;;FA;;;$sid)", [System.Security.AccessControl.AccessControlSections]::Access)
    [System.IO.File]::SetAccessControl($path, $acl)
    """
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, "ALPINA_DEV_KEY_PATH": str(path)},
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=True, capture_output=True, timeout=15,
    )


def _create_dev_key(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as key_file:
        temporary_path = Path(key_file.name)
    try:
        _restrict_key_file(temporary_path)
        temporary_path.write_bytes(Fernet.generate_key())
        os.link(temporary_path, path)
    except FileExistsError:
        # Otro proceso ya publicó su clave completa.
        pass
    finally:
        temporary_path.unlink(missing_ok=True)


@lru_cache(maxsize=1)
def _dev_fernet(key_path: Path) -> MultiFernet:
    try:
        if not key_path.exists() and not key_path.is_symlink():
            _create_dev_key(key_path)
        _restrict_key_file(key_path)
        return MultiFernet([Fernet(key_path.read_bytes().strip())])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise CryptoError("No se pudo leer o proteger la clave de desarrollo.") from exc


def get_fernet() -> MultiFernet:
    """Usa la primera clave configurada para cifrar y las restantes durante la rotación."""
    raw_keys = settings.chat_encryption_key.strip()
    if raw_keys:
        return _configured_fernet(raw_keys)
    if settings.is_production:
        raise CryptoError("CHAT_ENCRYPTION_KEY es obligatoria en producción.")
    with _dev_key_lock:
        return _dev_fernet(DATA_DIR / ".dev_chat_key")


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
    """Descifra únicamente tokens Fernet autenticados. Los valores vacíos se conservan."""
    if cipher is None or cipher == "":
        return ""

    try:
        return get_fernet().decrypt(str(cipher).encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError("El valor almacenado no es un token cifrado válido.") from exc
    except (CryptoError, UnicodeError) as exc:
        raise DecryptionError("No se pudo descifrar el contenido almacenado.") from exc


def rotate_encrypted_text(cipher: Optional[str]) -> str:
    """Rota un token Fernet cifrado con una clave anterior a la clave primaria activa.

    Si el texto es plano o vacío, lo cifra directamente con la clave primaria.
    """
    if cipher is None:
        return ""
    text = str(cipher)
    if not text:
        return ""
    if text.startswith("gAAAAA"):
        try:
            fernet = get_fernet()
            rotated_bytes = fernet.rotate(text.encode("utf-8"))
            return rotated_bytes.decode("utf-8")
        except Exception as exc:
            logger.error("Error al rotar token cifrado: %s", exc)
            raise CryptoError(f"Error al rotar token: {exc}") from exc
    return encrypt_text(text)
