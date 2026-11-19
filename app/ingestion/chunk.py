from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.ingestion.parser import normalize_text

DEFAULT_MAX_CHARS = 1200
DEFAULT_OVERLAP_CHARS = 150
DEFAULT_MIN_CHARS = 20

_HEADING_PREFIX = re.compile(
    r"^(?:ART[IÍ]CULO|CAP[IÍ]TULO|T[IÍ]TULO|SECCI[OÓ]N|PARTE|ANEXO|"
    r"RESOLUCI[OÓ]N|DECRETO|LEY|ACUERDO|CIRCULAR|ORDEN|POL[IÍ]TICA)\b",
    re.IGNORECASE,
)
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;:])\s+")
_WHITESPACE = re.compile(r"\s+")


@dataclass(slots=True)
class Chunk:
    index: int
    page_start: int
    page_end: int
    section: str | None
    content: str
    token_count: int


@dataclass(slots=True)
class _Piece:
    text: str
    section: str | None


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def detect_heading(line: str) -> str | None:
    candidate = _WHITESPACE.sub(" ", line).strip(" .:-\t")
    if not candidate or len(candidate) > 140:
        return None
    if _HEADING_PREFIX.match(candidate):
        return candidate
    letters = [character for character in candidate if character.isalpha()]
    if (
        len(letters) >= 6
        and candidate.upper() == candidate
        and len(candidate.split()) <= 12
    ):
        return candidate
    return None


def _split_text(text: str, max_chars: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    buffer = ""
    for sentence in _SENTENCE_SPLIT.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:
            if buffer:
                parts.append(buffer)
                buffer = ""
            for start in range(0, len(sentence), max_chars):
                part = sentence[start : start + max_chars].strip()
                if part:
                    parts.append(part)
            continue
        candidate = f"{buffer} {sentence}".strip() if buffer else sentence
        if len(candidate) <= max_chars:
            buffer = candidate
        else:
            if buffer:
                parts.append(buffer)
            buffer = sentence
    if buffer:
        parts.append(buffer)
    return parts


def _tail(text: str, max_chars: int) -> str:
    if max_chars <= 0 or not text:
        return ""
    if len(text) <= max_chars:
        return text.strip()
    tail = text[-max_chars:]
    space = tail.find(" ")
    if space >= 0:
        tail = tail[space + 1 :]
    return tail.strip()


def _heading_from_paragraph(paragraph: str) -> str | None:
    lines = [line.strip() for line in paragraph.split("\n") if line.strip()]
    if not lines:
        return None

    heading = detect_heading(lines[0])
    if not heading or len(lines) == 1:
        return heading

    first_line = lines[0]
    second_line = lines[1]
    continuation = re.search(
        r"(?:\b(?:y|e|de|del|la|el|los|las|para|por|en|con|sin|o|u))$",
        first_line,
        re.IGNORECASE,
    )
    second_is_upper = len(second_line) >= 4 and second_line.upper() == second_line
    if continuation or second_is_upper:
        combined = f"{first_line} {second_line}".strip()
        if len(combined) <= 140:
            combined_heading = detect_heading(combined)
            if combined_heading:
                return combined_heading
    return heading


def _page_pieces(
    text: str,
    max_chars: int,
    current_section: str | None,
) -> tuple[list[_Piece], str | None]:
    pieces: list[_Piece] = []
    paragraphs = [part.strip() for part in _PARAGRAPH_SPLIT.split(text) if part.strip()]
    for paragraph in paragraphs:
        heading = _heading_from_paragraph(paragraph)
        if heading:
            current_section = heading
        for part in _split_text(paragraph, max_chars):
            pieces.append(_Piece(part, current_section))
    return pieces, current_section


def _append_chunk(
    chunks: list[Chunk],
    content: str,
    *,
    page: int,
    section: str | None,
    max_chars: int,
    min_chars: int,
) -> None:
    content = content.strip()
    if not content:
        return
    if (
        len(content) < min_chars
        and chunks
        and chunks[-1].page_end == page
        and chunks[-1].section == section
    ):
        merged = f"{chunks[-1].content}\n\n{content}".strip()
        if len(merged) <= max_chars:
            chunks[-1].content = merged
            chunks[-1].token_count = estimate_tokens(merged)
            return
    chunks.append(
        Chunk(
            index=len(chunks),
            page_start=page,
            page_end=page,
            section=section,
            content=content,
            token_count=estimate_tokens(content),
        )
    )


def _chunk_page(
    page: int,
    pieces: Sequence[_Piece],
    *,
    max_chars: int,
    overlap_chars: int,
    min_chars: int,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    buffer = ""
    buffer_section: str | None = None
    previous = ""

    def flush() -> None:
        nonlocal buffer, previous
        if buffer:
            _append_chunk(
                chunks,
                buffer,
                page=page,
                section=buffer_section,
                max_chars=max_chars,
                min_chars=min_chars,
            )
            previous = buffer
            buffer = ""

    for piece in pieces:
        if buffer and piece.section != buffer_section:
            flush()
        if not buffer:
            buffer = piece.text
            buffer_section = piece.section
            continue

        candidate = f"{buffer}\n\n{piece.text}".strip()
        if len(candidate) <= max_chars:
            buffer = candidate
            continue

        flush()
        overlap = ""
        if overlap_chars > 0 and previous and buffer_section == piece.section:
            overlap = _tail(previous, overlap_chars)
        candidate = f"{overlap}\n\n{piece.text}".strip() if overlap else piece.text
        if len(candidate) > max_chars:
            candidate = piece.text
        buffer = candidate
        buffer_section = piece.section

    flush()
    return chunks


def chunk_pages(
    pages: Iterable[Mapping[str, Any]],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> list[Chunk]:
    if max_chars <= 0:
        raise ValueError("max_chars debe ser mayor que cero.")
    if overlap_chars < 0:
        raise ValueError("overlap_chars no puede ser negativo.")
    if min_chars < 0:
        raise ValueError("min_chars no puede ser negativo.")

    chunks: list[Chunk] = []
    current_section: str | None = None

    for raw_page in pages:
        page_number = int(raw_page.get("page", 0))
        if page_number < 1:
            continue
        text = normalize_text(str(raw_page.get("text", "")))
        if len(text) < min_chars:
            continue

        pieces, current_section = _page_pieces(text, max_chars, current_section)
        if not pieces:
            continue

        page_chunks = _chunk_page(
            page_number,
            pieces,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
            min_chars=min_chars,
        )
        for chunk in page_chunks:
            chunks.append(
                Chunk(
                    index=len(chunks),
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    section=chunk.section,
                    content=chunk.content,
                    token_count=chunk.token_count,
                )
            )

    return chunks
