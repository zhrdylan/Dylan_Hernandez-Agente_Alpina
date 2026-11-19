from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from app.db.connection import connect

router = APIRouter(prefix="/api/products", tags=["products"])

ORDER_BY_WHITELIST = {
    "name": "name asc",
    "price_asc": "case when price > 0 then 0 else 1 end, price asc",
    "price_desc": "case when price > 0 then 0 else 1 end, price desc",
    "protein": "case when protein_g is null then 1 else 0 end, protein_g desc",
}


@router.get("")
def list_products(
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=24, ge=1, le=96),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="name"),
    available: bool | None = None,
    label: str | None = Query(default=None, max_length=100),
) -> dict:
    """Consulta paginada del catálogo oficial de productos Alpina."""
    columns = """
        select id, ean, name, brand, presentation,
               price::float8 as price, currency,
               protein_g::float8 as protein_g, claims, ingredients,
               allergens, availability, source_url, source_page,
               coalesce(metadata->>'image_url', '') as image_url,
               verified_at, metadata
        from public.products
    """
    clauses: list[str] = []
    params: list[Any] = []
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        clauses.append(
            """
            (name ilike %s
               or ean ilike %s
               or id ilike %s
               or claims::text ilike %s
               or metadata->>'description' ilike %s
               or metadata->>'label' ilike %s)
            """
        )
        params.extend([pattern] * 6)
    if available is True:
        clauses.append("availability = 'Disponible'")
    elif available is False:
        clauses.append("coalesce(availability, '') <> 'Disponible'")
    if label and label.strip():
        clauses.append("metadata->>'label' ilike %s")
        params.append(f"%{label.strip()}%")

    where = " where " + " and ".join(clauses) if clauses else ""
    order_sql = ORDER_BY_WHITELIST.get(sort, "name asc")

    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select count(*) as total from public.products " + where,
                params,
            )
            total = int(cur.fetchone()["total"])
            cur.execute(
                columns
                + where
                + f"""
                order by {order_sql}
                limit %s offset %s
                """,
                [*params, limit, offset],
            )
            items = list(cur.fetchall())
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{product_id}")
def get_product(product_id: str) -> dict:
    """Detalle completo de un producto oficial por su SKU."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                select id, ean, name, brand, presentation,
                       price::float8 as price, currency,
                       protein_g::float8 as protein_g, claims, ingredients,
                       allergens, availability, source_url, source_page,
                       coalesce(metadata->>'image_url', '') as image_url,
                       verified_at, metadata
                from public.products
                where id = %s
                """,
                (product_id,),
            )
            product = cur.fetchone()
            if not product:
                raise HTTPException(status_code=404, detail="Producto no encontrado.")
            return product
