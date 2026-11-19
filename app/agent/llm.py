from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

from groq import Groq

from app.config import settings


class LlmError(RuntimeError):
    pass


GPT_OSS_MODELS = {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}
STRUCTURED_MODELS = GPT_OSS_MODELS | {"qwen/qwen3.8-27b", "meta-models/muse-spark-open"}
_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        if not settings.groq_api_key:
            raise LlmError("GROQ_API_KEY no está configurada en el archivo .env.")
        _client = Groq(api_key=settings.groq_api_key, timeout=25.0, max_retries=0)
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
    reasoning = {"reasoning_effort": "low"} if model in GPT_OSS_MODELS else {}

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=max_tokens,
                top_p=0.9,
                seed=42,
                response_format=response_format,
                **reasoning,
            )
            choice = response.choices[0]
            if choice.finish_reason != "stop":
                raise LlmError(f"Groq no completó la respuesta ({choice.finish_reason}).")
            content = choice.message.content or ""
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
            delay = 2**attempt
            if status == 429:
                headers = getattr(getattr(exc, "response", None), "headers", {})
                try:
                    delay = max(delay, float(headers.get("retry-after", 0)))
                except (TypeError, ValueError):
                    pass
            if retryable and attempt < max_retries and delay <= 4:
                sleep_fn(delay)
                continue
            break

    if isinstance(last_error, LlmError):
        raise last_error
    status = getattr(last_error, "status_code", None)
    code = getattr(last_error, "code", None)
    details = ", ".join(str(value) for value in (type(last_error).__name__, status, code) if value)
    raise LlmError(f"Groq ({model}) falló: {details}.") from last_error


def chat_json(
    model: str,
    system: str,
    user: str,
    *,
    temperature: float = 0.0,
    max_tokens: int = 800,
    fallback_model: str | None = None,
    schema: dict | None = None,
    max_retries: int = 1,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    models = dict.fromkeys(candidate for candidate in (model, fallback_model) if candidate)
    errors = []
    for candidate in models:
        response_format = (
            {"type": "json_schema", "json_schema": {**schema, "strict": True}}
            if schema and candidate in STRUCTURED_MODELS
            else {"type": "json_object"}
        )
        budget = min(max_tokens, 750) if candidate != model else max_tokens
        try:
            content = _chat(
                candidate,
                messages,
                temperature=temperature,
                max_tokens=budget,
                response_format=response_format,
                max_retries=max_retries,
                sleep_fn=sleep_fn,
            )
            payload = parse_json_content(content)
            if schema and not set(schema["schema"]["required"]).issubset(payload):
                raise LlmError("El modelo devolvió un objeto JSON incompleto.")
            return payload
        except LlmError as exc:
            errors.append(str(exc))
    raise LlmError("; ".join(errors))


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
