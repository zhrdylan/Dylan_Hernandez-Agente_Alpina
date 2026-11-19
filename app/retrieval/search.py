from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Sequence

import psycopg
from psycopg.rows import dict_row

from app.config import settings
from app.ingestion.embed import embed_query, vector_literal
from app.retrieval.coverage import merge_coverage_results

# PostgreSQL's websearch_to_tsquery('spanish', ...) maneja automáticamente
# la lematización y el filtrado nativo de stopwords en español.
# Se mantiene FTS_STOPWORDS vacío por retrocompatibilidad.
FTS_STOPWORDS: set[str] = set()

COMMON_FIELDS = (
    "chunk_id",
    "document_id",
    "document_title",
    "version_id",
    "version",
    "page_start",
    "page_end",
    "section",
    "content",
    "source_url",
    "category",
    "doc_type",
    "country",
    "vigente",
    "is_current",
)


@dataclass(slots=True)
class SearchFilters:
    document_ids: Sequence[str] | None = None
    categories: Sequence[str] | None = None
    doc_type: str | None = None
    country: str | None = "CO"
    vigente: bool | None = True
    coverage: bool = False

    def sql(self) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if self.document_ids:
            clauses.append("d.id = any(%s)")
            params.append(list(self.document_ids))
        if self.categories:
            clauses.append("d.category = any(%s)")
            params.append(list(self.categories))
        if self.doc_type:
            clauses.append("d.doc_type = %s")
            params.append(self.doc_type)
        if self.country:
            clauses.append("d.country = %s")
            params.append(self.country)
        if self.vigente is not None:
            clauses.append("d.vigente = %s")
            params.append(self.vigente)

        if not clauses:
            return "", []
        return " and " + " and ".join(clauses), params


@dataclass(slots=True)
class SearchResult:
    chunk_id: str
    document_id: str
    document_title: str
    version_id: str
    version: str
    page_start: int
    page_end: int
    section: str | None
    content: str
    source_url: str | None
    category: str
    doc_type: str | None
    country: str
    vigente: bool
    is_current: bool
    vector_score: float | None = None
    fts_score: float | None = None
    vector_rank: int | None = None
    fts_rank: int | None = None
    rrf_score: float = 0.0


def clean_search_query(query: str) -> str:
    """Limpia y normaliza la consulta para búsqueda textual sin eliminar términos de contenido."""
    text = (query or "").lower()
    text = re.sub(r"[^\wáéíóúñü]+", " ", text, flags=re.IGNORECASE)
    return " ".join(text.split())


clean_fts_query = clean_search_query


def _common_fields(row: dict) -> dict:
    return {
        "chunk_id": str(row["chunk_id"]),
        "document_id": row["document_id"],
        "document_title": row["document_title"],
        "version_id": str(row["version_id"]),
        "version": row["version"],
        "page_start": int(row["page_start"]),
        "page_end": int(row["page_end"]),
        "section": row["section"],
        "content": row["content"],
        "source_url": row["source_url"],
        "category": row["category"],
        "doc_type": row["doc_type"],
        "country": row["country"],
        "vigente": bool(row["vigente"]),
        "is_current": bool(row["is_current"]),
    }


def reciprocal_rank_fusion(
    vector_rows: Sequence[dict],
    fts_rows: Sequence[dict],
    *,
    rrf_k: int = 60,
    limit: int = 20,
) -> list[SearchResult]:
    fused: dict[str, SearchResult] = {}

    for rank, row in enumerate(vector_rows, start=1):
        common = _common_fields(row)
        fused[common["chunk_id"]] = SearchResult(
            **common,
            vector_score=float(row["vector_score"]),
            vector_rank=rank,
            rrf_score=1.0 / (rrf_k + rank),
        )

    for rank, row in enumerate(fts_rows, start=1):
        common = _common_fields(row)
        existing = fused.get(common["chunk_id"])
        if existing is None:
            fused[common["chunk_id"]] = SearchResult(
                **common,
                fts_score=float(row["fts_score"]),
                fts_rank=rank,
                rrf_score=1.0 / (rrf_k + rank),
            )
        else:
            existing.fts_score = float(row["fts_score"])
            existing.fts_rank = rank
            existing.rrf_score += 1.0 / (rrf_k + rank)

    ordered = sorted(fused.values(), key=lambda item: item.rrf_score, reverse=True)
    return ordered[:limit]


