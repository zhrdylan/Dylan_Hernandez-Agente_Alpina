from __future__ import annotations

from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings
from app.core.utils import ascii_fold


class R2StorageError(RuntimeError):
    pass


class R2Storage:
    def __init__(self, *, client: Any | None = None, bucket: str | None = None) -> None:
        self.bucket = (bucket if bucket is not None else settings.r2_bucket) or ""
        if not self.bucket:
            raise R2StorageError("R2_BUCKET no está configurado.")

        if client is None:
            if not self.is_configured():
                raise R2StorageError(
                    "Credenciales R2 incompletas: revisa R2_ACCESS_KEY_ID, "
                    "R2_SECRET_ACCESS_KEY y R2_ACCOUNT_ID."
                )
            client = self._build_client()

        self.client = client

    @staticmethod
    def is_configured() -> bool:
        return all(
            [
                settings.r2_account_id,
                settings.r2_access_key_id,
                settings.r2_secret_access_key,
                settings.r2_bucket,
            ]
        )

    @staticmethod
    def endpoint() -> str:
        if settings.r2_endpoint:
            return settings.r2_endpoint
        return f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"

    @staticmethod
    def _sanitize_metadata(
        metadata: dict[str, str] | None,
    ) -> dict[str, str] | None:
        if not metadata:
            return None
        sanitized: dict[str, str] = {}
        for key, value in metadata.items():
            sanitized[ascii_fold(str(key))[:128]] = ascii_fold(str(value))[:1024]
        return sanitized

    @classmethod
    def _build_client(cls):
        return boto3.client(
            "s3",
            endpoint_url=cls.endpoint(),
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
                retries={"max_attempts": 5, "mode": "standard"},
                connect_timeout=10,
                read_timeout=60,
            ),
        )

    def upload_bytes(
        self,
        data: bytes,
        key: str,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        params: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": data,
        }
        if content_type:
            params["ContentType"] = content_type
        clean_metadata = self._sanitize_metadata(metadata)
        if clean_metadata:
            params["Metadata"] = clean_metadata

        try:
            self.client.put_object(**params)
        except (BotoCoreError, ClientError) as exc:
            raise R2StorageError(f"No se pudo subir {key}: {type(exc).__name__}") from exc
        return key

    def upload_file(
        self,
        path: Path,
        key: str,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        extra_args: dict[str, Any] = {}
        if content_type:
            extra_args["ContentType"] = content_type
        clean_metadata = self._sanitize_metadata(metadata)
        if clean_metadata:
            extra_args["Metadata"] = clean_metadata

        try:
            if extra_args:
                self.client.upload_file(
                    str(path),
                    self.bucket,
                    key,
                    ExtraArgs=extra_args,
                )
            else:
                self.client.upload_file(str(path), self.bucket, key)
        except (BotoCoreError, ClientError) as exc:
            raise R2StorageError(f"No se pudo subir {key}: {type(exc).__name__}") from exc
        return key

    def get_bytes(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise R2StorageError(f"No se pudo leer {key}: {type(exc).__name__}") from exc

        body = response.get("Body")
        if body is None:
            raise R2StorageError(f"R2 no devolvió cuerpo para {key}.")
        data = body.read()
        if isinstance(data, bytes):
            return data
        return bytes(data)

    def generate_presigned_url(self, key: str, *, expires_in: int = 900) -> str:
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except (BotoCoreError, ClientError) as exc:
            raise R2StorageError(f"No se pudo firmar {key}: {type(exc).__name__}") from exc

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise R2StorageError(f"No se pudo borrar {key}: {type(exc).__name__}") from exc

    def head(self, key: str) -> dict:
        try:
            return self.client.head_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise R2StorageError(f"No se pudo consultar {key}: {type(exc).__name__}") from exc
