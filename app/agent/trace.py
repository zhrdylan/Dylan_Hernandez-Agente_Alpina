from __future__ import annotations

from typing import Any, Iterable

from app.core.utils import get_value


def build_retrieval_items(
    retrieved: Iterable[Any],
    citations: Iterable[Any],
    *,
    preview_chars: int = 260,
) -> list[dict]:
    cited_pages = set()
    cited_documents = set()
    for citation in citations or []:
        document_id = str(get_value(citation, "document_id", "")).upper()
        if not document_id:
            continue
        cited_documents.add(document_id)
        try:
            page = int(get_value(citation, "page", 0) or 0)
        except (TypeError, ValueError):
            page = 0
        if page:
            cited_pages.add((document_id, page))

    items: list[dict] = []
    for item in retrieved or []:
        document_id = str(get_value(item, "document_id", "")).upper()
        page = int(get_value(item, "page_start", 0) or 0)
        page_end = int(get_value(item, "page_end", page) or page)
        kind = "product" if document_id.startswith("SKU-") else "document"
        cited = (
            document_id in cited_documents
            if kind == "product"
            else (document_id, page) in cited_pages
        )
        content = " ".join(str(get_value(item, "content", "")).split())
        items.append(
            {
                "document_id": document_id,
                "title": get_value(item, "document_title", ""),
                "page": page,
                "page_end": page_end,
                "version": get_value(item, "version", ""),
                "category": get_value(item, "category", ""),
                "doc_type": get_value(item, "doc_type", ""),
                "kind": kind,
                "image_url": (
                    get_value(item, "image_url")
                    or (get_value(item, "metadata") or {}).get("image_url")
                    if isinstance(get_value(item, "metadata"), dict)
                    else None
                ),
                "vector_score": get_value(item, "vector_score"),
                "fts_score": get_value(item, "fts_score"),
                "rrf_score": get_value(item, "rrf_score"),
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