def _vector_rows(
    conn: psycopg.Connection,
    query_literal: str,
    filters: SearchFilters,
    limit: int,
) -> list[dict]:
    filter_sql, filter_params = filters.sql()
    sql = f"""
        select
            c.id as chunk_id,
            c.document_id,
            d.title as document_title,
            c.version_id,
            v.version,
            c.page_start,
            c.page_end,
            c.section,
            c.content,
            d.source_url,
            d.category,
            d.doc_type,
            d.country,
            d.vigente,
            v.is_current,
            1 - (e.embedding <=> %s::vector) as vector_score
        from public.chunks c
        join public.chunk_embeddings e on e.chunk_id = c.id
        join public.document_versions v on v.id = c.version_id
        join public.documents d on d.id = c.document_id
        where v.is_current
          and e.model = %s
          and e.dimension = %s
          {filter_sql}
        order by e.embedding <=> %s::vector
        limit %s
    """
    params = [
        query_literal,
        settings.cohere_embed_model,
        settings.cohere_embed_dim,
        *filter_params,
        query_literal,
        limit,
    ]
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def first_chunks_for_documents(
    conn: psycopg.Connection,
    filters: SearchFilters,
    *,
    exclude_ids: Sequence[str] | None = None,
    limit: int = 6,
) -> list[SearchResult]:
    filter_sql, filter_params = filters.sql()
    exclude_sql = ""
    params: list[Any] = [*filter_params]
    if exclude_ids:
        exclude_sql = " and not (c.document_id = any(%s))"
        params.append(list(exclude_ids))
    params.append(limit)

    sql = f"""
        select distinct on (c.document_id)
            c.id as chunk_id,
            c.document_id,
            d.title as document_title,
            c.version_id,
            v.version,
            c.page_start,
            c.page_end,
            c.section,
            c.content,
            d.source_url,
            d.category,
            d.doc_type,
            d.country,
            d.vigente,
            v.is_current,
            null::float8 as vector_score
        from public.chunks c
        join public.document_versions v on v.id = c.version_id
        join public.documents d on d.id = c.document_id
        where v.is_current
          {filter_sql}
          {exclude_sql}
        order by c.document_id, c.chunk_index
        limit %s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    return [
        SearchResult(
            **_common_fields(row),
            vector_score=None,
            fts_score=None,
            rrf_score=0.0,
        )
        for row in rows
    ]


def semantic_search(
    conn: psycopg.Connection,
    query: str,
    *,
    filters: SearchFilters | None = None,
    limit: int = 12,
    min_similarity: float = 0.25,
    embed_fn: Callable[[str], list[float]] = embed_query,
) -> list[SearchResult]:
    """Búsqueda semántica vectorial usando embeddings de Cohere y pgvector."""
    query = query.strip()
    if not query:
        return []

    filters = filters or SearchFilters()
    query_vector = embed_fn(query)
    query_literal = vector_literal(query_vector)

    raw_rows = _vector_rows(conn, query_literal, filters, limit=limit * 2)
    results: list[SearchResult] = []
    for rank, row in enumerate(raw_rows, start=1):
        score = float(row["vector_score"])
        if score < min_similarity:
            continue
        common = _common_fields(row)
        results.append(
            SearchResult(
                **common,
                vector_score=score,
                vector_rank=rank,
                fts_score=None,
                fts_rank=None,
                rrf_score=score,
            )
        )
        if len(results) >= limit:
            break
    return results


def coverage_search(
    conn: psycopg.Connection,
    query: str,
    *,
    filters: SearchFilters | None = None,
    base_limit: int = 8,
    extra_documents: int = 6,
    max_documents: int = 10,
    min_similarity: float = 0.25,
) -> list[SearchResult]:
    active_filters = filters or SearchFilters()
    base = semantic_search(
        conn,
        query,
        filters=active_filters,
        limit=base_limit,
        min_similarity=min_similarity,
    )
    if not active_filters.coverage:
        return base

    seen = {result.document_id for result in base}
    extra = first_chunks_for_documents(
        conn,
        active_filters,
        exclude_ids=seen,
        limit=extra_documents,
    )
    return merge_coverage_results(base, extra, max_documents=max_documents)


def hybrid_search(
    conn: psycopg.Connection,
    query: str,
    *,
    filters: SearchFilters | None = None,
    vector_k: int = 10,
    fts_k: int = 10,
    rrf_k: int = 60,
    limit: int = 20,
    embed_fn: Callable[[str], list[float]] = embed_query,
) -> list[SearchResult]:
    """Alias compatible hacia atrás que redirige a semantic_search puro."""
    return semantic_search(
        conn,
        query,
        filters=filters,
        limit=limit,
        embed_fn=embed_fn,
        min_similarity=0.0,
    )
