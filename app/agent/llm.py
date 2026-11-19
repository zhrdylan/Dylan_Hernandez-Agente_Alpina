from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

from groq import Groq

from app.config import settings


class LlmError(RuntimeError):
    pass


_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        if not settings.groq_api_key:
            raise LlmError("GROQ_API_KEY no está configurada en el archivo .env.")
        _client = Groq(api_key=settings.groq_api_key)
    return _client


def parse_json_content(content: str) -> dict:
    text = (content or "").strip()
    if not text:
        raise LlmError("El modelo devolvió una respuesta vacía.")

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, dict):
        return payload

    decoder = json.JSONDecoder()
    candidates: list[dict] = []
    for match in re.finditer(r"\{", text):
        try:
            candidate, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            candidates.append(candidate)

    if candidates:
        return candidates[-1]

    raise LlmError("La respuesta del modelo no contiene un objeto JSON válido.")


def _chat(
    model: str,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
    response_format: dict | None,
    max_retries: int,
    sleep_fn: Callable[[float], None],
) -> str:
    client = _get_client()
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=0.9,
                seed=42,
                response_format=response_format,
            )
            content = response.choices[0].message.content or ""
            if not content.strip():
                raise LlmError("El modelo devolvió contenido vacío.")
            return content
        except Exception as exc:
            last_error = exc
            status = getattr(exc, "status_code", None)
            name = type(exc).__name__.lower()
            retryable = (
                status in {429, 500, 502, 503, 504}
                or "connection" in name
                or "timeout" in name
            )
            if retryable and attempt < max_retries:
                sleep_fn(min(2**attempt, 30))
                continue
            break

    raise LlmError(f"Groq falló: {type(last_error).__name__}: {last_error}")


def chat_json(
    model: str,
    system: str,
    user: str,
    *,
    temperature: float = 0.0,
    max_tokens: int = 800,
    fallback_model: str | None = None,
    max_retries: int = 2,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    try:
        content = _chat(
            model,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            max_retries=max_retries,
            sleep_fn=sleep_fn,
        )
        return parse_json_content(content)
    except Exception as primary_error:
        if fallback_model and fallback_model != model:
            try:
                content = _chat(
                    fallback_model,
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=None,
                    max_retries=max_retries,
                    sleep_fn=sleep_fn,
                )
                return parse_json_content(content)
            except Exception as fallback_error:
                raise LlmError(
                    f"Modelo principal y fallback fallaron: "
                    f"{primary_error}; {fallback_error}"
                ) from fallback_error
        raise LlmError(str(primary_error)) from primary_error


def chat_text(
    model: str,
    system: str,
    user: str,
    *,
    temperature: float = 0.1,
    max_tokens: int = 1500,
    fallback_model: str | None = None,
    max_retries: int = 2,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> str:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        return _chat(
            model,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=None,
            max_retries=max_retries,
            sleep_fn=sleep_fn,
        )
    except Exception as primary_error:
        if fallback_model and fallback_model != model:
            try:
                return _chat(
                    fallback_model,
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=None,
                    max_retries=max_retries,
                    sleep_fn=sleep_fn,
                )
            except Exception as fallback_error:
                raise LlmError(
                    f"Modelo principal y fallback fallaron: "
                    f"{primary_error}; {fallback_error}"
                ) from fallback_error
        raise LlmError(str(primary_error)) from primary_error
