from __future__ import annotations

import re
from typing import Any, Iterable

from app.core.utils import ascii_fold, get_value

COVERAGE_PATTERNS = [
    re.compile(r"\btodos\s+los\s+documentos\b"),
    re.compile(r"\btodo\s+el\s+corpus\b"),
    re.compile(r"\btodos\s+los\s+informes\b"),
    re.compile(r"\btodos\s+los\s+archivos\b"),
    re.compile(r"\bresumen\b|\bresume\b"),
    re.compile(r"\bpanorama\b"),
    re.compile(r"\bcompara\b|\bcomparar\b|\bcomparacion\b"),
    re.compile(r"\bcuales\s+son\s+los\s+documentos\b"),
    re.compile(r"\bque\s+documentos\b"),
    re.compile(r"\blista\s+de\s+documentos\b"),
    re.compile(r"\bcobertura\b"),
]


def needs_coverage(query: str) -> bool:
    normalized = ascii_fold(query).lower()
    return any(pattern.search(normalized) for pattern in COVERAGE_PATTERNS)


def merge_coverage_results(
    base: Iterable[Any],
    extra: Iterable[Any],
    *,
    max_documents: int = 10,
) -> list[Any]:
    merged = list(base or [])
    seen = {
        str(get_value(item, "document_id", ""))
        for item in merged
        if get_value(item, "document_id")
    }
    for item in extra or []:
        document_id = str(get_value(item, "document_id", ""))
        if not document_id or document_id in seen:
            continue
        if len(seen) >= max_documents:
            break
        merged.append(item)
        seen.add(document_id)
    return merged
