from __future__ import annotations

import base64
import io
import time
from typing import Any

from app.config import settings

OCR_PROMPT = """Transcribe literalmente todo el texto visible en la imagen, respetando el orden de lectura.
No resumas, no interpretes y no agregues información que no aparezca en la imagen.
Conserva números, tildes, signos y encabezados tal como están.
Si hay tablas, transcribe cada fila en una línea y separa las celdas con tabulaciones.
Si algún fragmento es ilegible, escribe [ilegible] en su lugar.
Devuelve únicamente la transcripción, sin comentarios ni bloques de código."""

RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


class OcrError(RuntimeError):
    pass


def build_ocr_prompt() -> str:
    return OCR_PROMPT


def clean_ocr_output(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()
        if "\n" in cleaned:
            first_line, rest = cleaned.split("\n", 1)
            if first_line.strip().lower() in {"text", "txt", "markdown", "md"}:
                cleaned = rest.strip()
    return cleaned


def _is_retryable(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return status_code in RETRYABLE_STATUS_CODES

    name = type(exc).__name__.lower()
    return any(
        token in name
        for token in ("ratelimit", "timeout", "connection", "internalserver", "serviceunavailable")
    )


def _create_client() -> Any:
    if not settings.groq_api_key:
        raise OcrError("GROQ_API_KEY no está configurada en el archivo .env.")

    from groq import Groq

    return Groq(api_key=settings.groq_api_key)


def ocr_image_windows(
    image_bytes: bytes,
    *,
    lang: str = "es-ES",
) -> str:
    if not image_bytes:
        raise OcrError("La imagen para OCR está vacía.")

    try:
        import winocr
        from PIL import Image
    except Exception as exc:
        raise OcrError(
            f"OCR local no disponible: {type(exc).__name__}: {exc}"
        ) from exc

    def recognize(image) -> str:
        result = winocr.recognize_pil_sync(image, lang=lang)
        raw_text = result.get("text") if isinstance(result, dict) else str(result)
        return clean_ocr_output(str(raw_text or ""))

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        best_text = recognize(image)
        if len(best_text) < 20:
            for angle in (90, 180, 270):
                candidate = recognize(image.rotate(angle, expand=True))
                if len(candidate) > len(best_text):
                    best_text = candidate
    except Exception as exc:
        raise OcrError(
            f"OCR local falló: {type(exc).__name__}: {exc}"
        ) from exc

    return best_text


def ocr_image_jpeg(
    image_bytes: bytes,
    *,
    client: Any | None = None,
    model: str | None = None,
    prompt: str | None = None,
    max_retries: int = 5,
    retry_delay: float = 1.0,
    max_completion_tokens: int = 4096,
) -> str:
    if not image_bytes:
        raise OcrError("La imagen para OCR está vacía.")

    groq_client = client if client is not None else _create_client()
    encoded = base64.b64encode(image_bytes).decode("ascii")
    model_name = model or settings.groq_model_fallback
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt or OCR_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                },
            ],
        }
    ]

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            completion = groq_client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0,
                top_p=0.9,
                max_completion_tokens=max_completion_tokens,
                seed=42,
            )
            content = completion.choices[0].message.content
            cleaned = clean_ocr_output(content or "")
            if not cleaned:
                raise OcrError("El OCR devolvió texto vacío.")
            return cleaned
        except OcrError:
            raise
        except Exception as exc:
            last_error = exc
            if not _is_retryable(exc) or attempt >= max_retries:
                raise OcrError(f"OCR falló: {type(exc).__name__}: {exc}") from exc
            time.sleep(retry_delay * (2**attempt))

    raise OcrError(f"OCR falló tras {max_retries + 1} intentos: {last_error}")
