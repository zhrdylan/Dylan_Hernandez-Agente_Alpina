from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.retrieval.search import SearchResult, clean_search_query


def format_cop(value: Any) -> str:
    if value is None:
        return "No consta"
    amount = float(value)
    return f"${amount:,.0f}".replace(",", ".")


def _format_protein(value: Any) -> str:
    if value is None:
        return "No consta"
    return f"{float(value):g} g"


def product_row_to_result(row: dict) -> SearchResult:
    product_id = str(row["id"])
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    description = " ".join(str(metadata.get("description") or "").split())
    label = str(metadata.get("label") or "").strip()
    claims = list(row.get("claims") or [])
    claims_text = (
        "; ".join(str(claim) for claim in claims)
        if claims
        else "No consta en la fuente oficial (sin sellos o declaraciones adicionales)."
    )
    ingredients_raw = row.get("ingredients")
    ingredients = (
        str(ingredients_raw).strip()
        if ingredients_raw
        else "No consta en la fuente oficial (no declarado)."
    )
    allergens_raw = row.get("allergens")
    allergens = (
        str(allergens_raw).strip()
        if allergens_raw
        else "No consta en la fuente oficial (no declarado)."
    )
    availability = str(row.get("availability") or "No consta")

    source_page = int(row.get("source_page") or 1)
    verified_at = row.get("verified_at") or datetime.now(timezone.utc)
    version = verified_at.strftime("%Y-%m")

    content = "\n".join(
        [
            f"Producto: {row['name']}",
            f"SKU: {product_id}",
            f"Presentación: {row.get('presentation') or 'No consta'}",
            f"EAN: {row.get('ean') or 'No consta'}",
            f"Precio: {format_cop(row.get('price'))} {row.get('currency') or 'COP'}",
            f"Proteína: {_format_protein(row.get('protein_g'))}",
            f"Claims: {claims_text}",
            f"Categoría: {label or 'No consta'}",
            f"Descripción: {description or 'No consta en la fuente oficial.'}",
            f"Ingredientes: {ingredients}",
            f"Alérgenos: {allergens}",
            f"Disponibilidad: {availability}",
            f"Fuente: {row.get('source_url') or ''}",
        ]
    )

    score = row.get("score")
    return SearchResult(
        chunk_id=f"product-{product_id}",
        document_id=product_id.upper(),
        document_title=str(row["name"]),
        version_id=f"product-{product_id}",
        version=version,
        page_start=source_page,
        page_end=source_page,
        section="Producto",
        content=content,
        source_url=row.get("source_url"),
        category="nutrition",
        doc_type="producto",
        country="CO",
        vigente=True,
        is_current=True,
        vector_score=float(score) if score is not None else 1.0,
        fts_score=None,
        vector_rank=1,
        fts_rank=None,
        rrf_score=1.0,
    )


PRODUCT_CONVERSATIONAL_WORDS = {
    "dime", "dame", "muestra", "muestrame", "muéstrame", "busca", "buscar", "encuentra",
    "explicame", "explícame", "explica", "cual", "cuales", "cuál", "cuáles", "que", "qué",
    "cuanto", "cuánto", "cuesta", "vale", "precio", "precios", "costo", "costos", "valor",
    "ingrediente", "ingredientes", "alergeno", "alergenos", "alérgeno", "alérgenos",
    "informacion", "información", "nutricional", "tabla", "ficha", "tecnica", "técnica",
    "por", "favor", "gracias", "de", "del", "el", "la", "los", "las", "un", "una",
    "unos", "unas", "tiene", "contiene", "es", "son", "sobre", "en", "para", "con", "y", "o",
}


def _search_rows(
    conn: psycopg.Connection,
    search_query: str,
    value: str,
    pattern: str,
    limit: int,
) -> list[dict]:
    sql = """
        select
            id, ean, name, brand, presentation, price, currency,
            protein_g, claims, ingredients, allergens, availability,
            source_url, source_page, verified_at, metadata,
            ts_rank_cd(
                search_tsv,
                websearch_to_tsquery('spanish', %s)
            ) as score
        from public.products
        where search_tsv @@ websearch_to_tsquery('spanish', %s)
           or ean = %s
           or id = %s
           or name ilike %s
           or brand ilike %s
           or claims::text ilike %s
        order by score desc, name asc
        limit %s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            sql,
            (
                search_query,
                search_query,
                value,
                value,
                pattern,
                pattern,
                pattern,
                limit,
            ),
        )
        return list(cur.fetchall())


def search_products(
    conn: psycopg.Connection,
    query: str,
    *,
    limit: int = 3,
) -> list[SearchResult]:
    raw_query = (query or "").strip()
    if not raw_query:
        return []

    # Prioridad 1: Búsqueda exacta por SKU o EAN sin distorsión de normalización (F12)
    tokens = raw_query.split()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select
                id, ean, name, brand, presentation, price, currency,
                protein_g, claims, ingredients, allergens, availability,
                source_url, source_page, verified_at, metadata,
                1.0 as score
            from public.products
            where upper(id) = upper(%s) or ean = %s
            limit %s
            """,
            (raw_query, raw_query, limit),
        )
        exact_rows = list(cur.fetchall())
        if not exact_rows and len(tokens) > 1:
            for token in tokens:
                clean_tok = token.strip(",.;:()[]{}")
                if len(clean_tok) >= 3:
                    cur.execute(
                        """
                        select
                            id, ean, name, brand, presentation, price, currency,
                            protein_g, claims, ingredients, allergens, availability,
                            source_url, source_page, verified_at, metadata,
                            1.0 as score
                        from public.products
                        where upper(id) = upper(%s) or ean = %s
                        limit %s
                        """,
                        (clean_tok, clean_tok, limit),
                    )
                    exact_rows = list(cur.fetchall())
                    if exact_rows:
                        break

    if exact_rows:
        return [product_row_to_result(row) for row in exact_rows]

    cleaned = clean_search_query(query)
    if not cleaned:
        return []

    # Extraer términos clave del producto descartando verbos y relleno conversacional
    core_tokens = [w for w in cleaned.split() if w not in PRODUCT_CONVERSATIONAL_WORDS]
    core_query = " ".join(core_tokens) if core_tokens else cleaned

    # 1. Búsqueda con términos núcleo (ej: 'alpinito fresa', 'bon yurt')
    pattern = f"%{core_query}%"
    rows = _search_rows(conn, core_query, core_query, pattern, limit)

    # 2. Si no hay resultados y hay múltiples tokens, probar OR query
    if not rows and len(core_tokens) > 1:
        or_query = " OR ".join(core_tokens)
        rows = _search_rows(conn, or_query, core_query, pattern, limit)

    # 3. Si aún no hay resultados y core_query difiere de cleaned, intentar con cleaned
    if not rows and core_query != cleaned:
        raw_pattern = f"%{cleaned}%"
        rows = _search_rows(conn, cleaned, cleaned, raw_pattern, limit)

    # 4. Fallback final: si el primer token es una marca o producto conocido (ej: alpinito, finesse, defensis)
    if not rows and core_tokens:
        first_token = core_tokens[0]
        if len(first_token) >= 3:
            token_pattern = f"%{first_token}%"
            rows = _search_rows(conn, first_token, first_token, token_pattern, limit)

    return [product_row_to_result(row) for row in rows]
