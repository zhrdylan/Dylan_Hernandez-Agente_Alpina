from __future__ import annotations

from typing import Any, Iterable


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _citation_value(citation: Any, key: str, default: Any = None) -> Any:
    if isinstance(citation, dict):
        return citation.get(key, default)
    return getattr(citation, key, default)


def build_retrieval_items(
    retrieved: Iterable[Any],
    citations: Iterable[Any],
    *,
    preview_chars: int = 260,
) -> list[dict]:
    cited_pages = set()
    cited_documents = set()
    for citation in citations or []:
        document_id = str(_citation_value(citation, "document_id", "")).upper()
        if not document_id:
            continue
        cited_documents.add(document_id)
        try:
            page = int(_citation_value(citation, "page", 0) or 0)
        except (TypeError, ValueError):
            page = 0
        if page:
            cited_pages.add((document_id, page))

    items: list[dict] = []
    for item in retrieved or []:
        document_id = str(_value(item, "document_id", "")).upper()
        page = int(_value(item, "page_start", 0) or 0)
        page_end = int(_value(item, "page_end", page) or page)
        kind = "product" if document_id.startswith("SKU-") else "document"
        cited = (
            document_id in cited_documents
            if kind == "product"
            else (document_id, page) in cited_pages
        )
        content = " ".join(str(_value(item, "content", "")).split())
        items.append(
            {
                "document_id": document_id,
                "title": _value(item, "document_title", ""),
                "page": page,
                "page_end": page_end,
                "version": _value(item, "version", ""),
                "category": _value(item, "category", ""),
                "doc_type": _value(item, "doc_type", ""),
                "kind": kind,
                "image_url": (
                    _value(item, "image_url")
                    or (_value(item, "metadata") or {}).get("image_url")
                    if isinstance(_value(item, "metadata"), dict)
                    else None
                ),
                "vector_score": _value(item, "vector_score"),
                "fts_score": _value(item, "fts_score"),
                "rrf_score": _value(item, "rrf_score"),
                "content_preview": content[:preview_chars],
                "cited": cited,
            }
        )
    return items


def summarize_retrieval(items: Iterable[dict]) -> dict[str, int]:
    item_list = list(items or [])
    documents = {
        item["document_id"]
        for item in item_list
        if item.get("kind") == "document" and item.get("document_id")
    }
    chunks = sum(1 for item in item_list if item.get("kind") == "document")
    products = sum(1 for item in item_list if item.get("kind") == "product")
    return {
        "retrieved_chunks": chunks,
        "unique_documents": len(documents),
        "product_count": products,
        "retrieved_count": len(item_list),
    }
