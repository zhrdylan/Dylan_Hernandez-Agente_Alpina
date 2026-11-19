from __future__ import annotations

import time
from typing import Callable, Sequence

import httpx

from app.config import settings

COHERE_EMBED_URL = "https://api.cohere.com/v1/embed"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class EmbeddingError(RuntimeError):
    pass


def _extract_embeddings(payload: dict) -> list[list[float]]:
    embeddings = payload.get("embeddings")
    if isinstance(embeddings, dict):
        embeddings = embeddings.get("float")
    if not isinstance(embeddings, list) or not embeddings:
        raise EmbeddingError("La respuesta de Cohere no contiene embeddings.")
    return embeddings


def _post_with_retries(
    client: httpx.Client,
    payload: dict,
    *,
    api_key: str,
    max_retries: int,
    sleep_fn: Callable[[float], None],
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.post(
                COHERE_EMBED_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            sleep_fn(min(2**attempt, 30))
            continue

        if response.status_code == 200:
            return response

        if response.status_code in RETRYABLE_STATUS and attempt < max_retries:
            retry_after = response.headers.get("retry-after")
            if retry_after and retry_after.replace(".", "", 1).isdigit():
                delay = float(retry_after)
            else:
                delay = min(2**attempt, 30)
            sleep_fn(delay)
            continue

        raise EmbeddingError(
            f"Cohere respondió {response.status_code}: {response.text[:300]}"
        )

    raise EmbeddingError(f"No se pudo conectar con Cohere: {last_error}")


_DEFAULT_CLIENT: httpx.Client | None = None


def _get_default_client(timeout: float = 60.0) -> httpx.Client:
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None or _DEFAULT_CLIENT.is_closed:
        _DEFAULT_CLIENT = httpx.Client(
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20, keepalive_expiry=60.0),
        )
    return _DEFAULT_CLIENT


def embed_texts(
    texts: Sequence[str],
    *,
    input_type: str = "search_document",
    model: str | None = None,
    batch_size: int = 64,
    max_retries: int = 5,
    timeout: float = 60.0,
    client: httpx.Client | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> list[list[float]]:
    if not texts:
        return []
    if not settings.cohere_api_key:
        raise EmbeddingError("COHERE_API_KEY no está configurada en el archivo .env.")
    if batch_size <= 0:
        raise ValueError("batch_size debe ser mayor que cero.")

    normalized = [str(text).strip() for text in texts]
    if any(not text for text in normalized):
        raise EmbeddingError("No se pueden generar embeddings de textos vacíos.")

    model = model or settings.cohere_embed_model
    provided_client = client is not None
    active_client = client or _get_default_client(timeout)

    try:
        vectors: list[list[float]] = []
        for start in range(0, len(normalized), batch_size):
            batch = normalized[start : start + batch_size]
            response = _post_with_retries(
                active_client,
                {
                    "model": model,
                    "texts": batch,
                    "input_type": input_type,
                    "truncate": "END",
                },
                api_key=settings.cohere_api_key,
                max_retries=max_retries,
                sleep_fn=sleep_fn,
            )
            try:
                payload = response.json()
            except ValueError as exc:
                raise EmbeddingError("Cohere devolvió una respuesta no JSON.") from exc

            batch_vectors = _extract_embeddings(payload)
            if len(batch_vectors) != len(batch):
                raise EmbeddingError(
                    "Cohere devolvió una cantidad de embeddings distinta a la solicitada."
                )
            for vector in batch_vectors:
                if len(vector) != settings.cohere_embed_dim:
                    raise EmbeddingError(
                        f"Embedding de dimensión {len(vector)}; se esperaban "
                        f"{settings.cohere_embed_dim}."
                    )
            vectors.extend(batch_vectors)
        return vectors
    finally:
        if provided_client and client is not None:
            # Si el llamador proporcionó un cliente ad-hoc exclusivo, no lo cerramos aquí
            pass


def embed_query(text: str, **kwargs) -> list[float]:
    vectors = embed_texts([text], input_type="search_query", **kwargs)
    return vectors[0]


def vector_literal(vector: Sequence[float]) -> str:
    """Formato textual que Postgres acepta para castear a vector."""
    return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"
