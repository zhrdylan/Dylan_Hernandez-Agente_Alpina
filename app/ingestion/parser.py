from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image

LOW_TEXT_THRESHOLD = 80

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HORIZONTAL_SPACE = re.compile(r"[^\S\n]+")
_MANY_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(slots=True)
class PageText:
    page_number: int
    text: str
    method: str = "text"


def normalize_text(text: str) -> str:
    if not text:
        return ""

    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace("\xa0", " ").replace("\u2007", " ").replace("\u202f", " ")
    cleaned = _CONTROL_CHARS.sub("", cleaned)

    lines = [_HORIZONTAL_SPACE.sub(" ", line).strip() for line in cleaned.split("\n")]
    cleaned = "\n".join(lines)
    cleaned = _MANY_BLANK_LINES.sub("\n\n", cleaned)
    return cleaned.strip()


def is_low_text(text: str, threshold: int = LOW_TEXT_THRESHOLD) -> bool:
    return len(normalize_text(text)) < threshold


def extract_pdf_pages(path: Path) -> list[PageText]:
    pages: list[PageText] = []
    with pdfplumber.open(path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            try:
                raw_text = page.extract_text() or ""
            except Exception:
                raw_text = ""
            pages.append(
                PageText(
                    page_number=index,
                    text=normalize_text(raw_text),
                    method="text",
                )
            )
    return pages


def render_page_jpeg(
    path: Path,
    page_number: int,
    dpi: int = 220,
    quality: int = 85,
) -> bytes:
    if page_number < 1:
        raise ValueError("El número de página debe ser mayor o igual a 1.")

    document = pdfium.PdfDocument(str(path))
    try:
        if page_number > len(document):
            raise ValueError(
                f"La página {page_number} no existe; el documento tiene {len(document)} páginas."
            )
        page = document[page_number - 1]
        try:
            bitmap = page.render(scale=dpi / 72)
            image: Image.Image = bitmap.to_pil().convert("RGB")
        finally:
            page.close()
    finally:
        document.close()

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()
