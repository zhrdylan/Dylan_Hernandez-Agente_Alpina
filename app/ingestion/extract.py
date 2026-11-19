from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.config import settings
from app.ingestion.ocr import ocr_image_jpeg
from app.ingestion.parser import (
    extract_pdf_pages,
    is_low_text,
    normalize_text,
    render_page_jpeg,
)

OcrFn = Callable[[bytes], str]


def save_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    part.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(part, path)


def extract_document(
    doc: dict,
    pdf_path: Path,
    *,
    sha256: str | None = None,
    ocr_fn: OcrFn | None = None,
    ocr_model: str | None = None,
    max_ocr_pages: int | None = None,
    ocr_delay: float = 0.0,
    progress: Callable[[str], None] | None = None,
    previous: dict | None = None,
) -> dict:
    pages = extract_pdf_pages(pdf_path)
    run_ocr = ocr_fn or (lambda image: ocr_image_jpeg(image))
    ocr_attempts = 0
    errors: list[dict] = []

    previous_pages: dict[int, dict] = {}
    if previous and previous.get("sha256") == sha256:
        for item in previous.get("pages") or []:
            try:
                previous_pages[int(item.get("page"))] = item
            except (TypeError, ValueError):
                continue

    for page in pages:
        if not is_low_text(page.text):
            continue

        previous_page = previous_pages.get(page.page_number)
        if previous_page and previous_page.get("method") == "ocr":
            previous_text = str(previous_page.get("text") or "")
            if previous_text.strip():
                page.text = previous_text
                page.method = "ocr"
                continue

        if max_ocr_pages is not None and ocr_attempts >= max_ocr_pages:
            page.method = "ocr_skipped"
            continue

        ocr_attempts += 1
        if progress is not None:
            progress(f"OCR página {page.page_number}")

        try:
            image = render_page_jpeg(pdf_path, page.page_number)
            text = normalize_text(run_ocr(image))
            if text:
                page.text = text
                page.method = "ocr"
            else:
                page.method = "ocr_empty"
                errors.append(
                    {
                        "page": page.page_number,
                        "error": "El OCR devolvió texto vacío.",
                        "kind": "empty",
                    }
                )
        except Exception as exc:
            page.method = "ocr_failed"
            errors.append(
                {
                    "page": page.page_number,
                    "error": f"{type(exc).__name__}: {exc}",
                    "kind": "failed",
                }
            )

        if ocr_delay > 0:
            time.sleep(ocr_delay)

    stats = {
        "text_pages": sum(1 for page in pages if page.method == "text"),
        "ocr_pages": sum(1 for page in pages if page.method == "ocr"),
        "ocr_skipped": sum(1 for page in pages if page.method == "ocr_skipped"),
        "ocr_failed": sum(1 for page in pages if page.method == "ocr_failed"),
        "empty_pages": sum(1 for page in pages if not page.text.strip()),
        "total_chars": sum(len(page.text) for page in pages),
    }
    if stats["total_chars"] == 0 or (pages and stats["empty_pages"] == len(pages)):
        status = "failed"
    elif errors or stats["ocr_skipped"] > 0 or stats["ocr_failed"] > 0:
        status = "partial"
    else:
        status = "complete"

    return {
        "id": doc["id"],
        "title": doc["title"],
        "category": doc.get("category"),
        "doc_type": doc.get("doc_type"),
        "version": doc.get("version"),
        "country": doc.get("country"),
        "language": doc.get("language"),
        "vigente": doc.get("vigente"),
        "filename": doc.get("filename") or pdf_path.name,
        "sha256": sha256,
        "page_count": len(pages),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "ocr_model": ocr_model or settings.groq_model_fallback,
        "status": status,
        "stats": stats,
        "errors": errors,
        "pages": [
            {
                "page": page.page_number,
                "text": page.text,
                "method": page.method,
                "chars": len(page.text),
            }
            for page in pages
        ],
    }
