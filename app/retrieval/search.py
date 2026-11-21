from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Callable, Sequence

import psycopg
from psycopg.rows import dict_row

from app.config import settings
from app.ingestion.embed import EmbeddingError, embed_query, vector_literal
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
    focus_query: str | None = None

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
    focused_results: list[SearchResult] = []
    if active_filters.focus_query:
        with conn.transaction():
            focused = _fts_rows(conn, query, active_filters, limit=4)
        if focused:
            focused_results = reciprocal_rank_fusion([], focused, limit=base_limit)
            if not active_filters.coverage:
                return focused_results
        active_filters = replace(active_filters, focus_query=None)

    base = hybrid_search(
        conn,
        query,
        filters=active_filters,
        limit=base_limit,
        vector_k=base_limit * 2,
        fts_k=base_limit,
        min_similarity=min_similarity,
    )
    if not active_filters.coverage:
        return base

    if focused_results:
        focused_ids = {result.chunk_id for result in focused_results}
        base = [*focused_results, *(result for result in base if result.chunk_id not in focused_ids)][:base_limit]

    seen = {result.document_id for result in base}
    extra = first_chunks_for_documents(
        conn,
        active_filters,
        exclude_ids=seen,
        limit=extra_documents,
    )
    return merge_coverage_results(base, extra, max_documents=max_documents)


def _fts_rows(
    conn: psycopg.Connection,
    query: str,
    filters: SearchFilters,
    limit: int,
) -> list[dict]:
    terms = filters.focus_query or clean_search_query(query)
    if not terms:
        return []
    filter_sql, filter_params = filters.sql()
    order = "fts_score desc, document_id, chunk_id"
    if filters.focus_query:
        order = f"row_number() over (partition by document_id order by {order}), {order}"
    sql = f"""
        with ranked as (
            select c.id as chunk_id, c.document_id, d.title as document_title,
                   c.version_id, v.version, c.page_start, c.page_end, c.section, c.content,
                   d.source_url, d.category, d.doc_type, d.country, d.vigente, v.is_current,
                   ts_rank_cd(c.content_tsv, q.terms) as fts_score
            from public.chunks c
            join public.document_versions v on v.id = c.version_id
            join public.documents d on d.id = c.document_id
            cross join websearch_to_tsquery('spanish', %s) as q(terms)
            where v.is_current and c.content_tsv @@ q.terms {filter_sql}
        )
        select * from ranked
        order by {order}
        limit %s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (terms, *filter_params, limit))
        return list(cur.fetchall())


def hybrid_search(
    conn: psycopg.Connection,
    query: str,
    *,
    filters: SearchFilters | None = None,
    vector_k: int = 10,
    fts_k: int = 10,
    rrf_k: int = 60,
    limit: int = 20,
    min_similarity: float = 0.0,
    embed_fn: Callable[[str], list[float]] | None = None,
) -> list[SearchResult]:
    """Combina el índice de texto y la similitud vectorial mediante RRF."""
    query = query.strip()
    if not query:
        return []

    active_filters = filters or SearchFilters()
    vector_rows = []
    fts_rows = []
    vector_error = None
    fts_error = None
    try:
        vector = embed_fn(query) if embed_fn else embed_query(query, timeout=12.0, max_retries=1)
        with conn.transaction():
            rows = _vector_rows(conn, vector_literal(vector), active_filters, limit=vector_k)
            vector_rows = [row for row in rows if float(row["vector_score"]) >= min_similarity]
    except (EmbeddingError, psycopg.Error) as exc:
        vector_error = exc
    try:
        with conn.transaction():
            fts_rows = _fts_rows(conn, query, active_filters, limit=fts_k)
    except psycopg.Error as exc:
        fts_error = exc

    if not (vector_rows or fts_rows) and (vector_error or fts_error):
        raise (vector_error or fts_error)
    return reciprocal_rank_fusion(vector_rows, fts_rows, rrf_k=rrf_k, limit=limit)
