from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

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


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", str(text or ""))
    return value.encode("ascii", "ignore").decode("ascii").lower()


def needs_coverage(query: str) -> bool:
    normalized = _normalize(query)
    return any(pattern.search(normalized) for pattern in COVERAGE_PATTERNS)


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def merge_coverage_results(
    base: Iterable[Any],
    extra: Iterable[Any],
    *,
    max_documents: int = 10,
) -> list[Any]:
    merged = list(base or [])
    seen = {
        str(_value(item, "document_id", ""))
        for item in merged
        if _value(item, "document_id")
    }
    for item in extra or []:
        document_id = str(_value(item, "document_id", ""))
        if not document_id or document_id in seen:
            continue
        if len(seen) >= max_documents:
            break
        merged.append(item)
        seen.add(document_id)
    return merged
